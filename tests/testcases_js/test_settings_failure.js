const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const repository = path.resolve(__dirname, '..', '..')
let modalOpened = false
let toastMessage = ''
global.$ = () => ({
    modal: () => {modalOpened = true},
    toast: options => {toastMessage = options.message},
})
global.RootSecurity = {error_message: error => error.message}
global.BaseSettings = class {
    static async load_settings(){throw new Error('Server unavailable')}
}
vm.runInThisContext(fs.readFileSync(path.join(repository, 'frontend/roots/settings.js'), 'utf8'))

RootsSettings.on_settings()
    .then(() => {
        assert.strictEqual(modalOpened, false)
        assert.strictEqual(toastMessage, 'Could not load settings: Server unavailable')
        console.log('Settings failure test passed.')
    })
    .catch(error => {console.error(error); process.exitCode = 1})
