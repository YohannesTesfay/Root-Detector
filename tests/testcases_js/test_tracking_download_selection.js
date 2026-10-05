const assert = require('assert')
const fs = require('fs')
const vm = require('vm')

async function main(){
    let request
    let downloaded
    const context = {
        BaseDownload: class {},
        GLOBAL: {files: {
            'first.png': {tracking_results: {
                'second.png': {growthmap: 'variant.png', run_id: 'a'.repeat(32),
                    segmentation0: 's0.png', segmentation1: 's1.png',
                    statistics: {}, points0: [], points1: []},
                'third.png': {success: false, code: 'tracking_failed'},
            }},
            'fourth.png': {tracking_results: {
                'fifth.png': {code: 'too_many_roots'},
            }},
        }},
        RootSecurity: {request: async (...args) => {
            request = args
            return 'tracking_results.selected.zip'
        }},
        downloadURI: (...args) => { downloaded = args },
        url_for_image: name => `/images/${name}`,
        $: () => {
            const element = {addClass: () => element, removeClass: () => element,
                closest: () => element,
                attr: name => ({filename0: 'first.png', filename1: 'second.png',
                    filename: 'first.png.second.png'}[name] ?? element),
                removeAttr: () => element, toast: () => element}
            return element
        },
        console,
    }
    vm.createContext(context)
    vm.runInContext(fs.readFileSync('frontend/roots/download.js', 'utf8'), context)
    await context.RootTrackingDownload.on_download_all()

    assert.strictEqual(request[0], '/compile_tracking_results')
    assert.strictEqual(request[1], 'POST')
    assert.deepStrictEqual(JSON.parse(JSON.stringify(request[2].file_pairs)), [
        ['first.png', 'second.png', 'a'.repeat(32)],
    ])
    assert.deepStrictEqual(downloaded, [
        'RootDetector-tracking-results.zip',
        '/images/tracking_results.selected.zip',
    ])
    request = undefined
    await context.RootTrackingDownload.on_single_item_download_click({target: {}, currentTarget: {}})
    assert.strictEqual(request[0], '/compile_tracking_results', 'Single export must validate the selected result on the backend')
    assert.deepStrictEqual(JSON.parse(JSON.stringify(request[2].file_pairs)), [
        ['first.png', 'second.png', 'a'.repeat(32)],
    ])
    assert.strictEqual(downloaded[0], `RootDetector-tracking-${'a'.repeat(32)}.zip`)
    console.log('Tracking download selection tests passed.')
}

main().catch(error => {
    console.error(error)
    process.exitCode = 1
})
