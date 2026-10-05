"""Model-free tests for the packaged acceptance harness; no running app required."""
import argparse
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
import urllib.error


SPEC = importlib.util.spec_from_file_location('api_acceptance', Path(__file__).with_name('api_acceptance.py'))
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class AcceptanceTests(unittest.TestCase):
    def runner(self, directory):
        args = argparse.Namespace(output=str(Path(directory) / 'evidence'),
                                  url='http://127.0.0.1:5000', http_timeout=1,
                                  device='cpu', run_timeout=1, poll_interval=0.001)
        return api.Acceptance(args, [], [])

    def test_only_loopback_origins(self):
        for value in ('http://127.0.0.1:5000/', 'http://localhost', 'http://[::1]:5000'):
            self.assertEqual(api.loopback_url(value), value.rstrip('/'))
        for value in ('https://localhost', 'http://192.168.1.2:5000',
                      'http://localhost/path', 'http://user:secret@localhost',
                      'http://localhost?x=1', 'http://localhost#fragment'):
            with self.assertRaises(ValueError):
                api.loopback_url(value)

    def test_pairs_sorted_within_observation_group(self):
        names = ['tube1_L001_20.04.24_scan.tif', 'tube2_L001_2024.04.10_scan.png',
                 'tube1_L001_10.04.2024_scan.tif', 'tube2_L001_2024.04.20_scan.png']
        self.assertEqual(api.chronological_pairs([Path(name) for name in names]),
                         [[names[2], names[0]], [names[1], names[3]]])

    def test_invalid_or_duplicate_dates_rejected(self):
        for names in (['tube_31.02.24_x.tif', 'tube_01.03.24_x.tif'],
                      ['tube_01.03.24_a.tif', 'tube_01.03.24_b.tif'],
                      ['tube1_01.03.24_x.tif', 'tube2_02.03.24_x.tif']):
            with self.assertRaises(ValueError):
                api.chronological_pairs([Path(name) for name in names])

    def test_redaction_recursive(self):
        value = {'token': 'secret', 'items': [{'X-RootDetector-Token': 'secret', 'ok': True}],
                 'settings': {'authorization': 'secret'}}
        self.assertEqual(api.redact(value), {'items': [{'ok': True}], 'settings': {}})
        self.assertNotIn('secret', str(api.HTTPFailure(403, value)))

    def test_comparison_ignores_run_id_but_not_points(self):
        run = {'pairs': [{'filename0': 'a', 'filename1': 'b', 'result': {
            'points0': [[1, 2]], 'points1': [[3, 4]], 'run_id': 'first',
            'tracking_matcher': {'seed': 123, 'seed_identity': {'hash': 'abc'}},
            'statistics': {'growth': 1}, 'match_device': 'cpu'}}]}
        changed = copy.deepcopy(run)
        changed['pairs'][0]['result']['run_id'] = 'second'
        self.assertEqual(api.comparison_record(run), api.comparison_record(changed))
        changed['pairs'][0]['result']['points0'][0][0] = 2
        self.assertNotEqual(api.comparison_record(run), api.comparison_record(changed))

    def test_evidence_directory_must_be_new(self):
        with tempfile.TemporaryDirectory() as directory:
            self.runner(directory)
            with self.assertRaises(FileExistsError):
                self.runner(directory)

    def test_lost_pipeline_creation_is_unconfirmed_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            runner.client = FakeClient([urllib.error.URLError('response lost')])
            with self.assertRaises(urllib.error.URLError):
                runner.create_run('pipeline', {'filenames': []})
            self.assertEqual(runner.unconfirmed_submission, 'pipeline')
            self.assertIsNone(runner.active)
            self.assertEqual(len(runner.client.calls), 1)

    def test_lost_training_creation_recovers_with_same_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            runner.client = FakeClient([urllib.error.URLError('response lost'), {'id': 'known'}])
            payload = {'request_id': 'a' * 32}
            self.assertEqual(runner.create_run('training', payload), {'id': 'known'})
            self.assertEqual(runner.client.calls[0], runner.client.calls[1])
            self.assertEqual(runner.active, ('training', 'known'))
            self.assertIsNone(runner.unconfirmed_submission)

    def test_poll_recovers_and_saves_terminal_state(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            runner.client = FakeClient([urllib.error.URLError('lost'), {'state': 'completed'}])
            self.assertEqual(runner.poll('pipeline', 'known', 'case'), {'state': 'completed'})
            self.assertIsNone(runner.active)
            self.assertTrue((runner.output / 'case-poll-error-1.json').is_file())
            self.assertTrue((runner.output / 'case-latest.json').is_file())

    def test_unconfirmed_submission_prevents_settings_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            runner.original_settings = {'use_gpu': False}
            runner.settings_changed = True
            runner.unconfirmed_submission = 'pipeline'
            runner.client = FakeClient([])
            runner.diagnostics = lambda tag: None
            runner.cleanup()
            self.assertEqual(runner.client.calls, [])
            self.assertEqual(runner.summary['cases'][0]['status'], 'unconfirmed')

    def test_local_sidecar_cannot_verify_wrong_or_missing_live_build(self):
        for live in ('', 'commit=deadbeef'):
            with tempfile.TemporaryDirectory() as directory:
                runner = self.runner(directory)
                supplied = Path(directory) / 'local-build.txt'
                supplied.write_text('commit=abcdef12345', encoding='utf-8')
                runner.args.build_info = str(supplied)
                runner.args.expected_commit = 'abcdef12345'
                with self.assertRaises(AssertionError):
                    runner.check_build(live)

    def test_matching_live_build_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            runner.args.build_info = None
            runner.args.expected_commit = 'abcdef12345'
            runner.check_build('commit=abcdef12345')
            self.assertTrue(runner.summary['build_provenance_verified'])

    def test_settings_rejects_unapplied_model_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            runner.args.detection_model = None
            original = {'active_models': {'detection': 'original'}, 'use_gpu': False,
                        'exmask_enabled': False, 'tracking_sampling_mode': 'legacy',
                        'tracking_exclusion_policy': 'first'}
            runner.original_settings = original
            runner.client = FakeClient([{}, {'settings': original}])
            with self.assertRaises(AssertionError):
                runner.settings('legacy', 'first', 'trained-model')

    def test_failed_cancellation_races_are_not_reported_as_success(self):
        for current_state in ('failed', 'running'):
            with tempfile.TemporaryDirectory() as directory:
                runner = self.runner(directory)
                runner.settings = lambda *args: None
                runner.client = FakeClient([{'id': 'known'}, {'state': current_state}, {'state': 'failed'}])
                runner.poll = lambda *args: {'state': 'failed'}
                with self.assertRaises(AssertionError):
                    runner.cancellation()
                self.assertFalse(any(item['status'] == 'not_exercised' for item in runner.summary['cases']))

    def test_lost_retry_response_keeps_known_run_for_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            runner.settings = lambda *args: None
            runner.client = FakeClient([{'id': 'known'}, {'state': 'running'},
                                       {'state': 'cancelling'}, urllib.error.URLError('lost retry')])
            def cancelled(*args):
                runner.active = None
                return {'state': 'cancelled'}
            runner.poll = cancelled
            with self.assertRaises(urllib.error.URLError):
                runner.cancellation()
            self.assertEqual(runner.active, ('pipeline', 'known'))

    def test_profile_validation_rejects_wrong_device_and_masks(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            runner.paths = [Path('a'), Path('b')]
            runner.pairs = [['a', 'b']]
            result = {'run_profile': {'sampling_mode': 'deterministic', 'exclusion_mask_policy': 'first'},
                      'match_device': 'cpu', 'tracking_matcher': {'seed': 123, 'seed_identity': {'hash': 'abc'}},
                      'exclusion_masks': {'observation0_present': False,
                                          'observation1_present': False, 'combined_pixels': 0}}
            run = {'state': 'completed', 'images': {'a': {'state': 'completed'}, 'b': {'state': 'completed'}},
                   'pairs': [{'id': 'pair', 'filename0': 'a', 'filename1': 'b', 'state': 'completed', 'result': result}]}
            self.assertEqual(runner.verify_run(run, 'deterministic', 'first'), 0)
            result['match_device'] = 'cuda'
            with self.assertRaises(AssertionError):
                runner.verify_run(run, 'deterministic', 'first')
            result['match_device'] = 'cpu'
            result['exclusion_masks']['combined_pixels'] = 1
            with self.assertRaises(AssertionError):
                runner.verify_run(run, 'deterministic', 'first')


if __name__ == '__main__':
    unittest.main()
