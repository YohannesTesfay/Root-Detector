const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const state = {}
const element = selector => {
    if(!state[selector]) state[selector] = {text: '', visible: false, href: undefined, disabled: false}
    const target = state[selector]
    return {
        modal: action => {target.modal = action; return element(selector)},
        text: value => {target.text = value; return element(selector)},
        hide: () => {target.visible = false; return element(selector)},
        show: () => {target.visible = true; return element(selector)},
        attr: (name, value) => {target[name] = value; return element(selector)},
        removeAttr: name => {delete target[name]; return element(selector)},
        prop: (name, value) => {target[name] = value; return element(selector)},
    }
}
global.$ = element
let updateResult = {status: 'current'}
global.RootSecurity = {
    request: async url => url == '/api/version'
        ? {version: '0.1.0-rc.1', package: 'installer'} : updateResult,
    error_message: error => error.message,
}
vm.runInThisContext(fs.readFileSync(path.resolve(__dirname, '../../frontend/roots/updates.js'), 'utf8'))

async function main(){
    await RootUpdates.open()
    assert.strictEqual(state['#updates-installed-version'].text, '0.1.0-rc.1')
    updateResult = {status: 'available', version: '0.1.0',
        url: 'https://github.com/YohannesTesfay/Root-Detector/releases/tag/v0.1.0'}
    await RootUpdates.check()
    assert.strictEqual(state['#updates-release-link'].visible, true)
    assert.strictEqual(state['#updates-release-link'].href, updateResult.url)
    updateResult = {status: 'available', version: '<script>', url: 'https://evil.example/update.exe'}
    await RootUpdates.check()
    assert.strictEqual(state['#updates-release-link'].visible, false)
    assert.strictEqual(state['#updates-release-link'].href, undefined)
    assert.strictEqual(state['#updates-check-button'].disabled, false)
    console.log('Manual update display and release-link guard passed.')
}
main().catch(error => {console.error(error); process.exitCode = 1})
