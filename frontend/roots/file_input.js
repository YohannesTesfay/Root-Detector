

RootsFileInput = class extends BaseFileInput{
    static uploaded_files = new Map()

    static show_file_error(error){
        console.error(error)
        $('body').toast({
            message: RootSecurity.error_message(error, 'The selected files could not be loaded.'),
            class: 'error', displayTime: 0, closeIcon: true,
        })
    }

    static file_identity(file){
        return [file.name, file.size, file.lastModified ?? 0, file.type ?? ''].join('\u0000')
    }

    static reset_uploaded_files(){
        this.uploaded_files = new Map()
    }

    static is_retryable_upload_error(error){
        const status = Number(error?.status ?? 0)
        return status == 0 || [408, 425, 429].includes(status) || status >= 500
    }

    static async ensure_uploaded(file, options={}){
        const identity = this.file_identity(file)
        if(this.uploaded_files.get(file.name) == identity)
            return {skipped: true, attempts: 0}

        const max_attempts = Math.max(1, Number(options.max_attempts ?? 3))
        for(let attempt = 1; attempt <= max_attempts; attempt += 1){
            try {
                const request = RootSecurity.upload_file(file)
                if(options.on_request)
                    options.on_request(request)
                const response = await request
                this.uploaded_files.set(file.name, identity)
                return {response: response, skipped: false, attempts: attempt}
            } catch(error) {
                const will_retry = (
                    attempt < max_attempts
                    && this.is_retryable_upload_error(error)
                    && !options.is_cancelled?.()
                )
                if(!will_retry)
                    throw error
                const delay = 500 * attempt
                options.on_retry?.(attempt + 1, max_attempts, delay, error)
                await sleep(delay)
            } finally {
                options.on_request?.(undefined)
            }
        }
    }

    static async on_inputfiles_select(event){
        try {
            await this.load_list_of_files(event.target.files)
        } catch(error) {
            this.show_file_error(error)
        } finally {
            event.target.value = ''
        }
    }

    static async on_inputfolder_select(event){
        try {
            const files = Array.from(event.target.files)
            if(files.some(file => file.name == 'preparation-manifest.json'))
                await this.restore_prepared_files(files.filter(file => this.is_supported_image(file) || file.name == 'preparation-manifest.json'))
            else
                await this.set_input_files(files.filter(file => this.is_supported_image(file)))
        } catch(error) {
            this.show_file_error(error)
        } finally {
            event.target.value = ''
        }
    }

    static async on_annotations_select(event){
        try {
            await this.load_result_files(event.target.files)
        } catch(error) {
            this.show_file_error(error)
        } finally {
            event.target.value = ''
        }
    }

    static async on_preparedfiles_select(event){
        try {
            await this.restore_prepared_files(Array.from(event.target.files))
        } catch(error) {
            this.show_file_error(error)
        } finally {
            event.target.value = ''
        }
    }

    static async set_input_files(files){
        files = Array.from(files)
        const filenames = files.map(file => file.name)
        const duplicates = filenames.filter((name, index) => filenames.indexOf(name) != index)
        if(duplicates.length)
            throw new Error(`Duplicate filenames are not supported: ${[...new Set(duplicates)].join(', ')}`)

        if(!window.location.href.startsWith('file://'))
            await RootSecurity.request('/clear_cache', 'POST')

        this.reset_uploaded_files()
        RootsTraining.clear_imported_labels()
        GLOBAL.files = []
        for(const file of files){
            const input = new InputFile(file)
            if(file.preparation)
                input.preparation = file.preparation
            GLOBAL.files[file.name] = input
        }
        $('.tabs .item[data-tab="detection"]').click()
        const result = await this.refresh_filetable(files)
        RootPipeline.on_files_ready()
        return result
    }

    static async on_drop(event){
        event.preventDefault()
        try {
            await this.load_list_of_files(event.dataTransfer.files)
        } catch(error) {
            this.show_file_error(error)
        }
    }

    static is_supported_image(file){
        const extension = file.name.toLowerCase().split('.').pop()
        return file.type.startsWith('image/') || ['jpg', 'jpeg', 'png', 'tif', 'tiff'].includes(extension)
    }

    static async load_list_of_files(files){
        files = Array.from(files)
        if(files.some(file => file.name == 'preparation-manifest.json' || /^RootDetector-prepared-images(?: \(\d+\))?\.zip$/i.test(file.name))){
            await this.restore_prepared_files(files)
            return
        }
        const result_suffixes = ['.segmentation.png', '.skeleton.png', '.exclusionmask.png']
        const is_result_image = file => result_suffixes.some(
            suffix => file.name.toLowerCase().endsWith(suffix)
        )
        const inputfiles = files.filter(
            file => this.is_supported_image(file) && !is_result_image(file)
        )
        if(inputfiles.length)
            await this.set_input_files(inputfiles)

        const remaining_files = files.filter(file => !inputfiles.includes(file))
        await this.load_result_files(remaining_files)
    }

    static async restore_prepared_files(files){
        if(files.reduce((total, file) => total + file.size, 0) > 256 * 1024 * 1024)
            throw new Error('Prepared import exceeds the 256 MiB batch budget. Import a smaller set.')
        const form = new FormData()
        for(const file of files)
            form.append('files', file, file.name)
        const response = await $.ajax({
            url: '/api/preparation/import', method: 'POST', data: form,
            processData: false, contentType: false,
        })
        const restored = []
        for(const result of response.files){
            const blob = await fetch_as_blob(`/images/${encodeURIComponent(result.output)}`)
            const file = new File([blob], result.manifest.output_name, {type: 'image/png'})
            file.preparation = result.manifest
            restored.push(file)
        }
        // Fetch all validated copies before set_input_files clears the old cache.
        await this.set_input_files(restored)
    }

    static async load_result_files(files){
        const result_files = await this.collect_result_files(files)
        if(Object.keys(result_files).length == 0)
            return

        const $modal = $('#loading-files-modal')
        $modal.modal({closable: false, inverted: true, duration: 0}).modal('show')
        $modal.find('.progress').progress({
            total: Object.keys(result_files).length,
            value: 0,
            showActivity: false,
        })
        try {
            for(const [filename, results] of Object.entries(result_files)){
                const unzipped_results = await Promise.all(results.map(maybe_unzip))
                await this.load_result(filename, unzipped_results)
                $modal.find('.progress').progress('increment')
            }
        } finally {
            $modal.modal({closable: true}).modal('hide')
            await sleep(500)
            $modal.find('.progress').progress('reset')
        }
    }

    static async collect_results_from_zipfile(file){
        const configured = Number(RootSecurity.limits?.max_upload_bytes)
        const limit = Number.isFinite(configured) && configured > 0 ? configured : 256 * 1024 * 1024
        const label = Math.floor(limit / (1024 * 1024))
        if(file.size > limit)
            throw new Error(`Result ZIP exceeds the configured ${label} MiB import limit.`)
        const archive = await JSZip.loadAsync(file)
        const entries = Object.values(archive.files).filter(entry => !entry.dir)
        if(entries.length > 1000)
            throw new Error('Result ZIP contains too many files. Import a smaller batch.')
        let expanded = 0
        for(const entry of entries){
            const bytes = entry._data?.uncompressedSize
            if(entry.name?.toLowerCase().endsWith('.zip'))
                throw new Error('Nested ZIP archives are not supported. Import the result ZIP directly.')
            if(!Number.isSafeInteger(bytes) || bytes < 0 || bytes > limit)
                throw new Error(`Result ZIP contains an invalid entry or exceeds the configured ${label} MiB limit.`)
            expanded += bytes
            if(expanded > limit)
                throw new Error(`Expanded result ZIP exceeds the configured ${label} MiB import limit.`)
        }
        const sidecar = archive.files['preparation-manifest.json']
        if(sidecar && !sidecar.dir){
            if(sidecar._data.uncompressedSize > 1024 * 1024)
                throw new Error('Preparation manifest exceeds 1 MiB.')
            const document = JSON.parse(await sidecar.async('string'))
            if(document?.schema != 1 || !Array.isArray(document.preparations) || document.preparations.length > 20)
                throw new Error('Invalid preparation manifest in results ZIP.')
            let companions = []
            const companionSidecar = archive.files['preparation-companions.json']
            if(companionSidecar && !companionSidecar.dir){
                if(companionSidecar._data.uncompressedSize > 1024 * 1024)
                    throw new Error('Prepared mask manifest exceeds 1 MiB.')
                const companionDocument = JSON.parse(await companionSidecar.async('string'))
                if(companionDocument?.schema != 1 || !Array.isArray(companionDocument.companions) || companionDocument.companions.length > 40)
                    throw new Error('Invalid prepared mask manifest in results ZIP.')
                companions = companionDocument.companions
                const outputs = new Set()
                const kinds = new Set()
                for(const record of companions){
                    const name = record?.output_name
                    const identity = `${record?.preparation_id}:${record?.kind}`
                    if(typeof name != 'string' || !/^[A-Za-z0-9_-]+\.png$/.test(name) || outputs.has(name.toLowerCase()) || kinds.has(identity))
                        throw new Error('Invalid or duplicate prepared mask in results ZIP.')
                    outputs.add(name.toLowerCase())
                    kinds.add(identity)
                }
            }
            const validated = []
            const names = new Set()
            for(const record of document.preparations){
                if(names.has(record?.output_name))
                    throw new Error('Duplicate preparation record in results ZIP.')
                names.add(record?.output_name)
                const input = GLOBAL.files[record?.output_name]
                if(!input)
                    continue
                await this.ensure_uploaded(input)
                const matchingCompanions = companions.filter(companion => companion.preparation_id == record.preparation_id)
                for(const companion of matchingCompanions){
                    const entry = archive.files[`preparation-companions/${companion.output_name}`]
                    if(!entry || entry.dir)
                        throw new Error('A prepared mask recorded in the result ZIP is missing.')
                    await this.ensure_uploaded(new File([await entry.async('blob')], companion.output_name, {type: 'image/png'}))
                }
                const result = await RootSecurity.request('/api/preparation/validate', 'POST', {
                    filename: input.name, manifest: record, companions: matchingCompanions,
                    restore_exclusion_masks: true,
                })
                validated.push([input, result.manifest, result.companions ?? []])
            }
            for(const [input, record, records] of validated){
                input.preparation = record
                input.prepared_companions = records
                if(records.some(companion => companion.kind == 'exclusion_mask'))
                    await App.Detection.set_results(input.name, undefined)
            }
            if(validated.some(([_input, _record, records]) => records.some(companion => companion.kind == 'exclusion_mask')))
                await RootTracking.set_input_files(Object.values(GLOBAL.files))
        }
        return await this.collect_result_files(archive.files)
    }

    //override
    static async refresh_filetable(files){
        const $table = $('#filetable')
        const $body = $table.find('tbody').empty()
        const $modal = $('#loading-files-modal')
        $modal.modal({closable: false, inverted: true, duration: 0}).modal('show')
        $modal.find('.progress').progress({total: files.length, value: 0, showActivity: false})
        try {
            $table.find('#files-loaded-column-header').text('0 Files Loaded')
            for(let index = 0; index < files.length; index += 1){
                const $row = $('template#filetable-row-template').tmpl([{filename: files[index].name}])
                $row.appendTo($body)
                $row.first().attr('top', $row.offset().top)
                $table.find('#files-loaded-column-header').text(`${index + 1} File${index == 0 ? '' : 's'} Loaded`)
                $modal.find('.progress').progress('set progress', index + 1)
                await sleep(0)
            }
            const scripts = [...new Set($body.find('after-insert-script').get().map(element => element.innerHTML.trim()))]
            for(const script of scripts)
                (0, eval)(script)
            await RootTracking.set_input_files(files)
            RootDetectorApp.enhance_accessibility()
        } catch(error) {
            $body.empty()
            $table.find('#files-loaded-column-header').text('0 Files Loaded')
            GLOBAL.files = []
            await RootTracking.set_input_files([])
            throw error
        } finally {
            $modal.modal({closable: true}).modal('hide')
            $modal.find('.progress').progress('reset')
        }
    }

    //override
    static match_resultfile_to_inputfile(inputfilename, resultfilename){
        var basename          = file_basename(resultfilename)
        const no_ext_filename = remove_file_extension(inputfilename)
        const candidate_names = [
            inputfilename  +'.segmentation.png',
            no_ext_filename+'.segmentation.png',
            no_ext_filename+'.png',
        ]
        const original = GLOBAL.files[inputfilename]?.preparation?.source?.source_name
        if(original)
            candidate_names.push(original + '.segmentation.png', remove_file_extension(original) + '.segmentation.png', remove_file_extension(original) + '.png')
        return (candidate_names.indexOf(basename) != -1)
    }

    //override
    static async load_result(filename, resultfiles){
        const inputfile = GLOBAL.files[filename]
        if(inputfile != undefined){
            const companion = await this.validate_prepared_companion(inputfile, resultfiles[0], 'training annotation')
            const training_label = new File(
                [companion],
                `training-label-${Date.now()}-${Math.random().toString(36).slice(2)}.png`,
                {type:'image/png'},
            )
            if(companion.preparation_companion)
                training_label.preparation_companion = companion.preparation_companion
            // A prior prediction may already own the conventional result name
            // in the cache. Keep a separately named training label either way.
            if(inputfile.results){
                RootsTraining.register_imported_label(filename, training_label)
                $('body').toast({
                    message: `Imported a training label for ${filename}. The existing detection overlay was not replaced. Review the label before confirming training.`,
                    class: 'info', displayTime: 8000,
                })
                return
            }
            const resultfile = new File(
                //consistent file name
                [companion], `${filename}.segmentation.png`, {type:'image/png'}
            )

            //upload to flask & postprocess
            await this.ensure_uploaded(resultfile)
            const result = await RootSecurity.request(
                `/postprocess_detection/${encodeURIComponent(resultfile.name)}`,
                'POST',
            )
            await App.Detection.set_results(filename, result)
            RootsTraining.register_imported_label(filename, training_label)
        }
    }

    static async validate_prepared_companion(inputfile, file, description){
        if(!inputfile.preparation)
            return file
        await this.ensure_uploaded(inputfile)
        const send = confirmed => {
            const form = new FormData()
            form.append('files', file, file.name)
            form.append('prepared_filename', inputfile.name)
            form.append('manifest', JSON.stringify(inputfile.preparation))
            form.append('confirmed', confirmed ? 'true' : 'false')
            form.append('kind', description == 'training annotation' ? 'training_annotation' : 'exclusion_mask')
            return $.ajax({
                url: '/api/preparation/companion', method: 'POST', data: form,
                processData: false, contentType: false,
            })
        }
        let result
        try {
            result = await send(false)
        } catch(error) {
            if(error?.responseJSON?.code != 'companion_confirmation_required')
                throw error
            if(!window.confirm(
                `Crop ${description} ${file.name} using the exact original-pixel rectangle of ${inputfile.name}? `
                + 'Continue only if this mask is aligned with the original scan. No resizing or automatic alignment will be applied.'
            ))
                throw new Error('Mask import cancelled; the original mask has not been changed.')
            result = await send(true)
        }
        const blob = await fetch_as_blob(`/images/${encodeURIComponent(result.output)}`)
        const transformed = new File([blob], file.name, {type: 'image/png'})
        const previous = (inputfile.prepared_companions ?? []).find(record =>
            record.kind == result.provenance.kind
            && record.preparation_id == result.provenance.preparation_id
            && record.output_sha256 == result.provenance.output_sha256
        )
        // Keep the validated original-coordinate history when re-importing its exact mask.
        const provenance = previous ?? result.provenance
        transformed.preparation_companion = provenance
        inputfile.prepared_companions = (inputfile.prepared_companions ?? [])
            .filter(previous => previous.kind != result.provenance.kind)
            .concat([provenance])
        return transformed
    }

    static async on_exclusionmasks_select(event){
        try {
            for(const selected_mask of event.target.files){
                const maskbasename = remove_file_extension(selected_mask.name)

                for(const inputfile of Object.values(GLOBAL.files)){
                    const original = inputfile.preparation?.source?.source_name
                    if(wildcard_test(maskbasename, remove_file_extension(inputfile.name)) || (original && wildcard_test(maskbasename, remove_file_extension(original)))){
                        const companion = await this.validate_prepared_companion(inputfile, selected_mask, 'exclusion mask')
                        console.log('Matched mask for input file ', inputfile.name);
            
                        //indicate in the file table that a mask is available
                        //FIXME: this belongs into HTML files //FIXME:  class="cornered red circle icon"
                        $(`tr.title.table-row[filename="${inputfile.name}"]`)
                            .find('.status.icon.image').addClass('red')
            
                        //set file as not processed (needs reprocessing)
                        await App.Detection.set_results(inputfile.name, undefined)
            
                        const new_name = `${remove_file_extension(inputfile.name)}.exclusionmask.png`
                        const maskfile = rename_file(companion, new_name)
                        await this.ensure_uploaded(maskfile)
                    }
                }
            }
        } catch(error) {
            this.show_file_error(error)
        } finally {
            event.target.value = ""; //reset the input
        }
    }
}




function wildcard_test(wildcard_pattern, str) {
    //string comparison with wildcard characters * and ~
    //https://stackoverflow.com/questions/26246601/wildcard-string-comparison-in-javascript
    let w = wildcard_pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&'); // regexp escape 
        w = w.replace(/~/g,'*');                                   //allow ~ as wildcard (for windows paths)
    const re = new RegExp(`^${w.replace(/\*/g,'.*').replace(/\?/g,'.')}$`,'i');
    return re.test(str); // remove last 'i' above to have case sensitive
}
