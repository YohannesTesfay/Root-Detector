

RootsSettings = class extends BaseSettings{

    static on_settings(){
        super.on_settings()
        const $dialog = $('#settings-dialog')
        $dialog.off('keydown.rootdetector-focus').on('keydown.rootdetector-focus', event => {
            if(event.key != 'Tab')
                return
            const selector = [
                'button:not([disabled])',
                'input:not([type="hidden"]):not([disabled])',
                '.ui.dropdown[tabindex]:not(.disabled)',
                '[tabindex]:not([tabindex="-1"])',
            ].join(',')
            const focusable = [...new Set($dialog.find(selector).filter(':visible').get())]
            if(!focusable.length)
                return
            const first = focusable[0]
            const last = focusable[focusable.length - 1]
            if(event.shiftKey && document.activeElement == first){
                event.preventDefault()
                last.focus()
            } else if(!event.shiftKey && document.activeElement == last){
                event.preventDefault()
                first.focus()
            }
        })
        setTimeout(() => $('#settings-active-model').focus(), 0)
    }

    //override
    static async load_settings(){
        const data = await super.load_settings();

        this.update_gpu_info(data);
    }

    //override
    static update_settings_modal(models){
        super.update_settings_modal(models)

        const settings = GLOBAL.settings;
        $('#settings-exclusionmask-enable')
            .checkbox({onChange: _ => this.on_exmask_checkbox()})
            .checkbox(settings.exmask_enabled? 'check' : 'uncheck');
        $('#settings-too-many-roots-input')[0].value = settings.too_many_roots;
        if(models['exclusion_mask'])
            this.update_model_selection_dropdown(
                models['exclusion_mask'], settings.active_models['exclusion_mask'], $("#settings-exclusionmask-model")
            )
        if(models['tracking'])
            this.update_model_selection_dropdown(
                models['tracking'], settings.active_models['tracking'], $("#settings-tracking-model")
            )
    }


    //override
    static apply_settings_from_modal(){
        GLOBAL.settings.active_models['detection']      = $("#settings-active-model").dropdown('get value');
        GLOBAL.settings.active_models['exclusion_mask'] = $("#settings-exclusionmask-model").dropdown('get value');
        GLOBAL.settings.active_models['tracking']       = $("#settings-tracking-model").dropdown('get value');

        GLOBAL.settings.use_gpu
            = $('#settings-gpu-enable').checkbox('is checked')
        GLOBAL.settings.too_many_roots
            = Number($("#settings-too-many-roots-input")[0].value);
    }

    static on_exmask_checkbox(){
        var enabled = $('#settings-exclusionmask-enable').checkbox('is checked');
        GLOBAL.settings.exmask_enabled = enabled;
        $("#settings-exclusionmask-model-field").toggle(enabled)
    }

    static update_gpu_info(data){
        if(data['available_gpu']){
            $('#settings-no-gpu-warning').hide()
            $('#settings-gpu-available-box').show()
            $('#settings-gpu-name').text(data['available_gpu'])
        } else {
            $('#settings-no-gpu-warning').show()                        //maybe just hide the whole gpu field?
            $('#settings-gpu-available-box').hide()
        }
        console.log(data.settings)
        $('#settings-gpu-enable').checkbox(!!data.settings['use_gpu']? 'check' : 'uncheck')
    }
}
