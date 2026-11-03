const assert = require('assert')
const fs = require('fs')
const vm = require('vm')
const context = {
    BaseDownload: class {static zipdata_for_files(){return {}}},
    GLOBAL: {files: {
        'failed.tif': {preparation: {output_name: 'failed.tif'}},
        'passed.tif': {results: {statistics: {sum: 7, widths: [1, 2, 3]}}},
    }},
}
vm.createContext(context)
vm.runInContext(fs.readFileSync('frontend/roots/download.js', 'utf8'), context)
const archive = context.RootDetectionDownload.zipdata_for_files(['failed.tif', 'passed.tif'])
assert(archive['statistics.csv'].startsWith('Filename,'))
assert(archive['statistics.csv'].includes('passed.tif'))
assert(!archive['statistics.csv'].includes('failed.tif'))
assert(!archive['preparation-manifest.json'])
assert.strictEqual(Object.keys(context.RootDetectionDownload.zipdata_for_files(['failed.tif'])).length, 0)
console.log('Partial detection export tests passed.')
