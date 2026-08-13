from base.backend.app import App as BaseApp

import os
import flask

import backend
import backend.training
import backend.pipeline
import backend.settings
from . import root_detection
from . import root_tracking



class App(BaseApp):
    def __init__(self, *args, **kw):
        # Packaged Windows releases contain the manifest but fetch the large
        # verified model files on first launch. Source/Docker users can prefetch
        # them explicitly to make startup deterministic.
        backend.settings.ensure_pretrained_models()
        
        super().__init__(*args, **kw)
        if self.is_reloader:
            return

        self.pipeline_manager = backend.pipeline.PipelineManager(
            self.settings,
            cache_path=self.cache_path,
        )

        self.route('/process_root_tracking', methods=['GET', 'POST'])(self.process_root_tracking)
        self.route('/postprocess_detection/<filename>')(self.postprocess_detection)
        self.route('/compile_tracking_results', methods=['POST'])(self.compile_tracking_results)
        self.route('/api/pipeline/runs', methods=['POST'])(self.create_pipeline_run)
        self.route('/api/pipeline/runs/<run_id>', methods=['GET'])(self.get_pipeline_run)
        self.route('/api/pipeline/runs/<run_id>/cancel', methods=['POST'])(self.cancel_pipeline_run)
        self.route('/api/pipeline/runs/<run_id>/retry', methods=['POST'])(self.retry_pipeline_run)

    def postprocess_detection(self, filename):
        #FIXME: code duplication
        full_path = os.path.join(self.cache_path, filename)
        if not os.path.exists(full_path):
            flask.abort(404)
        
        result = root_detection.postprocess_segmentation_file(full_path)
        result['segmentation'] = os.path.basename(result['segmentation'])
        result['skeleton']     = os.path.basename(result['skeleton'])
        return flask.jsonify(result)
    

    def process_root_tracking(self):
        if flask.request.method=='POST':
            data   = flask.request.get_json(force=True)
            fname0 = os.path.join(self.cache_path, data['filename0'])
            fname1 = os.path.join(self.cache_path, data['filename1'])
            result = root_tracking.process(fname0, fname1, self.settings, data)
        else:
            fname0 = os.path.join(self.cache_path, flask.request.args['filename0'])
            fname1 = os.path.join(self.cache_path, flask.request.args['filename1'])
            result = root_tracking.process(fname0, fname1, self.settings)
        
        if isinstance(result, root_tracking.TooManyRootsError):
            return flask.jsonify({
                'success': 'TOO_MANY_ROOTS',
                'state': 'skipped',
                'code': 'too_many_roots',
                'message': 'Tracking was skipped because the configured root threshold was exceeded.',
            })
        
        return flask.jsonify({
            'points0':         result['points0'].tolist(),
            'points1':         result['points1'].tolist(),
            'growthmap'     :  os.path.basename(result['growthmap']),
            'growthmap_rgba':  os.path.basename(result['growthmap_rgba']),
            'segmentation0' :  os.path.basename(result['segmentation0']),
            'segmentation1' :  os.path.basename(result['segmentation1']),
            'success'       :  result['success'],
            'n_matched_points'   : result['n_matched_points'],
            'tracking_model'     : result['tracking_model'],
            'segmentation_model' : result['segmentation_model'],
            'statistics'         : result['statistics'],
        })
    
    def compile_tracking_results(self):
        file_pairs = flask.request.get_json(force=True)['file_pairs']
        return root_tracking.compile_results_into_zip(file_pairs)

    def create_pipeline_run(self):
        request_data = flask.request.get_json(force=True) or {}
        try:
            run = self.pipeline_manager.create(
                request_data.get('filenames', []),
                request_data.get('file_pairs', []),
            )
        except ValueError as exc:
            return flask.jsonify({
                'code': 'invalid_pipeline_request',
                'message': str(exc),
                'retryable': False,
            }), 400
        except RuntimeError as exc:
            return flask.jsonify({
                'code': 'pipeline_busy',
                'message': str(exc),
                'retryable': True,
            }), 409
        return flask.jsonify(run.snapshot()), 202

    def get_pipeline_run(self, run_id):
        try:
            return flask.jsonify(self.pipeline_manager.get(run_id).snapshot())
        except KeyError as exc:
            return flask.jsonify({
                'code': 'pipeline_not_found',
                'message': str(exc),
                'retryable': False,
            }), 404

    def cancel_pipeline_run(self, run_id):
        try:
            run = self.pipeline_manager.get(run_id)
        except KeyError as exc:
            return flask.jsonify({
                'code': 'pipeline_not_found',
                'message': str(exc),
                'retryable': False,
            }), 404
        run.request_cancel()
        return flask.jsonify(run.snapshot()), 202

    def retry_pipeline_run(self, run_id):
        try:
            run = self.pipeline_manager.get(run_id)
            run.retry_failed()
        except KeyError as exc:
            return flask.jsonify({
                'code': 'pipeline_not_found',
                'message': str(exc),
                'retryable': False,
            }), 404
        except RuntimeError as exc:
            return flask.jsonify({
                'code': 'pipeline_not_retryable',
                'message': str(exc),
                'retryable': False,
            }), 409
        return flask.jsonify(run.snapshot()), 202

    #override    #TODO: unify
    def training(self):
        requestform  = flask.request.get_json(force=True)
        options      = requestform['options']
        if options['training_type'] not in ['detection', 'exclusion_mask']:
            raise NotImplementedError()

        imagefiles   = requestform['filenames']
        imagefiles   = [os.path.join(self.cache_path, fname) for fname in imagefiles]
        targetfiles  = backend.training.find_targetfiles(imagefiles)
        if not all([os.path.exists(fname) for fname in imagefiles]) or not all(targetfiles):
            flask.abort(404)
        
        backend.training.start_training(imagefiles, targetfiles, options, self.settings)
        return 'OK'
    
