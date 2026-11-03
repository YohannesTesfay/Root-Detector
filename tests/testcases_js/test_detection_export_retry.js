const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const repo = path.resolve(__dirname, '..', '..')
const element = {
    find(){return this}, toggleClass(){return this}, prop(){return this},
    attr(){return this}, text(){return this}, toast(){return this},
}
const nodes = new Map()
const labels = []
const buttonSelector = '.tab[data-tab="detection"] .download-all'
const label = {...element, text(value){labels.push(value); return this}}
global.$ = selector => {
    if(!nodes.has(selector))
        nodes.set(selector, {
            ...element, find(child){return selector == buttonSelector && child == '.download-label' ? label : element},
            prop(name, value){this[name] = value; return this},
            text(value){this.content = value; return this},
            attr(name, value){
                if(value === undefined)
                    return name == 'data-tooltip-prefix' ? 'Download the last prepared ZIP again.' : this[name]
                this[name] = value
                return this
            },
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
let fail = false
const archive = (id, total) => ({id: id.repeat(32), state: 'ready', total, bytes: 91057,
    created_utc: '2026-11-03T09:48:44Z', download_name: `RootDetector-detection-results_2026-11-03_09-48-44Z_${id.repeat(8)}.zip`})
global.RootSecurity = {
    error_message: error => error.message,
    request: async (url, method, data) => {
        requests.push([url, method, data])
        if(method == 'POST' && fail)
            throw new Error('Test failure')
        if(method == 'POST')
            return {id: 'a'.repeat(32), state: 'preparing', processed: 0, total: 1}
        if(url.endsWith('/' + 'a'.repeat(32))) {
            pollCount++
            return {...archive('a', 1), processed: 1}
        }
        return {exports: [archive('b', 12)]}
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
        archive('a', 1).download_name,
        '/api/exports/detection/' + 'a'.repeat(32) + '/download',
    ])
    assert.strictEqual(nodes.get('#detection-export-retry').hidden, false)
    assert.match(nodes.get('#detection-export-details').content, /Prepared .+ · 1 image · .+ KB/)
    assert.strictEqual(nodes.get('#detection-export-retry').title, nodes.get('#detection-export-details').content)
    assert.match(nodes.get('#detection-export-retry').title, /^Download the last prepared ZIP again\.\nPrepared /)
    assert(!nodes.get('#detection-export-details').content.includes('Previous image selection'))
    assert.deepStrictEqual(labels, ['Preparing ZIP 0 of 1', 'Preparing ZIP 0 of 1', 'Download All'])
    RootDetectionDownload.on_retry_ready_export()
    assert.deepStrictEqual(downloads[1], downloads[0])
    await RootDetectionDownload.restore_recent_export()
    assert.match(nodes.get('#detection-export-details').content, /12 images.*Previous image selection/)
    RootDetectionDownload.on_retry_ready_export()
    assert.strictEqual(downloads[2][1], '/api/exports/detection/' + 'b'.repeat(32) + '/download')
    RootDetectionDownload.show_ready_archive(archive('c', 3))
    RootDetectionDownload.mark_archive_previous()
    assert.match(nodes.get('#detection-export-details').content, /Previous image selection/)
    fail = true
    await RootDetectionDownload.on_download_all()
    assert.strictEqual(labels[labels.length - 1], 'Download All')
    assert.strictEqual(nodes.get(buttonSelector).disabled, false)
    assert.strictEqual(RootDetectionDownload.ready_export.id, 'c'.repeat(32))
    console.log('Detection export retry tests passed.')
}

main().catch(error => {console.error(error); process.exitCode = 1})
