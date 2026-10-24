RootAlerts = class {
    static items = []
    static expanded = false
    static installed = false
    static initialized = false
    static next_id = 1

    static install(){
        if(this.installed || !$.fn?.toast)
            return
        const original = $.fn.toast
        $.fn.toast = function(options, ...args){
            if(options && typeof options == 'object' && this.is('body')){
                RootAlerts.show(options)
                return this
            }
            return original.call(this, options, ...args)
        }
        this.installed = true
    }

    static show(options){
        const message = String(options.message ?? '').trim()
        if(!message)
            return
        const kind = ['error', 'warning', 'success', 'info'].find(value =>
            String(options.class ?? '').split(/\s+/).includes(value)
        ) ?? 'info'
        const key = options.key ?? null
        const details = Array.isArray(options.details) ? options.details.map(String) : []
        const old_index = this.items.findIndex(item => item.kind == kind && (
            key ? item.key == key : item.key == null && item.message == message
        ))
        const item = old_index < 0
            ? {id: this.next_id++, key, message, kind, details, count: 1}
            : this.items.splice(old_index, 1)[0]
        if(old_index >= 0){
            item.count = key ? 1 : item.count + 1
            item.message = message
            item.details = details
        }
        this.items.push(item)
        this.render()
        const duration = Number(options.displayTime ?? (kind == 'error' ? 0 : 8000))
        if(duration > 0){
            clearTimeout(item.timer)
            item.timer = setTimeout(() => this.dismiss(item.id), duration)
        }
    }

    static dismiss(id){
        const index = this.items.findIndex(item => item.id == id)
        if(index < 0)
            return
        clearTimeout(this.items[index].timer)
        this.items.splice(index, 1)
        this.render()
    }

    static clear_all(){
        for(const item of this.items)
            clearTimeout(item.timer)
        this.items = []
        this.expanded = false
        this.render()
    }

    static render(){
        const root = document.getElementById('root-alerts')
        if(!root)
            return
        root.hidden = this.items.length == 0
        const list = root.querySelector('.root-alert-list')
        list.replaceChildren()
        const hidden_count = Math.max(0, this.items.length - 3)
        const items = this.expanded ? this.items : this.items.slice(-3)
        for(const item of [...items].reverse()){
            const box = document.createElement('div')
            box.className = `root-alert root-alert-${item.kind}`
            box.setAttribute('role', item.kind == 'error' ? 'alert' : 'status')
            const content = document.createElement('div')
            content.className = 'root-alert-content'
            const text = document.createElement('span')
            text.textContent = item.message + (item.count > 1 ? ` (${item.count} times)` : '')
            content.append(text)
            if(item.details.length){
                const disclosure = document.createElement('details')
                const summary = document.createElement('summary')
                summary.textContent = `Show ${item.details.length} affected image(s)`
                const entries = document.createElement('ul')
                for(const detail of item.details){
                    const entry = document.createElement('li')
                    entry.textContent = detail
                    entries.append(entry)
                }
                disclosure.append(summary, entries)
                content.append(disclosure)
            }
            const close = document.createElement('button')
            close.type = 'button'
            close.className = 'root-alert-close'
            close.setAttribute('aria-label', 'Dismiss alert')
            close.textContent = '×'
            close.addEventListener('click', () => this.dismiss(item.id))
            box.append(content, close)
            list.append(box)
        }
        const more = root.querySelector('.root-alert-more')
        more.hidden = hidden_count == 0 && !this.expanded
        more.textContent = this.expanded ? 'Show recent alerts' : `Show ${hidden_count} earlier alert(s)`
    }

    static init(){
        if(this.initialized)
            return
        this.install()
        document.querySelector('#root-alerts .root-alert-clear')?.addEventListener('click', () => this.clear_all())
        document.querySelector('#root-alerts .root-alert-more')?.addEventListener('click', () => {
            this.expanded = !this.expanded
            this.render()
        })
        this.initialized = true
    }
}
