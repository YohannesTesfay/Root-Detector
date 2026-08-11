

RootsFileInput = class extends BaseFileInput{
    static show_file_error(error){
        console.error(error)
        $('body').toast({
            message: error?.message ?? String(error),
            class: 'error', displayTime: 0, closeIcon: true,
        })
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
            const files = Array.from(event.target.files).filter(file => this.is_supported_image(file))
            await this.set_input_files(files)
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

    static async set_input_files(files){
        files = Array.from(files)
        const filenames = files.map(file => file.name)
        const duplicates = filenames.filter((name, index) => filenames.indexOf(name) != index)
        if(duplicates.length)
            throw new Error(`Duplicate filenames are not supported: ${[...new Set(duplicates)].join(', ')}`)

        if(!window.location.href.startsWith('file://'))
            await $.get('/clear_cache')

        GLOBAL.files = []
        for(const file of files)
            GLOBAL.files[file.name] = new InputFile(file)
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

    //override
    static async refresh_filetable(files){
        const promise  = BaseFileInput.refresh_filetable(files)
        const promise2 = RootTracking.set_input_files(files)
        return Promise.all([promise, promise2])
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
        return (candidate_names.indexOf(basename) != -1)
    }

    //override
    static async load_result(filename, resultfiles){
        console.log(filename, resultfiles)
        const inputfile = GLOBAL.files[filename]
        if(inputfile != undefined){
            const resultfile = new File(
                //consistent file name
                [resultfiles[0]], `${filename}.segmentation.png`, {type:'image/png'}
            )

            //upload to flask & postprocess
            await upload_file_to_flask(resultfile)
            const result = await $.get(`/postprocess_detection/${resultfile.name}`)
            await App.Detection.set_results(filename, result)
        }
    }

    static async on_exclusionmasks_select(event){
        try {
            for(const selected_mask of event.target.files){
                const maskbasename = remove_file_extension(selected_mask.name)

                for(const inputfile of Object.values(GLOBAL.files)){
                    if( wildcard_test(maskbasename, remove_file_extension(inputfile.name)) ){
                        console.log('Matched mask for input file ', inputfile.name);
            
                        //indicate in the file table that a mask is available
                        //FIXME: this belongs into HTML files //FIXME:  class="cornered red circle icon"
                        $(`tr.title.table-row[filename="${inputfile.name}"]`)
                            .find('.status.icon.image').addClass('red')
            
                        //set file as not processed (needs reprocessing)
                        await App.Detection.set_results(inputfile.name, undefined)
            
                        const new_name = `${remove_file_extension(inputfile.name)}.exclusionmask.png`
                        const maskfile = rename_file(selected_mask, new_name)
                        await upload_file_to_flask(maskfile)
                    }
                }
            }
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
