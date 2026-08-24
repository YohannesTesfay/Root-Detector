

RootsTraining = class extends BaseTraining {
    static active_run_id = undefined
    static terminal_states = ['completed', 'cancelled', 'failed']

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
            lr                  : Number($('#training-learning-rate')[0].value),
            epochs              : Number($('#training-number-of-epochs')[0].value),
        };
    }

    static async on_start_training(){
        const filenames = this.get_selected_files()
        try {
            this.show_modal()
            await this.upload_training_data(filenames)
            const run = await RootSecurity.request('/api/training/runs', 'POST', {
                filenames: filenames,
                options: this.get_training_options(),
            })
            this.active_run_id = run.id
            const result = await this.poll_until_finished()
            await GLOBAL.App.Settings.load_settings()
            return result
        } catch(error) {
            console.error(error)
            this.fail_modal()
            const diagnostic = error?.responseJSON?.diagnostic_id
            const message = error?.responseJSON?.message ?? error?.message ?? 'Training failed.'
            $('body').toast({
                message: diagnostic ? `${message} Diagnostic ID: ${diagnostic}` : message,
                class: 'error',
                displayTime: 0,
                closeIcon: true,
            })
            throw error
        }
    }

    static async poll_until_finished(){
        while(this.active_run_id){
            const run = await RootSecurity.request(
                `/api/training/runs/${this.active_run_id}`,
                'GET',
            )
            $('#training-modal .progress').progress({
                percent: run.progress * 100,
                autoSuccess: false,
            })
            $('#training-modal .label').text(
                run.state == 'cancelling' ? 'Stopping training...' : 'Training in progress...'
            )
            if(this.terminal_states.includes(run.state)){
                if(run.state == 'completed')
                    this.success_modal()
                else if(run.state == 'cancelled')
                    this.interrupted_modal()
                else {
                    this.fail_modal()
                    const message = run.error?.message ?? run.result?.message ?? 'Training failed.'
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
    }

    static async on_cancel_training(){
        $('#training-modal #cancel-training-button').addClass('disabled')
        try {
            if(this.active_run_id)
                await RootSecurity.request(
                    `/api/training/runs/${this.active_run_id}/cancel`,
                    'POST',
                )
            else
                await RootSecurity.request('/stop_training', 'POST')
            $('#training-modal .label').text('Stopping training...')
        } catch(error) {
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
