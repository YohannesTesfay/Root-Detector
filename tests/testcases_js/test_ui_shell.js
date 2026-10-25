const assert = require('assert')
const fs = require('fs')
const vm = require('vm')

const toastCalls = []
const context = {
    setTimeout: () => 1,
    clearTimeout: () => {},
    $: {fn: {toast(options){toastCalls.push(options); return this}}},
}
vm.createContext(context)
vm.runInContext(fs.readFileSync('frontend/roots/alerts.js', 'utf8'), context)
context.RootAlerts.render = () => {}
context.RootAlerts.install()
const body = {is: selector => selector == 'body'}
context.$.fn.toast.call(body, {message: 'Processing failed', class: 'error', details: ['one.tif']})
context.$.fn.toast.call(body, {message: 'Processing failed', class: 'error', details: ['one.tif']})
assert.strictEqual(context.RootAlerts.items.length, 1)
assert.strictEqual(context.RootAlerts.items[0].count, 2)
assert.strictEqual(context.RootAlerts.items[0].details[0], 'one.tif')
assert.strictEqual(toastCalls.length, 0)
context.$.fn.toast.call(body, {key: 'batch', message: '1 image failed', class: 'error', details: ['one.tif']})
context.$.fn.toast.call(body, {key: 'batch', message: '2 images failed', class: 'error', details: ['one.tif', 'two.tif']})
assert.strictEqual(context.RootAlerts.items.length, 2)
assert.strictEqual(context.RootAlerts.items[1].message, '2 images failed')
assert.strictEqual(context.RootAlerts.items[1].details.length, 2)
context.RootAlerts.clear_all()
assert.strictEqual(context.RootAlerts.items.length, 0)

context.BaseDownload = class {}
vm.runInContext(fs.readFileSync('frontend/roots/download.js', 'utf8'), context)
const label = {hidden: false, prop(name, value){this[name] = value; return this}}
const progress = {text(value){this.value = value; return this}}
const status = {hidden: true, prop(name, value){this[name] = value; return this},
    find(){return progress}}
const button = {busy: false, disabled: false, attributes: {},
    toggleClass(name, value){assert.strictEqual(name, 'is-busy'); this.busy = value; return this},
    prop(name, value){this[name] = value; return this},
    attr(name, value){this.attributes[name] = value; return this},
    find(selector){return selector == '.download-label' ? label : status},
}
context.set_download_all_busy(button, true, 42.6)
assert.strictEqual(button.busy, true)
assert.strictEqual(button.disabled, true)
assert.strictEqual(label.hidden, true)
assert.strictEqual(status.hidden, false)
assert.strictEqual(progress.value, 'Preparing download… 43%')
context.set_download_all_busy(button, false)
assert.strictEqual(label.hidden, false)
assert.strictEqual(status.hidden, true)

class Element {
    constructor(){this.listeners = {}; this.classList = {toggle(){}}; this.hidden = true}
    addEventListener(type, listener){this.listeners[type] = listener}
    removeEventListener(type){delete this.listeners[type]}
    focus(){document.activeElement = this}
}
const layer = new Element()
const panel = new Element()
const cancel = new Element()
const approve = new Element()
const title = new Element()
const message = new Element()
const elements = {
    '.root-confirm-panel': panel,
    '.root-confirm-cancel': cancel,
    '.root-confirm-approve': approve,
    '.root-confirm-title': title,
    '.root-confirm-message': message,
}
layer.querySelector = selector => elements[selector]
const trigger = new Element()
const document = {
    activeElement: trigger,
    getElementById: id => id == 'root-confirm-layer' ? layer : null,
    listeners: {},
    addEventListener(type, listener){this.listeners[type] = listener},
    removeEventListener(type){delete this.listeners[type]},
}
context.document = document
vm.runInContext(fs.readFileSync('frontend/roots/dialogs.js', 'utf8'), context)

async function test_dialog(){
    const accepted = context.RootDialogs.confirm('Replace the images?', {destructive: true})
    assert.strictEqual(layer.hidden, false)
    assert.strictEqual(document.activeElement, cancel)
    assert.strictEqual(message.textContent, 'Replace the images?')
    approve.listeners.click()
    assert.strictEqual(await accepted, true)
    assert.strictEqual(layer.hidden, true)
    assert.strictEqual(document.activeElement, trigger)

    const rejected = context.RootDialogs.confirm('Discard the batch?')
    document.listeners.keydown({key: 'Escape', preventDefault(){}, stopImmediatePropagation(){}})
    assert.strictEqual(await rejected, false)
    assert.strictEqual(context.RootDialogs.active, false)
}

test_dialog().then(() => console.log('UI shell tests passed.')).catch(error => {
    console.error(error)
    process.exitCode = 1
})
