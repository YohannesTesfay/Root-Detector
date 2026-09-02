RootSecurity = class {
    static token = undefined

    static async initialize(){
        const session = await $.get('/api/session')
        this.token = session.token
        $.ajaxPrefilter((options, _originalOptions, request) => {
            const method = String(options.method ?? options.type ?? 'GET').toUpperCase()
            const target = new URL(options.url, window.location.href)
            if(target.origin == window.location.origin && !['GET', 'HEAD', 'OPTIONS'].includes(method))
                request.setRequestHeader('X-RootDetector-Token', this.token)
        })
        return session
    }

    static request(url, method, data=undefined){
        return $.ajax({
            url: url,
            method: method,
            contentType: data == undefined ? undefined : 'application/json',
            data: data == undefined ? undefined : JSON.stringify(data),
        })
    }

    static error_message(error, fallback='The request could not be completed.'){
        const candidates = [
            error?.responseJSON?.message,
            error?.responseJSON?.error?.message,
            error?.message,
        ]
        if(error?.responseText){
            try {
                const parsed = JSON.parse(error.responseText)
                candidates.push(parsed?.message, parsed?.error?.message)
            } catch(_ignored) {
                if(!String(error.responseText).trim().startsWith('<'))
                    candidates.push(error.responseText)
            }
        }
        if(Number(error?.status) == 0)
            candidates.push(
                'The connection to the local RootDetector process was interrupted. '
                + 'Keep this window open, verify the selected file is still available, and retry.'
            )
        if(error?.statusText && error.statusText != 'error')
            candidates.push(error.statusText)

        for(const candidate of candidates){
            if(typeof candidate == 'string' && candidate.trim()){
                const normalized = candidate.trim()
                if(normalized != '[object Object]')
                    return normalized.slice(0, 2000)
            }
        }
        return fallback
    }
}
