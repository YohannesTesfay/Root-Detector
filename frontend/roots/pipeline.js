RootPipeline = class {
    static active_run_id = undefined
    static terminal_states = ['completed', 'completed_with_errors', 'cancelled', 'failed']

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
        this.set_message('Uploading input images...')
        this.set_progress(0, filenames.length)

        try {
            let uploaded = 0
            for(const filename of filenames){
                await upload_file_to_flask(GLOBAL.files[filename])
                uploaded += 1
                this.set_progress(uploaded, filenames.length)
                this.set_message(`Uploaded ${uploaded} of ${filenames.length} images.`)
            }

            const response = await this.request('/api/pipeline/runs', 'POST', {
                filenames: filenames,
                file_pairs: RootTracking.get_file_pairs(),
            })
            this.active_run_id = response.id
            await this.poll_until_finished()
        } catch(error) {
            console.error('Pipeline start failed.', error)
            this.show_error(this.error_message(error))
            this.set_running(false)
        }
    }

    static async poll_until_finished(){
        while(this.active_run_id){
            const run = await this.request(`/api/pipeline/runs/${this.active_run_id}`, 'GET')
            this.render(run)
            if(this.terminal_states.includes(run.state)){
                await this.apply_results(run)
                this.set_running(false)
                return run
            }
            await sleep(300)
        }
    }

    static async on_cancel(){
        if(!this.active_run_id)
            return
        try {
            await this.request(`/api/pipeline/runs/${this.active_run_id}/cancel`, 'POST')
            this.set_message('Cancellation requested. The current model operation will finish first.')
        } catch(error) {
            this.show_error(this.error_message(error))
        }
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
        this.set_progress(run.progress.finished, run.progress.total)
        const current = run.current
        if(current)
            this.set_message(`${this.pretty_state(current.stage)}: ${current.item_id}`)
        else
            this.set_message(this.run_message(run))

        const $body = $('#pipeline-status-table tbody').empty()
        const items = Object.values(run.images).concat(run.pairs)
        for(const item of items){
            const label = item.filename ?? `${item.filename0} → ${item.filename1}`
            const message = item.error?.message ?? ''
            const $row = $('<tr>')
            $('<td>').text(label).appendTo($row)
            $('<td>').text(item.stage).appendTo($row)
            $('<td>').text(this.pretty_state(item.state)).appendTo($row)
            $('<td>').text(message).appendTo($row)
            $body.append($row)
        }

        const terminal = this.terminal_states.includes(run.state)
        $('#pipeline-cancel-button').toggle(!terminal)
        $('#pipeline-close-button').toggle(terminal)
        const retryable = terminal && items.some(item => ['failed', 'skipped'].includes(item.state))
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
        $('#pipeline-status-table tbody').empty()
        $('#pipeline-error-message').hide().text('')
        $('#pipeline-cancel-button').show()
        $('#pipeline-retry-button, #pipeline-close-button').hide()
        $('#pipeline-status-modal').modal({closable:false, duration:0}).modal('show')
    }

    static show_error(message){
        $('#pipeline-error-message').text(message).show()
        this.set_message('Analysis could not continue.')
        $('#pipeline-cancel-button').hide()
        $('#pipeline-close-button').show()
        $('#pipeline-status-modal').modal({closable:true})
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
        return error?.responseJSON?.message ?? error?.message ?? String(error)
    }

    static request(url, method, data=undefined){
        return $.ajax({
            url: url,
            method: method,
            contentType: data == undefined ? undefined : 'application/json',
            data: data == undefined ? undefined : JSON.stringify(data),
        })
    }
}
