RootPipeline = class {
    static active_run_id = undefined
    static terminal_states = ['completed', 'completed_with_errors', 'cancelled', 'failed']
    static phase = 'idle'
    static upload_cancel_requested = false
    static current_upload_request = undefined
    static upload_rows = new Map()

    static on_files_ready(){
        this.active_run_id = undefined
        const disabled = Object.keys(GLOBAL.files).length == 0
        $('#pipeline-run-button')
            .toggleClass('disabled', disabled)
            .prop('disabled', disabled)
            .attr('aria-disabled', String(disabled))
    }

    static async on_run_analysis(event){
        event?.preventDefault()
        if($('#pipeline-run-button').hasClass('disabled'))
            return

        const filenames = Object.keys(GLOBAL.files)
        if(!filenames.length){
            this.show_error('Load at least one input image before starting analysis.')
            return
        }

        this.set_running(true)
        this.show_modal()
        this.phase = 'upload'
        this.upload_cancel_requested = false
        this.set_message('Preparing analysis: uploading input images...')
        this.set_progress(0, filenames.length)

        let current_filename = undefined
        let uploaded = 0
        try {
            for(const filename of filenames){
                if(this.upload_cancel_requested)
                    break
                current_filename = filename
                this.render_upload(filename, 'uploading', 'Sending to the local RootDetector process...')
                const upload = await RootsFileInput.ensure_uploaded(GLOBAL.files[filename], {
                    max_attempts: 3,
                    on_request: request => this.current_upload_request = request,
                    is_cancelled: () => this.upload_cancel_requested,
                    on_retry: (attempt, total, delay, error) => {
                        const detail = RootSecurity.error_message(error)
                        this.render_upload(
                            filename,
                            'retrying',
                            `Attempt ${attempt} of ${total} after ${delay} ms — ${detail}`,
                        )
                        this.set_message(
                            `Upload interrupted for ${filename}; retrying attempt ${attempt} of ${total}...`
                        )
                    },
                })
                if(this.upload_cancel_requested)
                    break
                uploaded += 1
                this.set_progress(uploaded, filenames.length)
                this.render_upload(
                    filename,
                    'ready',
                    upload.skipped ? 'Already uploaded in this session.' : `Uploaded in ${upload.attempts} attempt(s).`,
                )
                this.set_message(`Prepared ${uploaded} of ${filenames.length} images.`)
            }

            if(this.upload_cancel_requested){
                this.show_upload_cancelled(current_filename)
                return
            }

            current_filename = undefined
            this.phase = 'starting'
            const file_pairs = RootTracking.get_file_pairs()
            this.set_message(
                file_pairs.length
                    ? `All images are ready. Starting detection and ${file_pairs.length} tracking pair(s)...`
                    : 'All images are ready. Starting detection only; no valid tracking pairs were found.'
            )
            const response = await this.request('/api/pipeline/runs', 'POST', {
                filenames: filenames,
                file_pairs: file_pairs,
            })
            this.active_run_id = response.id
            this.phase = 'analysis'
            await this.poll_until_finished()
        } catch(error) {
            console.error('Pipeline start failed.', error)
            if(this.upload_cancel_requested)
                this.show_upload_cancelled(current_filename)
            else {
                const stage = this.phase == 'upload' ? 'Upload' : 'Analysis startup'
                const item = current_filename ? ` for ${current_filename}` : ''
                const message = `${stage} failed${item}: ${this.error_message(error)}`
                if(current_filename)
                    this.render_upload(current_filename, 'failed', this.error_message(error))
                this.show_error(message)
            }
            this.set_running(false)
        } finally {
            this.current_upload_request = undefined
        }
    }

    static async poll_until_finished(){
        let interrupted_requests = 0
        while(this.active_run_id){
            let run
            try {
                run = await this.request(`/api/pipeline/runs/${this.active_run_id}`, 'GET')
                interrupted_requests = 0
            } catch(error) {
                interrupted_requests += 1
                if(interrupted_requests > 5 || !RootsFileInput.is_retryable_upload_error(error))
                    throw error
                this.set_message(
                    `Connection interrupted; reconnecting to the active analysis `
                    + `(attempt ${interrupted_requests} of 5)...`
                )
                await sleep(1000 * interrupted_requests)
                continue
            }
            this.render(run)
            if(this.terminal_states.includes(run.state)){
                await this.apply_results(run)
                this.set_running(false)
                this.phase = 'idle'
                return run
            }
            await sleep(300)
        }
    }

    static async on_cancel(event){
        event?.preventDefault()
        event?.stopPropagation()
        if(!this.active_run_id && this.phase == 'upload'){
            this.upload_cancel_requested = true
            this.current_upload_request?.abort()
            this.set_message('Stopping upload. Files already prepared will be reused on retry...')
            $('#pipeline-cancel-button')
                .prop('disabled', true)
                .attr('aria-disabled', 'true')
                .addClass('disabled loading')
                .text('Stopping...')
            return false
        }
        if(!this.active_run_id)
            return false
        const $button = $('#pipeline-cancel-button')
            .prop('disabled', true)
            .attr('aria-disabled', 'true')
            .addClass('disabled loading')
            .text('Cancelling...')
        this.set_message('Cancelling analysis. Waiting for the active operation to stop safely...')
        $('#pipeline-status-modal').modal({closable:false})
        try {
            await this.request(`/api/pipeline/runs/${this.active_run_id}/cancel`, 'POST')
        } catch(error) {
            this.show_error(this.error_message(error))
            $button
                .prop('disabled', false)
                .attr('aria-disabled', 'false')
                .removeClass('disabled loading')
                .text('Cancel')
        }
        return false
    }

    static async on_retry_failed(){
        if(!this.active_run_id)
            return
        this.set_running(true)
        $('#pipeline-retry-button').addClass('disabled')
        try {
            await this.request(`/api/pipeline/runs/${this.active_run_id}/retry`, 'POST')
            await this.poll_until_finished()
        } catch(error) {
            this.show_error(this.error_message(error))
            this.set_running(false)
        }
    }

    static async apply_results(run){
        for(const [filename, item] of Object.entries(run.images)){
            if(item.state == 'completed' && item.result)
                await App.Detection.set_results(filename, item.result)
            else if(['failed', 'cancelled'].includes(item.state))
                App.Detection.set_failed(filename)
        }
        for(const item of run.pairs)
            RootTracking.apply_pipeline_result(item)
    }

    static render(run){
        const active_fraction = run.current?.progress ?? 0
        this.set_progress(run.progress.finished + active_fraction, run.progress.total)
        const current = run.current
        if(run.state == 'cancelling')
            this.set_message('Cancelling analysis. Waiting for the active operation to stop safely...')
        else if(current){
            const detail = current.description ? ` — ${current.description}` : ''
            this.set_message(`${this.pretty_state(current.stage)}: ${current.item_id}${detail}`)
        }
        else
            this.set_message(this.run_message(run))

        const $body = $('#pipeline-status-table tbody').empty()
        const items = Object.values(run.images).concat(run.pairs)
        for(const item of items){
            const label = item.filename ?? `${item.filename0} → ${item.filename1}`
            const diagnostic = item.error?.diagnostic_id
            const message = item.error?.message
                ? `${item.error.message}${diagnostic ? ` [${diagnostic}]` : ''}`
                : ''
            const $row = $('<tr>')
            $('<td>').text(label).appendTo($row)
            $('<td>').text(item.stage).appendTo($row)
            $('<td>').text(this.pretty_state(item.state)).appendTo($row)
            $('<td>').text(message).appendTo($row)
            $body.append($row)
        }

        const terminal = this.terminal_states.includes(run.state)
        $('#pipeline-cancel-button')
            .toggle(!terminal)
            .prop('disabled', run.state == 'cancelling')
            .attr('aria-disabled', String(run.state == 'cancelling'))
            .toggleClass('disabled loading', run.state == 'cancelling')
            .text(run.state == 'cancelling' ? 'Cancelling...' : 'Cancel')
        $('#pipeline-close-button').toggle(terminal)
        const retryable = terminal && items.some(
            item => ['failed', 'skipped', 'cancelled'].includes(item.state)
        )
        $('#pipeline-retry-button').toggle(retryable).toggleClass('disabled', !retryable)
        $('#pipeline-status-modal').modal({closable: terminal})
    }

    static run_message(run){
        const messages = {
            completed: 'Analysis completed successfully. Results are ready for review and export.',
            completed_with_errors: 'Analysis completed with failures or items requiring review.',
            cancelled: 'Analysis was cancelled. Completed results remain available.',
            failed: 'The pipeline could not complete.',
        }
        return messages[run.state] ?? this.pretty_state(run.state)
    }

    static show_modal(){
        this.active_run_id = undefined
        this.phase = 'idle'
        this.upload_cancel_requested = false
        this.current_upload_request = undefined
        this.upload_rows = new Map()
        $('#pipeline-status-table tbody').empty()
        $('#pipeline-error-message').hide().text('')
        $('#pipeline-cancel-button').show()
            .prop('disabled', false)
            .attr('aria-disabled', 'false')
            .removeClass('disabled loading')
            .text('Cancel')
        $('#pipeline-retry-button, #pipeline-close-button').hide()
        $('#pipeline-status-modal').modal({closable:false, duration:0}).modal('show')
    }

    static show_error(message){
        $('#pipeline-error-message').text(message).show()
        this.set_message('Analysis could not continue.')
        $('#pipeline-cancel-button').hide()
        $('#pipeline-close-button').show()
        $('#pipeline-status-modal').modal({closable:true})
        this.phase = 'idle'
    }

    static show_upload_cancelled(filename){
        if(filename)
            this.render_upload(filename, 'cancelled', 'Upload stopped by the user.')
        $('#pipeline-error-message').hide().text('')
        this.set_message('Upload stopped. Prepared files will be reused if you run analysis again.')
        $('#pipeline-cancel-button').hide()
        $('#pipeline-close-button').show()
        $('#pipeline-status-modal').modal({closable:true})
        this.phase = 'idle'
        this.set_running(false)
    }

    static render_upload(filename, state, details=''){
        let $row = this.upload_rows.get(filename)
        if(!$row){
            $row = $('<tr>')
            $('<td>').text(filename).appendTo($row)
            $('<td>').text('Upload').appendTo($row)
            $('<td>').appendTo($row)
            $('<td>').appendTo($row)
            $('#pipeline-status-table tbody').append($row)
            this.upload_rows.set(filename, $row)
        }
        $row.children().eq(2).text(this.pretty_state(state))
        $row.children().eq(3).text(details)
    }

    static set_message(message){
        $('#pipeline-current-message').text(message)
    }

    static set_progress(value, total){
        const safe_total = Math.max(total, 1)
        $('#pipeline-progress').progress({
            total: safe_total,
            value: Math.min(value, safe_total),
            showActivity: value < total,
        })
    }

    static set_running(running){
        const run_disabled = running || Object.keys(GLOBAL.files).length == 0
        $('#pipeline-run-button')
            .toggleClass('disabled loading', run_disabled)
            .prop('disabled', run_disabled)
            .attr('aria-disabled', String(run_disabled))
        $('#settings-button, #load-input-images-button, #load-input-folder-button, #load-annotations-button, #load-exclude-masks-button, .process-all')
            .toggleClass('disabled', running)
            .prop('disabled', running)
        $('#input_images, #input_folder, #input_masks').prop('disabled', running)
    }

    static pretty_state(value){
        if(!value)
            return ''
        return value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
    }

    static error_message(error){
        return RootSecurity.error_message(error, 'RootDetector returned an unreadable error.')
    }

    static request(url, method, data=undefined){
        return RootSecurity.request(url, method, data)
    }
}
