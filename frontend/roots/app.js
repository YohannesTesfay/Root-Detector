
RootDetectorApp = class extends BaseApp {
    static Detection       = RootDetection;
    static Download        = RootDetectionDownload;
    static ViewControls    = ViewControls;
    static Settings        = RootsSettings;
    static FileInput       = RootsFileInput;
    static Training        = RootsTraining;

    static async init(){
        if(!window.location.href.startsWith('file://')){
            await this.Settings.load_settings()
            setup_sse()
        }

        $('#filetable.accordion').accordion({
            duration: 0,
            onOpening: function() { GLOBAL.App.ImageLoading.on_accordion_open(this) },
        })
        $('.tabs.menu .item').tab({onLoad: path => {
            if(path == 'training')
                this.Training.refresh_tab()
        }})
        this.FileInput.setup_drag_and_drop()
    }
}


//override
GLOBAL.App = RootDetectorApp;
App        = RootDetectorApp;
