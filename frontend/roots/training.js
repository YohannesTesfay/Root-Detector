

RootsTraining = class extends BaseTraining {

    static training_active = false

    //override
    static refresh_tab(){
        super.refresh_tab()
        this.update_number_of_training_files_info()
    }
    
    //dummy override: all files selected  //TODO: move upstream
    static get_selected_files(){
        const files_with_results = Object.values(GLOBAL.files).filter( x => !!x.results )
        return files_with_results.map( x => x.name)
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
        if(this.training_active)
            return

        const filenames = this.get_selected_files()
        const progress_cb = message => this.on_training_progress(message)
        this.training_active = true
        try {
            this.show_modal()
            await this.upload_training_data(filenames)
            $(GLOBAL.event_source).on('training', progress_cb)
            const response = await $.ajax({
                url: '/training',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({
                    filenames: filenames,
                    options: this.get_training_options(),
                }),
            })
            if(response.result == 'OK')
                this.success_modal()
            else
                this.interrupted_modal()
            await GLOBAL.App.Settings.load_settings()
            return response
        } catch(error) {
            console.error(error)
            this.fail_modal()
            return undefined
        } finally {
            this.training_active = false
            $(GLOBAL.event_source).off('training', progress_cb)
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

    static async on_cancel_training(){
        const $button = $('#training-modal #cancel-training-button')
            .prop('disabled', true)
            .attr('aria-disabled', 'true')
            .addClass('disabled loading')
        $('#training-modal .label').text('Stopping training safely...')
        try {
            await $.get('/stop_training')
        } catch(error) {
            $button
                .prop('disabled', false)
                .attr('aria-disabled', 'false')
                .removeClass('disabled loading')
            $('body').toast({message:'Stopping failed.', class:'error'})
        }
        return false
    }

    static interrupted_modal(){
        const $progress = $('#training-modal .ui.progress')
        $progress.removeClass('active success').addClass('error')
        $progress.find('.label').text('Training interrupted. You can retry with the same settings.')
        $('#training-modal #cancel-training-button').hide()
        $('#training-modal #retry-training-button, #training-modal #close-training-button').show()
        $('#training-modal').modal({closable:true})
    }

    static fail_modal(){
        const $progress = $('#training-modal .ui.progress')
        $progress.removeClass('active success').addClass('error')
        $progress.find('.label').text('Training failed. Review the console details, then retry.')
        $('#training-modal #cancel-training-button').hide()
        $('#training-modal #retry-training-button, #training-modal #close-training-button').show()
        $('#training-modal').modal({closable:true})
    }

    static success_modal(){
        const $progress = $('#training-modal .ui.progress')
        $progress.progress('set percent', 100).removeClass('active error').addClass('success')
        $progress.find('.label').text('Training finished')
        $('#training-modal #cancel-training-button, #training-modal #retry-training-button').hide()
        $('#training-modal #close-training-button').show()
        $('#training-modal').modal({closable:true})
    }

    static on_retry_training(){
        $('#training-modal').modal('hide')
        return this.on_start_training()
    }

    static upload_training_data(filenames){
        const uploads = filenames.map(filename => upload_file_to_flask(GLOBAL.files[filename]))
        const segmentations = filenames
            .map(filename => GLOBAL.files[filename].results.segmentation)
            .filter(segmentation => segmentation instanceof Blob)
        return Promise.all(uploads.concat(
            segmentations.map(segmentation => upload_file_to_flask(segmentation))
        ))
    }

    //override
    static update_model_info(){
        const model_type  = $('#training-model-type').dropdown('get value');
        if(!model_type)
            return;
        
        super.update_model_info(model_type)
    }

    static update_number_of_training_files_info(){
        const n = this.get_selected_files().length;
        $('#training-number-of-files-info-label').text(n)
        $('#training-number-of-files-info-message').removeClass('hidden')
        $('#start-training-button')
            .prop('disabled', n == 0)
            .attr('aria-disabled', String(n == 0))
    }
}
