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
}
