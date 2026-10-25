RootUpdates = class {
    static async open(){
        const dialog = $('#updates-dialog')
        $('#updates-installed-version').text('Loading…')
        $('#updates-status').text('')
        $('#updates-release-link').hide().removeAttr('href')
        $('#updates-check-button').prop('disabled', false)
        dialog.modal('show')
        try {
            const info = await RootSecurity.request('/api/version', 'GET')
            const label = info.version ?? 'Unknown'
            const kind = info.package == 'source' ? ' (source checkout)' : ''
            $('#updates-installed-version').text(label + kind)
        } catch(error) {
            $('#updates-installed-version').text('Unavailable')
            $('#updates-status').text(RootSecurity.error_message(error, 'Could not read this installation’s version.'))
        }
    }

    static async check(){
        const button = $('#updates-check-button')
        button.prop('disabled', true)
        $('#updates-release-link').hide().removeAttr('href')
        $('#updates-status').text('Checking published releases…')
        try {
            const result = await RootSecurity.request('/api/updates/check', 'POST')
            if(result.status == 'available'){
                const release = new URL(result.url)
                if(release.protocol != 'https:' || release.hostname != 'github.com'
                        || !release.pathname.startsWith('/YohannesTesfay/Root-Detector/releases/tag/'))
                    throw new Error('The release link was not recognized.')
                $('#updates-status').text(`Version ${result.version} is available.`)
                $('#updates-release-link').attr('href', release.href).show()
            } else if(result.status == 'current') {
                $('#updates-status').text('No newer compatible release is published.')
            } else {
                $('#updates-status').text(result.message ?? 'The update check is unavailable. Try again later.')
            }
        } catch(error) {
            $('#updates-status').text(RootSecurity.error_message(error, 'The update check could not finish.'))
        } finally {
            button.prop('disabled', false)
        }
    }
}
