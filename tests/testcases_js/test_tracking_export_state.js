const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const repository = path.resolve(__dirname, '..', '..')
const pair = ['first.tif', 'second.tif']
const complete = {
    success: true,
    growthmap: 'growth.png',
    growthmap_rgba: 'overlay.png',
    segmentation0: 'first.png',
    segmentation1: 'second.png',
    statistics: {sum_same: 1},
    points0: [],
    points1: [],
}

const element = {
    length: 1,
    find: () => element,
    filter: () => element,
    hide: () => element,
    show: () => element,
    toggle: () => element,
    dimmer: () => element,
    addClass: () => element,
    removeClass: () => element,
    css: () => element,
    attr: () => element,
    removeAttr: () => element,
    checkbox: () => element,
    toast: () => element,
}
global.$ = () => element
global.GLOBAL = {
    files: {
        [pair[0]]: {name: pair[0], tracking_results: {[pair[1]]: {...complete}}},
        [pair[1]]: {name: pair[1]},
    },
}
global.BaseDownload = class {}
global.ViewControls = class {}
global.RootSecurity = {request: async () => 'result.zip'}
global.url_for_image = filename => filename
global.downloadURI = () => {}
const archiveEntries = []
global.JSZip = class {
    file(name, value){archiveEntries.push([name, value])}
    async generateAsync(){return 'archive-bytes'}
}
const blobs = []
global.download_blob = (filename, blob) => blobs.push([filename, blob])

vm.runInThisContext(fs.readFileSync(path.join(repository, 'frontend/roots/tracking.js'), 'utf8'))
vm.runInThisContext(fs.readFileSync(path.join(repository, 'frontend/roots/download.js'), 'utf8'))

async function test_failed_rerun_cannot_export_stale_result(){
    RootTracking.apply_pipeline_result({filename0: pair[0], filename1: pair[1], state: 'failed', error: {message: 'GPU error'}})
    assert.deepStrictEqual(GLOBAL.files[pair[0]].tracking_results[pair[1]], {})
    assert.strictEqual(RootTrackingDownload.is_exportable_result(GLOBAL.files[pair[0]].tracking_results[pair[1]]), false)
}

async function test_review_required_result_remains_available(){
    const result = {...complete, success: false}
    RootTracking.apply_pipeline_result({filename0: pair[0], filename1: pair[1], state: 'review_required', result})
    assert.strictEqual(GLOBAL.files[pair[0]].tracking_results[pair[1]], result)
    assert.strictEqual(RootTrackingDownload.is_exportable_result(result), true)
}

async function test_only_valid_results_are_compiled(){
    const requests = []
    const downloads = []
    RootSecurity.request = async (_url, _method, body) => {
        requests.push(body)
        return 'result.zip'
    }
    global.downloadURI = (filename) => downloads.push(filename)
    GLOBAL.files[pair[0]].tracking_results[pair[1]] = {code: 'too_many_roots'}
    await RootTrackingDownload.on_download_all()
    assert.strictEqual(requests.length, 0)

    GLOBAL.files[pair[0]].tracking_results[pair[1]] = {...complete, success: false}
    await RootTrackingDownload.on_download_all()
    assert.deepStrictEqual(requests[0].file_pairs, [pair])
    assert.deepStrictEqual(downloads, ['RootDetector-tracking-results.zip'])
}

async function test_archive_generation_is_awaited(){
    await download_root_zip('RootDetector-detection-results.zip', {
        'first.tif/statistics.csv': Promise.resolve('one row'),
    })
    assert.deepStrictEqual(archiveEntries, [['first.tif/statistics.csv', 'one row']])
    assert.deepStrictEqual(blobs, [['RootDetector-detection-results.zip', 'archive-bytes']])
}

Promise.resolve()
    .then(test_failed_rerun_cannot_export_stale_result)
    .then(test_review_required_result_remains_available)
    .then(test_only_valid_results_are_compiled)
    .then(test_archive_generation_is_awaited)
    .then(() => console.log('Tracking export-state tests passed.'))
    .catch(error => {console.error(error); process.exitCode = 1})
