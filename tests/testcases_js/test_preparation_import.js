const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const {File} = require('node:buffer')

global.File = File
global.BaseFileInput = class {}
global.GLOBAL = {files: {}}
global.RootSecurity = {}
global.file_basename = name => name.split('/').pop()
global.remove_file_extension = name => name.replace(/\.[^.]*$/, '')
global.sleep = async () => {}
global.window = {location: {href: 'http://localhost'}, confirm: () => false}
const repository = path.resolve(__dirname, '../..')
vm.runInThisContext(fs.readFileSync(path.join(repository, 'frontend/roots/file_input.js'), 'utf8'))

async function main(){
    const realSet = RootsFileInput.set_input_files
    const realLoadResults = RootsFileInput.load_result_files
    const realRestore = RootsFileInput.restore_prepared_files
    const seen = []
    RootsFileInput.set_input_files = async files => seen.push(['inputs', files])
    RootsFileInput.load_result_files = async files => seen.push(['results', files])
    RootsFileInput.restore_prepared_files = async files => seen.push(['prepared', files])
    const generic = new File(['zip'], 'results.zip', {type: 'application/zip'})
    await RootsFileInput.load_list_of_files([generic])
    assert.equal(seen[0][0], 'results', 'Existing result ZIP imports must not be routed as prepared input.')
    seen.length = 0
    await RootsFileInput.load_list_of_files([new File(['zip'], 'RootDetector-prepared-images (1).zip')])
    assert.equal(seen[0][0], 'prepared')
    RootsFileInput.restore_prepared_files = realRestore
    RootsFileInput.load_result_files = realLoadResults

    const manifest = {output_name: 'prepared.png', preparation_id: 'id', source: {source_name: 'source.tiff'}}
    global.$ = {ajax: async () => ({files: [{output: 'cache.png', manifest}]})}
    global.fetch_as_blob = async () => { seen.push(['fetch']); return new Blob(['image']) }
    seen.length = 0
    await RootsFileInput.restore_prepared_files([new File(['zip'], 'renamed.zip')])
    assert.deepEqual(seen.map(item => item[0]), ['fetch', 'inputs'])
    assert.equal(seen[1][1][0].preparation, manifest)
    seen.length = 0
    $.ajax = async () => { throw new Error('stale image hash') }
    await assert.rejects(RootsFileInput.restore_prepared_files([generic]), /stale image hash/)
    assert.equal(seen.length, 0, 'Failed verification must preserve the currently loaded input set.')

    GLOBAL.files = {'prepared.png': {name: 'prepared.png', preparation: manifest}}
    assert(RootsFileInput.match_resultfile_to_inputfile('prepared.png', 'source.png'))
    assert(RootsFileInput.match_resultfile_to_inputfile('prepared.png', 'source.tiff.segmentation.png'))
    RootsFileInput.ensure_uploaded = async () => {}
    const masks = []
    const provenance = {kind: 'training_annotation', preparation_id: 'id', operation: 'pixel_preserving_crop'}
    $.ajax = async options => {
        masks.push(options.data.get('confirmed'))
        if(options.data.get('confirmed') == 'false')
            throw {responseJSON: {code: 'companion_confirmation_required'}}
        return {output: 'mask.png', provenance}
    }
    window.confirm = () => true
    const transformed = await RootsFileInput.validate_prepared_companion(GLOBAL.files['prepared.png'], new File(['tiff'], 'source.tiff'), 'training annotation')
    assert.deepEqual(masks, ['false', 'true'])
    assert.equal(transformed.preparation_companion, provenance)
    assert.deepEqual(GLOBAL.files['prepared.png'].prepared_companions, [provenance])
    window.confirm = () => false
    await assert.rejects(RootsFileInput.validate_prepared_companion(GLOBAL.files['prepared.png'], new File(['mask'], 'source.png'), 'training annotation'), /cancelled/)

    const realCollect = RootsFileInput.collect_result_files
    RootsFileInput.collect_result_files = async files => files
    const sidecar = {dir: false, _data: {uncompressedSize: 100}, async: async () => JSON.stringify({schema: 1, preparations: [manifest]})}
    global.JSZip = {loadAsync: async () => ({files: {'preparation-manifest.json': sidecar}})}
    RootSecurity.request = async (_url, _method, data) => ({manifest: data.manifest})
    delete GLOBAL.files['prepared.png'].preparation
    await RootsFileInput.collect_results_from_zipfile(generic)
    assert.equal(GLOBAL.files['prepared.png'].preparation.output_name, manifest.output_name)
    const exclusion = {kind: 'exclusion_mask', output_name: 'prepare-companion-test.png', preparation_id: 'id'}
    const importedMasks = []
    RootsFileInput.ensure_uploaded = async file => importedMasks.push(file.name)
    const archiveFiles = {
        'preparation-manifest.json': sidecar,
        'preparation-companions.json': {dir: false, _data: {uncompressedSize: 100}, async: async () => JSON.stringify({schema: 1, companions: [exclusion]})},
        'preparation-companions/prepare-companion-test.png': {dir: false, _data: {uncompressedSize: 4}, async: async () => new Blob(['mask'])},
    }
    JSZip.loadAsync = async () => ({files: archiveFiles})
    const invalidated = []
    global.App = {Detection: {set_results: async filename => invalidated.push(filename)}}
    global.RootTracking = {set_input_files: async () => invalidated.push('tracking')}
    RootSecurity.request = async (_url, _method, data) => {
        assert.equal(data.restore_exclusion_masks, true)
        return {manifest: data.manifest, companions: data.companions}
    }
    await RootsFileInput.collect_results_from_zipfile(generic)
    assert(importedMasks.includes(exclusion.output_name))
    assert.deepEqual(invalidated, ['prepared.png', 'tracking'])
    assert.deepEqual(GLOBAL.files['prepared.png'].prepared_companions, [exclusion])
    delete GLOBAL.files['prepared.png'].preparation
    RootSecurity.request = async () => { throw new Error('hash mismatch') }
    await assert.rejects(RootsFileInput.collect_results_from_zipfile(generic), /hash mismatch/)
    assert.equal(GLOBAL.files['prepared.png'].preparation, undefined)
    RootsFileInput.collect_result_files = realCollect
    RootsFileInput.set_input_files = realSet

    // A thrown row/template initialization error must settle the promise and hide progress.
    const modalCalls = []
    const element = {
        find(){ return this }, empty(){ return this }, text(){ return this },
        modal(arg){ modalCalls.push(arg); return this }, progress(){ return this },
    }
    global.$ = selector => selector == 'template#filetable-row-template'
        ? {tmpl(){ throw new Error('template row failed') }} : element
    global.RootTracking = {set_input_files: async files => assert.deepEqual(files, [])}
    global.RootDetectorApp = {enhance_accessibility(){}}
    await assert.rejects(RootsFileInput.refresh_filetable([{name: 'file.png'}]), /template row failed/)
    assert(modalCalls.includes('hide'))
    assert.deepEqual(GLOBAL.files, [])
    console.log('Prepared input, mask confirmation, sidecar identity, and async table errors passed')
}

main().catch(error => { console.error(error); process.exitCode = 1 })
