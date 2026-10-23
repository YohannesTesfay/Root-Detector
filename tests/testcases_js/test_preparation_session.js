const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const {File} = require('node:buffer')

const repository = path.resolve(__dirname, '../..')
const elements = new Map()
let dimmer_hidden = false
function element(selector){
    if(!elements.has(selector))
        elements.set(selector, {visible: selector == '#preparation-dialog', text: '', value: ''})
    const state = elements.get(selector)
    return {
        modal(...args){
            if(args[0] == 'destroy') state.destroyed = (state.destroyed ?? 0) + 1
            if(args[0] == 'show') state.visible = true
            if(args[0] == 'hide'){
                state.visible = false
                if(state.onHidden) state.onHidden()
            }
            if(args[0] == 'setting' && args[1] == 'onHidden') state.onHidden = args[2]
            return this
        },
        is(query){ return query == ':visible' ? state.visible : false },
        closest(){ return {hasClass: name => name == 'hidden' && dimmer_hidden} },
        removeClass(){ return this },
        show(){ state.visible = true; return this },
        hide(){ state.visible = false; return this },
        toggle(visible){ state.visible = visible; return this },
        text(value){ if(value === undefined) return state.text; state.text = value; return this },
        val(value){ if(value === undefined) return state.value; state.value = value; return this },
        prop(){ return this },
        attr(){ return this },
        removeAttr(){ return this },
        css(){ return this },
    }
}
global.$ = element
global.File = File
global.window = {confirm: () => true}
global.GLOBAL = {files: {}}
global.RootSecurity = {
    limits: {},
    error_message: error => error.message,
    request: async () => ({}),
}
global.fetch_as_blob = async () => new Blob(['prepared'])
global.RootsFileInput = {set_input_files: async () => {}}
let inspected = 0
global.upload_file_to_flask = async file => ({
    id: `stage-${++inspected}`,
    preview: `preview-${inspected}.png`,
    source_width: 1400,
    source_height: 1400,
    source_bytes: file.size,
})
vm.runInThisContext(fs.readFileSync(path.join(repository, 'frontend/roots/preparation.js'), 'utf8'))

async function select(name){
    const target = {files: [new File(['original'], name)], value: 'chosen'}
    await RootPreparation.on_files_select({target})
    assert.equal(target.value, '', 'File input must reset so the same files can be selected again.')
}

async function main(){
    const template = fs.readFileSync(path.join(repository, 'templates/roots/modals.html'), 'utf8')
    for(const id of ['preparation-recovery', 'preparation-resume', 'preparation-discard'])
        assert(template.includes(`id="${id}"`), `${id} must be reachable in the dialog.`)

    const discarded = []
    RootSecurity.request = async url => { discarded.push(url); return {} }
    await select('first.png')
    const firstStage = RootPreparation.stage.id
    element('#preparation-dialog').modal('hide') // Simulate another UI path hiding the modal.
    dimmer_hidden = true
    await select('second.png')
    assert.equal(elements.get('#preparation-dialog').destroyed, 1, 'A hidden Fomantic dimmer needs its stale modal instance reset.')
    dimmer_hidden = false
    assert.equal(element('#preparation-dialog').is(':visible'), true)
    assert.equal(element('#preparation-recovery').is(':visible'), true)
    assert.equal(RootPreparation.sources[0].name, 'first.png')
    assert.equal(RootPreparation.pending_sources[0].name, 'second.png')
    await RootPreparation.resume()
    assert.equal(RootPreparation.stage.id, firstStage)
    assert.equal(RootPreparation.pending_sources.length, 0)

    await select('second.png')
    await RootPreparation.discard_session(true)
    assert(discarded.some(url => url.includes(firstStage)))
    assert.equal(RootPreparation.sources[0].name, 'second.png')
    assert.equal(RootPreparation.pending_sources.length, 0)
    await RootPreparation.cancel()
    assert.equal(RootPreparation.has_session(), false)
    assert.equal(element('#preparation-dialog').is(':visible'), false)

    global.upload_file_to_flask = async () => { throw new Error('inspection failed') }
    await select('retry.png')
    assert.equal(RootPreparation.stage, undefined)
    assert.equal(element('#preparation-recovery').is(':visible'), true)
    assert.equal(element('#preparation-resume').text(), 'Retry current image')
    global.upload_file_to_flask = async file => ({
        id: `stage-${++inspected}`, preview: 'retry-preview.png',
        source_width: 1400, source_height: 1400, source_bytes: file.size,
    })
    await RootPreparation.resume()
    assert(RootPreparation.stage?.id)

    let failDiscard = true
    RootSecurity.request = async url => {
        if(failDiscard && url.includes('/discard')) throw new Error('discard failed')
        discarded.push(url)
        return {}
    }
    const retryStage = RootPreparation.stage.id
    await RootPreparation.cancel()
    assert.equal(RootPreparation.stage.id, retryStage, 'Failed server cleanup must retain a retryable stage.')
    assert.equal(element('#preparation-dialog').is(':visible'), true)
    RootSecurity.request = async () => { throw {responseJSON: {code: 'preparation_not_found'}} }
    await RootPreparation.cancel()
    assert.equal(RootPreparation.has_session(), false, 'An already-removed server stage must not trap the browser.')

    await select('original.png')
    RootPreparation.update_bounds = () => true
    RootPreparation.current_bounds = () => ({left: 10, top: 20, width: 1280, height: 1280})
    const original = RootPreparation.sources[0]
    const manifest = {output_name: 'prepared.png', source: {source_name: original.name}, rectangle: RootPreparation.current_bounds()}
    failDiscard = true
    RootSecurity.request = async url => {
        if(url == '/api/preparation/apply') return {output: 'prepared.png', manifest}
        if(failDiscard && url.includes('/discard')) throw new Error('discard failed')
        return {}
    }
    await RootPreparation.apply_current()
    assert.equal(RootPreparation.prepared.length, 0, 'Failed cleanup must not commit a duplicate copy.')
    assert(RootPreparation.stage?.id)
    failDiscard = false
    await RootPreparation.apply_current()
    assert.equal(RootPreparation.prepared.length, 1)
    assert.deepEqual(RootPreparation.prepared[0].preparation, manifest)
    assert.equal(RootPreparation.sources[0], original, 'Original file must remain untouched.')

    let imported
    RootsFileInput.set_input_files = async files => { imported = files.slice() }
    element('#preparation-dialog').modal('hide')
    await RootPreparation.import_prepared()
    assert.equal(imported.length, 1, 'Already-hidden dialog must not block import.')
    assert.deepEqual(imported[0].preparation, manifest)
    assert.equal(RootPreparation.has_session(), false)
    console.log('Preparation recovery, safe reselection, discard retry, and provenance passed')
}

main().catch(error => { console.error(error); process.exitCode = 1 })
