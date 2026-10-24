RootDialogs = class {
    static active = false

    static confirm(message, options={}){
        const layer = document.getElementById('root-confirm-layer')
        if(!layer || this.active)
            return Promise.reject(new Error('Confirmation dialog is unavailable.'))
        this.active = true
        const previous_focus = document.activeElement
        const panel = layer.querySelector('.root-confirm-panel')
        const cancel = layer.querySelector('.root-confirm-cancel')
        const approve = layer.querySelector('.root-confirm-approve')
        layer.querySelector('.root-confirm-title').textContent = options.title ?? 'Please confirm'
        layer.querySelector('.root-confirm-message').textContent = message
        approve.textContent = options.confirmLabel ?? 'Continue'
        approve.classList.toggle('negative', !!options.destructive)
        approve.classList.toggle('primary', !options.destructive)
        layer.hidden = false

        return new Promise(resolve => {
            const finish = accepted => {
                document.removeEventListener('keydown', on_keydown, true)
                cancel.removeEventListener('click', on_cancel)
                approve.removeEventListener('click', on_approve)
                layer.removeEventListener('click', on_backdrop)
                layer.hidden = true
                this.active = false
                previous_focus?.focus?.()
                resolve(accepted)
            }
            const on_cancel = () => finish(false)
            const on_approve = () => finish(true)
            const on_backdrop = event => {
                if(event.target == layer)
                    finish(false)
            }
            const on_keydown = event => {
                if(event.key == 'Escape'){
                    event.preventDefault()
                    event.stopImmediatePropagation()
                    finish(false)
                } else if(event.key == 'Tab'){
                    const buttons = [cancel, approve]
                    const index = buttons.indexOf(document.activeElement)
                    event.preventDefault()
                    event.stopImmediatePropagation()
                    buttons[(index + (event.shiftKey ? 1 : -1) + 2) % 2].focus()
                }
            }
            cancel.addEventListener('click', on_cancel)
            approve.addEventListener('click', on_approve)
            layer.addEventListener('click', on_backdrop)
            document.addEventListener('keydown', on_keydown, true)
            panel.focus()
            cancel.focus()
        })
    }
}
