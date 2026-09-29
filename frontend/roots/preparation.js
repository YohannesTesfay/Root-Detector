// Optional, bounded preparation. The thumbnail is never used as analysis input.
RootPreparation = class {
    static sources = []
    static prepared = []
    static index = 0
    static stage = undefined
    static bounds_template = undefined
    static busy = false
    static max_prepared_batch_bytes = 256 * 1024 * 1024

    static show_error(error){
        $('#preparation-error')
            .text(RootSecurity.error_message(error, 'Image preparation failed.'))
            .show()
    }

    static set_busy(busy){
        this.busy = busy
        $('#preparation-dialog .actions button').prop('disabled', busy)
        if(!busy && this.stage)
            this.update_bounds()
    }

    static show_selection_error(message){
        $('body').toast({message: message, class: 'error', displayTime: 0, closeIcon: true})
    }

    static async on_files_select(event){
        const files = Array.from(event.target.files ?? [])
        event.target.value = ''
        if(!files.length)
            return
        if(this.busy || this.stage || this.sources.length){
            this.show_selection_error('Finish or close the current image preparation first.')
            return
        }
        if(files.length > 20){
            this.show_selection_error('Prepare at most 20 images in one batch.')
            return
        }
        const max_bytes = Number(RootSecurity.limits?.preparation_source_bytes ?? 64 * 1024 * 1024)
        const oversize = files.find(file => file.size > max_bytes)
        if(oversize){
            const mib = Math.floor(max_bytes / (1024 * 1024))
            this.show_selection_error(`${oversize.name} exceeds the ${mib} MiB preparation limit. Prepare it externally.`)
            return
        }
        this.sources = files
        this.prepared = []
        this.index = 0
        this.bounds_template = undefined
        $('#preparation-error').hide()
        $('#preparation-download, #preparation-import').hide()
        $('#preparation-dialog').modal({closable: false}).modal('show')
        await this.inspect_current()
    }

    static async inspect_current(){
        const file = this.sources[this.index]
        if(!file)
            return
        this.set_busy(true)
        $('#preparation-source-info').text(`Inspecting ${this.index + 1} of ${this.sources.length}: ${file.name}...`)
        $('#preparation-preview-wrap').hide()
        $('#preparation-preview').removeAttr('src')
        $('#preparation-fields, #preparation-apply').hide()
        $('#preparation-error').hide()
        try {
            const inspected = await upload_file_to_flask(file, '/api/preparation/inspect')
            this.stage = inspected
            $('#preparation-source-info').text(
                `${this.index + 1} of ${this.sources.length}: ${file.name} — `
                + `${inspected.source_width} × ${inspected.source_height} original pixels; `
                + `${(inspected.source_bytes / (1024 * 1024)).toFixed(1)} MiB encoded.`
            )
            $('#preparation-preview')
                .attr('src', `/images/${encodeURIComponent(inspected.preview)}`)
            $('#preparation-preview-wrap').css('display', 'inline-block')
            const bounds = this.bounds_template ?? {
                left: 0, top: 0,
                width: inspected.source_width, height: inspected.source_height,
            }
            this.set_bounds(bounds)
            $('#preparation-fields, #preparation-apply').show()
            this.update_bounds()
        } catch(error) {
            this.show_error(error)
        } finally {
            this.set_busy(false)
        }
    }

    static current_bounds(){
        return {
            left: Number($('#crop-left').val()),
            top: Number($('#crop-top').val()),
            width: Number($('#crop-width').val()),
            height: Number($('#crop-height').val()),
        }
    }

    static set_bounds(bounds){
        for(const key of ['left', 'top', 'width', 'height'])
            $(`#crop-${key}`).val(bounds[key])
    }

    static reset_bounds(){
        if(!this.stage)
            return
        this.set_bounds({
            left: 0, top: 0,
            width: this.stage.source_width,
            height: this.stage.source_height,
        })
        this.update_bounds()
    }

    static update_bounds(){
        if(!this.stage)
            return false
        const {left, top, width, height} = this.current_bounds()
        const complete = ['left', 'top', 'width', 'height']
            .every(key => String($(`#crop-${key}`).val()).trim() !== '')
        const valid = complete && [left, top, width, height].every(Number.isSafeInteger)
            && left >= 0 && top >= 0 && width > 0 && height > 0
            && left + width <= this.stage.source_width
            && top + height <= this.stage.source_height
            && Math.min(width, height) >= Number(RootSecurity.limits?.preparation_min_analysis_dimension ?? 1280)
            && width * height <= Number(RootSecurity.limits?.preparation_source_pixels ?? 16000000)
            && Math.max(width, height) <= 32768
        $('#preparation-apply').prop('disabled', !valid || this.busy)
        $('#preparation-selection').toggle(valid)
        if(valid){
            $('#preparation-selection').css({
                left: `${100 * left / this.stage.source_width}%`,
                top: `${100 * top / this.stage.source_height}%`,
                width: `${100 * width / this.stage.source_width}%`,
                height: `${100 * height / this.stage.source_height}%`,
            })
        }
        $('#preparation-summary').text(valid
            ? `New copy: ${width} × ${height} pixels (${(width * height / 1000000).toFixed(2)} MP). `
                + 'No resampling is applied; verify the same physical region on every date.'
            : 'Enter whole-pixel crop bounds inside the original image. The released model needs at least 1280 × 1280 pixels; the selected region must also fit the preparation limits.'
        )
        return valid
    }

    static async apply_current(){
        if(this.busy || !this.stage || !this.update_bounds())
            return
        const bounds = this.current_bounds()
        this.set_busy(true)
        try {
            const result = await RootSecurity.request('/api/preparation/apply', 'POST', {
                id: this.stage.id,
                rectangle: bounds,
            })
            const blob = await fetch_as_blob(`/images/${encodeURIComponent(result.output)}`)
            const current_bytes = this.prepared.reduce((total, file) => total + file.size, 0)
            if(current_bytes + blob.size > this.max_prepared_batch_bytes)
                throw new Error(
                    'Prepared copies would exceed the 256 MiB browser batch budget. '
                    + 'Download or import the completed copies, then prepare the remaining images in a new batch.'
                )
            const file = new File([blob], result.manifest.output_name, {type: 'image/png'})
            if(this.prepared.some(previous => previous.name == file.name))
                throw new Error(`Two prepared copies would be named ${file.name}. Use distinct source names or regions.`)
            file.preparation = result.manifest
            this.prepared.push(file)
            $('#preparation-download, #preparation-import').show()
            this.bounds_template = $('#crop-reuse-bounds').is(':checked') ? bounds : undefined
            await RootSecurity.request(`/api/preparation/${encodeURIComponent(this.stage.id)}/discard`, 'POST')
            this.stage = undefined
            this.index += 1
            if(this.index < this.sources.length){
                await this.inspect_current()
            } else {
                $('#preparation-preview-wrap, #preparation-fields, #preparation-apply').hide()
                $('#preparation-source-info').text(`${this.prepared.length} prepared copy/copies are ready.`)
                $('#preparation-summary').text(
                    'Download the prepared copies and manifest to retain them, then import them for analysis. '
                    + 'The original files have not been changed.'
                )
                $('#preparation-download, #preparation-import').show()
            }
        } catch(error) {
            this.show_error(error)
        } finally {
            this.set_busy(false)
        }
    }

    static download_prepared(){
        if(!this.prepared.length)
            return
        const zipdata = {
            'preparation-manifest.json': JSON.stringify({
                schema: 1,
                preparations: this.prepared.map(file => file.preparation),
            }, null, 2),
        }
        for(const file of this.prepared)
            zipdata[file.name] = file
        download_zip('RootDetector-prepared-images.zip', zipdata)
    }

    static async import_prepared(){
        if(!this.prepared.length || this.busy)
            return
        if(this.index < this.sources.length && !window.confirm(
            `Only ${this.prepared.length} of ${this.sources.length} images are prepared. Import these and skip the rest?`
        ))
            return
        if(Object.keys(GLOBAL.files).length && !window.confirm(
            'Importing prepared copies replaces the current image set and clears its temporary results. Download existing results first. Continue?'
        ))
            return
        this.set_busy(true)
        try {
            if(this.stage){
                await RootSecurity.request(`/api/preparation/${encodeURIComponent(this.stage.id)}/discard`, 'POST')
                this.stage = undefined
            }
            // The shared file importer opens its own progress modal. Wait for
            // this dialog to close first so Fomantic does not leave that modal
            // active behind the preparation dialog.
            await new Promise(resolve => {
                $('#preparation-dialog')
                    .modal('setting', 'onHidden', resolve)
                    .modal('hide')
            })
            await RootsFileInput.set_input_files(this.prepared)
            this.sources = []
            this.prepared = []
            this.bounds_template = undefined
        } catch(error) {
            $('#preparation-dialog').modal('show')
            this.show_error(error)
        } finally {
            this.set_busy(false)
        }
    }

    static async cancel(){
        if(this.busy)
            return
        if(this.prepared.length && !window.confirm('Discard prepared copies that have not been downloaded or imported?'))
            return
        if(this.stage){
            try {
                await RootSecurity.request(`/api/preparation/${encodeURIComponent(this.stage.id)}/discard`, 'POST')
            } catch(error) {
                this.show_error(error)
                return
            }
        }
        this.stage = undefined
        this.sources = []
        this.prepared = []
        this.bounds_template = undefined
        $('#preparation-dialog').modal('hide')
    }
}
