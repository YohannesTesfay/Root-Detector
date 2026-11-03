const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const repo = path.resolve(__dirname, '..', '..')
const element = {
    find: () => element, toggleClass: () => element, prop: () => element,
    attr: () => element, text: () => element, toast: () => element,
    show: () => element, hide: () => element,
}
const nodes = new Map()
global.$ = selector => {
    if(!nodes.has(selector))
        nodes.set(selector, {
            ...element,
            prop(name, value){this[name] = value; return this},
            text(value){this.content = value; return this},
        })
    return nodes.get(selector)
}
global.BaseDownload = class {}
global.GLOBAL = {files: {
    'one.tiff': {name: 'one.tiff', results: {statistics: {
        sum: 1, sum_negative: 2, sum_mask: 3, sum_skeleton: 4,
        widths: [5, 6, 7], kimura_length: 8,
    }}},
}}
global.sleep = async () => {}
global.url_for_image = name => name
const downloads = []
global.downloadURI = (name, uri) => downloads.push([name, uri])
global.download_blob = () => {throw new Error('bulk export must not create a browser Blob')}
global.JSZip = class {constructor(){throw new Error('bulk export must not use JSZip')}}
const requests = []
let pollCount = 0
global.RootSecurity = {
    error_message: error => error.message,
    request: async (url, method, data) => {
        requests.push([url, method, data])
        if(method == 'POST')
            return {id: 'a'.repeat(32), state: 'preparing', processed: 0, total: 1}
        if(url.endsWith('/' + 'a'.repeat(32))) {
            pollCount++
            return {id: 'a'.repeat(32), state: 'ready', processed: 1, total: 1}
        }
        return {exports: [{id: 'b'.repeat(32), state: 'ready', processed: null, total: null}]}
    },
}

vm.runInThisContext(fs.readFileSync(path.join(repo, 'frontend/roots/download.js'), 'utf8'))

async function main(){
    await RootDetectionDownload.on_download_all()
    assert.strictEqual(requests[0][0], '/api/exports/detection')
    assert.strictEqual(requests[0][1], 'POST')
    assert.strictEqual(requests[0][2].files[0].filename, 'one.tiff')
    assert.strictEqual(requests[0][2].files[0].csv_row, 'one.tiff, 1, 2, 3, 4, 5, 6, 7, 8;\n')
    assert.strictEqual(pollCount, 1)
    assert.deepStrictEqual(downloads[0], [
        'RootDetector-detection-results.zip',
        '/api/exports/detection/' + 'a'.repeat(32) + '/download',
    ])
    assert.strictEqual(nodes.get('#detection-export-recovery').hidden, false)
    assert.strictEqual(nodes.get('#detection-export-recovery').open, false)
    assert.match(nodes.get('#detection-export-summary-detail').content, /Prepared archive/)
    assert.strictEqual(
        nodes.get('.detection-actions-menu .detection-batch-summary').content,
        'ZIP ready — check saved file.',
    )
    RootDetectionDownload.on_retry_ready_export()
    assert.deepStrictEqual(downloads[1], downloads[0])
    await RootDetectionDownload.restore_recent_export()
    assert.strictEqual(nodes.get('#detection-export-recovery').open, false)
    assert.match(nodes.get('#detection-export-summary-detail').content, /Previous prepared archive/)
    RootDetectionDownload.on_retry_ready_export()
    assert.strictEqual(downloads[2][1], '/api/exports/detection/' + 'b'.repeat(32) + '/download')
    RootDetectionDownload.show_ready_archive({id: 'c'.repeat(32), state: 'ready'})
    RootDetectionDownload.mark_archive_previous()
    assert.match(nodes.get('#detection-export-notice').content, /previous image selection/)
    console.log('Detection export retry tests passed.')
}

main().catch(error => {console.error(error); process.exitCode = 1})
