

RootsTraining = class extends BaseTraining {
    static active_run_id = undefined
    static terminal_states = ['completed', 'cancelled', 'failed']
    static training_states = {}
    static imported_labels = new Map()
    static start_pending = false
    static cancel_requested = false
    static upload_request = undefined
    static active_options = undefined
    static pending_submission = undefined

    static clear_imported_labels(){
        this.imported_labels = new Map()
        $('#training-reviewed-labels-checkbox').prop('checked', false)
        this.update_number_of_training_files_info()
    }

    static forget_imported_label(filename){
        if(this.imported_labels.delete(filename)){
            $('#training-reviewed-labels-checkbox').prop('checked', false)
            this.update_number_of_training_files_info()
        }
    }

    static register_imported_label(filename, label){
        this.imported_labels.set(filename, label)
        $('#training-reviewed-labels-checkbox').prop('checked', false)
        this.update_number_of_training_files_info()
    }

    //override
    static refresh_tab(){
        super.refresh_tab()
        this.update_number_of_training_files_info()
    }
    
    // Detection predictions are never selected as training labels automatically.
    static get_selected_files(){
        return Array.from(this.imported_labels.keys()).filter(name => !!GLOBAL.files[name])
    }

    //override
    static get_training_options(){
        const training_type = $('#training-model-type').dropdown('get value');
        return {
            training_type       : training_type,
            learning_rate       : Number($('#training-learning-rate')[0].value),
            epochs              : Number($('#training-number-of-epochs')[0].value),
        };
    }

    static async on_start_training(){
        if(this.active_run_id || this.start_pending || this.pending_submission)
            return

        const filenames = this.get_selected_files()
        const options = this.get_training_options()
        if(!filenames.length || !$('#training-reviewed-labels-checkbox').is(':checked')){
            $('body').toast({
                message: 'Load a small set of reviewed labels and confirm their review before training.',
                class: 'error', displayTime: 0, closeIcon: true,
            })
            return
        }
        this.start_pending = true
        this.cancel_requested = false
        this.training_states[options.training_type] = 'running'
        $('#training-new-modelname-field').hide()
        try {
            this.show_modal()
            await this.upload_training_data(filenames)
            this.check_upload_cancellation()
            const request_id = Array.from(crypto.getRandomValues(new Uint8Array(16)))
                .map(value => value.toString(16).padStart(2, '0')).join('')
            this.active_options = options
            this.pending_submission = {
                request_id: request_id,
                filenames: filenames,
                label_filenames: filenames.map(filename => this.imported_labels.get(filename).name),
                options: options,
                label_review: {source: 'user_reviewed', confirmed: true},
            }
            const result = await this.submit_or_reconnect_training(options)
            await this.refresh_training_settings()
            return result
        } catch(error) {
            this.handle_training_error(error, options)
        } finally {
            this.start_pending = false
            this.upload_request = undefined
        }
    }

    static handle_training_error(error, options){
        if(this.cancel_requested && !this.active_run_id && !this.pending_submission){
            this.training_states[options.training_type] = 'cancelled'
            this.interrupted_modal()
            return
        }
        console.error(error)
        // A lost poll response does not establish that the server-side job failed.
        this.training_states[options.training_type] = this.pending_submission
            ? 'unknown' : (this.active_run_id ? 'running' : 'failed')
        const diagnostic = error?.responseJSON?.diagnostic_id
        const detail = RootSecurity.error_message(error, 'Training failed.')
        const message = this.pending_submission
            ? `Training submission could not be confirmed. Use Retry to recover the same request${this.cancel_requested ? ' and cancel it' : ''}. ${detail}`
            : (this.active_run_id
                ? `Connection to training was interrupted. Use Retry to reconnect to the same run. ${detail}`
                : detail)
        this.fail_modal(message)
        $('body').toast({
            message: diagnostic ? `${message} Diagnostic ID: ${diagnostic}` : message,
            class: 'error', displayTime: 0, closeIcon: true,
        })
    }

    static async submit_or_reconnect_training(options){
        if(this.pending_submission){
            let run
            try {
                run = await RootSecurity.request('/api/training/runs', 'POST', this.pending_submission)
            } catch(error) {
                // Input rejection happens before job creation. Let the user
                // correct those options; transport failures retain the identity.
                if([400, 413, 415, 422].includes(Number(error?.status)))
                    this.pending_submission = undefined
                throw error
            }
            this.active_run_id = run.id
            this.pending_submission = undefined
        }
        if(this.cancel_requested)
            await RootSecurity.request(`/api/training/runs/${this.active_run_id}/cancel`, 'POST')
        return this.poll_until_finished(options)
    }

    static async refresh_training_settings(){
        try {
            await GLOBAL.App.Settings.load_settings()
            this.update_model_info()
        } catch(error) {
            // Settings refresh is independent of the confirmed training outcome.
            $('body').toast({
                message: 'Training has finished, but model information could not be refreshed. Open Settings to reconnect.',
                class: 'error', displayTime: 0, closeIcon: true,
            })
        }
    }

    static async poll_until_finished(options){
        while(this.active_run_id){
            const run = await RootSecurity.request(
                `/api/training/runs/${this.active_run_id}`,
                'GET',
            )
            $('#training-modal .progress').progress({
                percent: Math.min(Number(run.progress) * 100, 99),
                autoSuccess: false,
            })
            $('#training-modal .label').text(
                run.state == 'cancelling' ? 'Stopping training...' : 'Training in progress...'
            )
            if(this.terminal_states.includes(run.state)){
                this.training_states[options.training_type] = run.state
                if(run.state == 'completed')
                    this.success_modal()
                else if(run.state == 'cancelled')
                    this.interrupted_modal()
                else {
                    const message = run.error?.message ?? run.result?.message ?? 'Training failed.'
                    this.fail_modal(message)
                    const diagnostic = run.error?.diagnostic_id
                    $('body').toast({
                        message: diagnostic ? `${message} Diagnostic ID: ${diagnostic}` : message,
                        class: 'error',
                        displayTime: 0,
                        closeIcon: true,
                    })
                }
                this.active_run_id = undefined
                return run
            }
            await sleep(300)
        }
    }

    static show_modal(){
        super.show_modal()
        $('#training-modal #cancel-training-button')
            .prop('disabled', false)
            .attr('aria-disabled', 'false')
            .removeClass('disabled loading')
            .show()
        $('#training-modal #retry-training-button, #training-modal #close-training-button').hide()
    }

    static interrupted_modal(){
        const $progress = $('#training-modal .ui.progress')
        $progress.removeClass('active success').addClass('error')
        $progress.find('.label').text('Training interrupted. You can retry with the same settings.')
        $('#training-modal #cancel-training-button').hide()
        $('#training-modal #retry-training-button, #training-modal #close-training-button').show()
        $('#training-modal').modal({closable:true})
    }

    static fail_modal(message){
        const $progress = $('#training-modal .ui.progress')
        $progress.removeClass('active success').addClass('error')
        $progress.find('.label').text(
            message || 'Training failed. Review the console details, then retry.'
        )
        $('#training-modal #cancel-training-button').hide()
        $('#training-modal #retry-training-button, #training-modal #close-training-button').show()
        $('#training-modal').modal({closable:true})
    }

    static success_modal(){
        const $progress = $('#training-modal .ui.progress')
        $progress.progress({percent:100, autoSuccess:false})
            .removeClass('active error').addClass('success')
        $progress.find('.label').text('Training finished')
        $('#training-modal #cancel-training-button, #training-modal #retry-training-button').hide()
        $('#training-modal #close-training-button').show()
        $('#training-modal').modal({closable:true})
    }

    static async on_retry_training(){
        if(this.start_pending)
            return
        if(this.active_run_id || this.pending_submission){
            const options = this.active_options ?? this.get_training_options()
            this.start_pending = true
            try {
                this.show_modal()
                const result = await this.submit_or_reconnect_training(options)
                await this.refresh_training_settings()
                return result
            } catch(error) {
                this.handle_training_error(error, options)
            } finally {
                this.start_pending = false
            }
            return
        }
        $('#training-modal').modal('hide')
        return this.on_start_training()
    }

    static check_upload_cancellation(){
        if(this.cancel_requested)
            throw new Error('Training upload was cancelled.')
    }

    static async upload_training_data(filenames){
        for(const filename of filenames){
            for(const file of [GLOBAL.files[filename], this.imported_labels.get(filename)]){
                this.check_upload_cancellation()
                await RootsFileInput.ensure_uploaded(file, {
                    on_request: request => { this.upload_request = request },
                    is_cancelled: () => this.cancel_requested,
                })
                this.check_upload_cancellation()
            }
        }
    }

    //override
    static update_model_info(){
        const model_type  = $('#training-model-type').dropdown('get value');
        if(!model_type)
            return;
        
        super.update_model_info(model_type)
        const state = this.training_states[model_type]
        if(['cancelled', 'failed', 'running', 'unknown'].includes(state)){
            $('#training-new-modelname-field').hide()
            if(GLOBAL.settings.active_models[model_type] == '')
                $('#training-model-info-label').text(
                    state == 'cancelled'
                        ? '[INTERRUPTED - NOT SAVABLE]'
                        : '[INCOMPLETE - NOT SAVABLE]'
                )
        }
    }

    static update_number_of_training_files_info(){
        const n = this.get_selected_files().length;
        $('#training-number-of-files-info-label').text(n)
        $('#training-label-file-list').text(
            n ? this.get_selected_files().join(', ') : 'No annotations imported yet.'
        )
        $('#training-number-of-files-info-message').removeClass('hidden')
        const confirmed = $('#training-reviewed-labels-checkbox').is(':checked')
        $('#start-training-button')
            .prop('disabled', n == 0 || !confirmed)
            .attr('aria-disabled', String(n == 0 || !confirmed))
    }

    static async on_cancel_training(){
        this.cancel_requested = true
        this.upload_request?.abort?.()
        const $button = $('#training-modal #cancel-training-button')
            .prop('disabled', true)
            .attr('aria-disabled', 'true')
            .addClass('disabled loading')
        $('#training-modal .label').text('Stopping training safely...')
        try {
            if(this.active_run_id)
                await RootSecurity.request(
                    `/api/training/runs/${this.active_run_id}/cancel`,
                    'POST',
                )
            else if(this.pending_submission && !this.start_pending)
                await this.on_retry_training()
        } catch(error) {
            $button
                .prop('disabled', false)
                .attr('aria-disabled', 'false')
                .removeClass('disabled loading')
            $('body').toast({message:'Stopping failed.', class:'error'})
        }
        return false
    }

    static on_save_model(){
        const new_modelname = $('#training-new-modelname')[0].value
        RootSecurity.request('/save_model', 'POST', {
            newname: new_modelname,
            options: this.get_training_options(),
        })
            .done(_ => $('#training-new-modelname-field').hide())
            .fail(_ => $('body').toast({message:'Saving failed.', class:'error', displayTime:0, closeIcon:true}))
        $('#training-new-modelname')[0].value = ''
    }
}
