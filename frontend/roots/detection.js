


RootDetection = class extends BaseDetection{
    static async on_process_image(event){
        const filename = $(event.target).closest('[filename]').attr('filename')
        return await this.process_image(filename)
    }

    static async on_process_all(event){
        const filenames = Object.keys(GLOBAL.files)
        const $button = $(event.currentTarget || event.target)
        const $progress = $button.siblings('.processing')
        const $summary = $button.siblings('.detection-batch-summary')
        $button.hide()
        $summary.hide().text('')
        $button.siblings('.cancel-processing, .processing').show().removeClass('disabled')
        GLOBAL.cancel_requested = false
        const failed = []
        let attempted = 0
        let completed = 0
        const progress_text = () => `${completed} of ${filenames.length} attempted (${filenames.length ? Math.round(100 * completed / filenames.length) : 100}%)`
        $progress.find('.processing-progress-text').text(`Processing ${progress_text()}`)
        for(const filename of filenames){
            if(GLOBAL.cancel_requested)
                break
            attempted += 1
            try {
                await this.process_image(filename, true, {is_cancelled: () => GLOBAL.cancel_requested})
            } catch(error) {
                failed.push({filename: filename, error: error})
                $('body').toast({
                    key: 'detection-batch-failures',
                    message: `${failed.length} image(s) failed so far. Processing continues.`,
                    details: failed.map(({filename, error}) =>
                        `${filename}: ${RootSecurity.error_message(error)}`),
                    class: 'error', displayTime: 0,
                })
            }
            completed += 1
            $progress.find('.processing-progress-text').text(`Processing ${progress_text()}`)
        }
        if(failed.length)
            $('body').toast({
                key: 'detection-batch-failures',
                message: `${failed.length} of ${attempted} processed image(s) failed${GLOBAL.cancel_requested ? ' before cancellation.' : '. The batch continued past those failures.'}`,
                details: failed.map(({filename, error}) =>
                    `${filename}: ${RootSecurity.error_message(error)}`),
                class: 'error', displayTime: 0, closeIcon: true,
            })
        $button.show()
        $button.siblings('.cancel-processing, .processing').hide()
        $summary.text(`${GLOBAL.cancel_requested ? 'Stopped' : 'Finished'}: ${progress_text()}${failed.length ? `; ${failed.length} failed` : ''}`).show()
        return {failed: failed, cancelled: GLOBAL.cancel_requested}
    }

    static async process_image(filename, upload_image=true, options={}){
        await this.set_results(filename, undefined)
        this.set_processing(filename)

        function on_message(event){
            const data = JSON.parse(event.originalEvent.data)
            if(data.image == filename)
                console.log(event)
        }
        $(GLOBAL.event_source).on('message', on_message)

        try {
            if(upload_image)
                await RootsFileInput.ensure_uploaded(GLOBAL.files[filename])
            let results
            for(let attempt = 1; attempt <= 3; attempt += 1){
                try {
                    results = await RootSecurity.request(
                        `/process_image/${encodeURIComponent(filename)}`,
                        'POST',
                    )
                    break
                } catch(error) {
                    if(attempt == 3 || !RootSecurity.is_transient_request_error(error)
                            || options.is_cancelled?.())
                        throw error
                    console.warn(`Transient detection request failure for ${filename}; retrying (${attempt + 1}/3).`, error)
                    await sleep(500 * attempt)
                }
            }
            await this.set_results(filename, results)
            return results
        } catch(error) {
            console.error(`Processing failed for ${filename}.`, error)
            this.set_failed(filename)
            const report = await RootSecurity.report_client_error(
                'manual_detection',
                filename,
                error,
            )
            const diagnostic = report?.diagnostic_id ? ` [${report.diagnostic_id}]` : ''
            throw new Error(`${RootSecurity.error_message(error)}${diagnostic}`)
        } finally {
            $(GLOBAL.event_source).off('message', on_message)
        }
    }

    // Keep server result names as URLs. Eagerly fetching both PNGs for every
    // image retains gigabytes of browser Blobs in large batches and can turn a
    // successful backend detection into a misleading processing failure.
    static async set_results(filename, results){
        RootsTraining.forget_imported_label(filename)
        var clear = (results==undefined)
        this.hide_dimmer(filename)
        var $root = $(`#filetable [filename="${filename}"]`)
        $root.find('.show-results-checkbox')
            .checkbox({onChange: () => GLOBAL.App.ViewControls.toggle_results(filename)})
            .checkbox('check')
        if(clear)
            GLOBAL.App.ImageLoading.set_image_src($root.find('img.overlay'), undefined)
        GLOBAL.files[filename].set_results(results)
        GLOBAL.App.Boxes.refresh_boxes(filename)
        this.set_processed(filename, clear)
        $(`[filename="${filename}"] .skeletonized-checkbox`)
            .toggleClass('disabled', clear)
            .checkbox({onChange: this.on_toggle_skeleton})
        if($(`#filetable tr.ui.title[filename="${filename}"]`).hasClass('active'))
            this.show_result_preview(filename)
    }

    static show_result_preview(filename){
        const result = GLOBAL.files[filename]?.results
        if(!result)
            return
        const $root = $(`#filetable [filename="${filename}"]`)
        const skeleton = $root.find('.skeletonized-checkbox').checkbox('is checked')
        const source = skeleton ? result.skeleton : result.segmentation
        GLOBAL.App.ImageLoading.set_image_src($root.find('img.overlay'), source)
    }

    static on_toggle_skeleton(){
        var $root    = $(this).closest('[filename]')
        var filename = $root.attr('filename')
        var checked  = $(this).closest('.checkbox').checkbox('is checked')
        var src      = checked? GLOBAL.files[filename].results.skeleton : GLOBAL.files[filename].results.segmentation;

        //var $result_image   = $root.find('img.result-image')
        //GLOBAL.App.ImageLoading.set_image_src($result_image, src)
        var $result_overlay = $root.find(`img.overlay`)
        GLOBAL.App.ImageLoading.set_image_src($result_overlay, src)
    }
}
