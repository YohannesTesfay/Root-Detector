const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const repo = path.resolve(__dirname, '..', '..')
let expanded = false
const previews = []
const downloads = []
const statuses = []
const element = {
    find: () => element,
    checkbox: option => option == 'is checked' ? false : element,
    toggleClass: () => element,
    hasClass: () => expanded,
    on: () => element,
    off: () => element,
}
const files = {}
const context = {
    BaseDetection: class {
        static hide_dimmer() {}
        static set_processing() {}
        static set_processed(name, clear) { statuses.push([name, clear]) }
        static set_failed() { throw new Error('A successful detection was marked failed') }
    },
    BaseDownload: class { static csv_data_for_file() { return 'statistics' } },
    RootsTraining: {forget_imported_label() {}},
    RootsFileInput: {ensure_uploaded: async () => {}},
    RootSecurity: {
        request: async (_url, method) => {
            assert.strictEqual(method, 'POST')
            return {
                segmentation: 'one.tiff.segmentation.png',
                skeleton: 'one.tiff.skeleton.png',
                statistics: {sum: 1, sum_negative: 2, sum_mask: 3,
                    sum_skeleton: 4, widths: [5, 6, 7], kimura_length: 8},
            }
        },
        report_client_error: async () => {throw new Error('No client error expected')},
    },
    GLOBAL: {files, event_source: {}, App: {
        ViewControls: {toggle_results() {}},
        Boxes: {refresh_boxes() {}},
        ImageLoading: {set_image_src: (_element, src) => previews.push(src)},
    }},
    $: () => element,
    is_string: value => typeof value == 'string',
    fetch_as_file: () => {throw new Error('Results must not be fetched eagerly')},
    fetch_as_blob: async url => {
        downloads.push(url)
        return {url}
    },
    url_for_image: name => '/images/' + name,
    console: {log() {}, error() {}},
}
vm.createContext(context)
vm.runInContext(fs.readFileSync(path.join(repo, 'frontend/roots/detection.js'), 'utf8'), context)
vm.runInContext(fs.readFileSync(path.join(repo, 'frontend/roots/download.js'), 'utf8'), context)

async function main(){
    for(let index = 0; index < 2000; index++){
        const name = `image-${index}.tiff`
        files[name] = {set_results(result){this.results = result}}
        await context.RootDetection.set_results(name, {
            segmentation: `${name}.segmentation.png`,
            skeleton: `${name}.skeleton.png`,
        })
    }
    assert.strictEqual(previews.length, 0, 'Collapsed batch must not fetch previews')
    assert.strictEqual(files['image-1999.tiff'].results.skeleton, 'image-1999.tiff.skeleton.png')
    assert.strictEqual(statuses.length, 2000)

    expanded = true
    context.RootDetection.show_result_preview('image-1999.tiff')
    assert.deepStrictEqual(previews, ['image-1999.tiff.segmentation.png'])
    await context.RootDetection.set_results('image-1999.tiff', undefined)
    assert.strictEqual(previews.at(-1), undefined, 'Clearing results must clear the old preview')

    files['one.tiff'] = {set_results(result){this.results = result}}
    expanded = false
    await context.RootDetection.process_image('one.tiff')
    assert.strictEqual(files['one.tiff'].results.segmentation, 'one.tiff.segmentation.png')
    const zipdata = context.RootDetectionDownload.zipdata_for_file('one.tiff')
    assert(zipdata['one.tiff.segmentation.png'])
    assert(zipdata['one.tiff.skeleton.png'])
    assert.strictEqual((await zipdata['one.tiff.segmentation.png']).url,
        '/images/one.tiff.segmentation.png')
    assert.strictEqual((await zipdata['one.tiff.skeleton.png']).url,
        '/images/one.tiff.skeleton.png')
    assert.deepStrictEqual(downloads, [
        '/images/one.tiff.segmentation.png', '/images/one.tiff.skeleton.png',
    ])
    console.log('Lazy detection preview tests passed.')
}

main().catch(error => {console.error(error); process.exitCode = 1})
