const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const repo = path.resolve(__dirname, '..', '..')
const files = {'one.tiff': {set_results(result){this.results = result}}}
const delays = []
const requests = []
const reported = []
const labels = []
const announcements = []
const progressItem = {show(){this.visible = true; return this}, hide(){this.visible = false; return this},
    prop(key, value){this[key] = value; return this}}
const label = {text(value){labels.push(value); return this}}
const icon = {addClass(){return this}, removeClass(){return this}}
const announcement = {text(value){announcements.push(value); return this}}
const button = {
    addClass(){return this}, removeClass(){return this}, hasClass(){return false},
    prop(key, value){this[key] = value; return this}, attr(){return this},
    find(selector){return selector == '.process-label' ? label : icon},
    siblings(selector){assert.strictEqual(selector, '.cancel-processing'); return progressItem},
}
const element = {on(){return this}, off(){return this}, toast(){return this}}
const context = {
    BaseDetection: class {
        static set_processing() {}
        static set_failed() {}
    },
    RootsFileInput: {ensure_uploaded: async () => {}},
    RootSecurity: {
        request: async () => {throw new Error('Request stub not set')},
        is_transient_request_error: error => error?.status == 0 || error?.status >= 500,
        report_client_error: async (_stage, _filename, error) => {
            reported.push(error)
            return {diagnostic_id: 'test-id'}
        },
        error_message: error => error?.message || 'Connection interrupted',
    },
    GLOBAL: {files, event_source: {}, cancel_requested: false},
    $: target => target === button ? button : target === progressItem ? progressItem :
        target === '#detection-action-announcement' ? announcement : element,
    sleep: async delay => {delays.push(delay)},
    console: {warn() {}, error() {}, log() {}},
}
vm.createContext(context)
vm.runInContext(fs.readFileSync(path.join(repo, 'frontend/roots/detection.js'), 'utf8'), context)
context.RootDetection.set_results = async (name, result) => {files[name].set_results(result)}

async function main(){
    let calls = 0
    context.RootSecurity.request = async () => {
        calls += 1
        requests.push(calls)
        if(calls < 3) throw {status: 0, message: 'Connection interrupted'}
        return {segmentation: 'one.tiff.segmentation.png'}
    }
    await context.RootDetection.process_image('one.tiff')
    assert.strictEqual(calls, 3)
    assert.deepStrictEqual(delays, [500, 1000])
    assert.strictEqual(reported.length, 0, 'Recovered transient errors must not become final failures')
    assert.strictEqual(files['one.tiff'].results.segmentation, 'one.tiff.segmentation.png')

    calls = 0
    delays.length = 0
    context.RootSecurity.request = async () => {calls += 1; throw {status: 415, message: 'Invalid image'}}
    await assert.rejects(context.RootDetection.process_image('one.tiff'), /Invalid image/)
    assert.strictEqual(calls, 1, 'Non-transient image errors must not be retried')
    assert.deepStrictEqual(delays, [])
    assert.strictEqual(reported.length, 1)

    calls = 0
    context.RootSecurity.request = async () => {calls += 1; throw {status: 0, message: 'Connection interrupted'}}
    await assert.rejects(context.RootDetection.process_image('one.tiff'), /Connection interrupted/)
    assert.strictEqual(calls, 3, 'Transient failures have a bounded retry count')
    assert.strictEqual(reported.length, 2)

    calls = 0
    context.RootSecurity.request = async () => {calls += 1; throw {status: 0, message: 'Connection interrupted'}}
    await assert.rejects(context.RootDetection.process_image('one.tiff', true, {is_cancelled: () => true}), /Connection interrupted/)
    assert.strictEqual(calls, 1, 'Cancellation must suppress further retries')

    files['two.tiff'] = {set_results(result){this.results = result}}
    files['three.tiff'] = {set_results(result){this.results = result}}
    context.RootDetection.process_image = async name => {
        if(name == 'two.tiff') throw new Error('Expected test failure')
    }
    const batch = await context.RootDetection.on_process_all({currentTarget: button})
    assert.strictEqual(batch.failed.length, 1)
    assert.deepStrictEqual(labels, ['Processing 0 of 3', 'Processing 1 of 3', 'Processing 2 of 3', 'Processing 3 of 3', 'Process All'])
    assert(announcements.includes('Finished: 3 of 3; 1 failed'))
    assert.strictEqual(button.disabled, false)
    assert.strictEqual(progressItem.visible, false)
    let processed = 0
    context.RootDetection.process_image = async () => {
        processed += 1
        assert.strictEqual(button.disabled, true)
        assert.strictEqual(progressItem.visible, true)
        context.RootDetection.on_cancel_processing({currentTarget: progressItem, target: {}})
        assert.strictEqual(progressItem.disabled, true)
    }
    const cancelled = await context.RootDetection.on_process_all({currentTarget: button})
    assert.strictEqual(cancelled.cancelled, true)
    assert.strictEqual(processed, 1)
    assert.strictEqual(labels[labels.length - 1], 'Process All')
    assert(announcements.includes('Stopped: 1 of 3'))
    console.log('Manual detection retry and batch progress tests passed.')
}

main().catch(error => {console.error(error); process.exitCode = 1})
