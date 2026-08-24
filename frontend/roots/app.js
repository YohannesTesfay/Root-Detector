
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
        $(document).on('keydown.rootdetector-buttons', '[role="button"]', event => {
            if(event.key != 'Enter' && event.key != ' ')
                return
            event.preventDefault()
            event.currentTarget.click()
        })
        this.FileInput.setup_drag_and_drop()
        this.enhance_accessibility()
    }

    static enhance_accessibility(){
        $('.accordion .title').each(function(){
            const filename = $(this).attr('filename')
            const filename0 = $(this).attr('filename0')
            const filename1 = $(this).attr('filename1')
            const item_name = filename ?? `${filename0} to ${filename1}`
            $(this)
                .attr('role', 'button')
                .attr('tabindex', '0')
                .attr('aria-expanded', $(this).hasClass('active') ? 'true' : 'false')
                .attr('aria-label', `Expand or collapse details for ${item_name}`)
                .attr('title', 'Expand or collapse result details')
        })
        const controls = [
            ['.content-menu .process, .secondary.icon.menu .process', 'Process this image or pair'],
            ['.view-menu-button', 'Open display options'],
            ['.download.item', 'Download this result'],
            ['.help-menu-button', 'Show keyboard and editing help'],
            ['.secondary.icon.menu .item[onclick*="correction"]', 'Apply manual corrections'],
        ]
        for(const [selector, label] of controls){
            $(selector).each(function(){
                $(this)
                    .attr('role', 'button')
                    .attr('tabindex', $(this).hasClass('disabled') ? '-1' : '0')
                    .attr('aria-label', label)
                    .attr('title', label)
            })
        }
    }
}


//override
GLOBAL.App = RootDetectorApp;
App        = RootDetectorApp;
