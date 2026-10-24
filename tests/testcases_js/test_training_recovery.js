const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const widget = {
    prop(){ return this }, attr(){ return this }, addClass(){ return this },
    removeClass(){ return this }, hide(){ return this }, show(){ return this },
    text(){ return this }, toast(){ return this }, modal(){ return this },
    progress(){ return this }, find(){ return this }, is(){ return true },
}
global.$ = () => widget
global.BaseTraining = class {}
global.GLOBAL = {
    files: {'image.png': {name: 'image.png'}},
    App: {Settings: {load_settings: async () => {}}},
}
global.sleep = async () => {}
global.RootsFileInput = {}
global.RootSecurity = {}
RootSecurity.error_message = error => error?.message ?? 'Training failed.'
global.crypto = require('crypto').webcrypto
vm.runInThisContext(fs.readFileSync(
    path.resolve(__dirname, '../../frontend/roots/training.js'), 'utf8',
), {filename: 'training.js'})
const options = {training_type: 'detection', epochs: 1, learning_rate: 0.001}
RootsTraining.get_training_options = () => options
RootsTraining.show_modal = () => {}
RootsTraining.update_model_info = () => {}

function deferred(){
    let resolve, reject
    const promise = new Promise((done, fail) => { resolve = done; reject = fail })
    return {promise, resolve, reject}
}

function reset(){
    RootsTraining.active_run_id = undefined
    RootsTraining.active_options = undefined
    RootsTraining.start_pending = false
    RootsTraining.cancel_requested = false
    RootsTraining.upload_request = undefined
    RootsTraining.pending_submission = undefined
    RootsTraining.training_states = {}
    RootsTraining.imported_labels = new Map([['image.png', {name: 'label.png'}]])
    RootsTraining.get_training_options = () => options
    GLOBAL.App.Settings.load_settings = async () => {}
}

async function cancelled_upload_never_creates_a_job(){
    reset()
    const uploaded = deferred()
    const began = deferred()
    let aborted = false
    let calls = 0
    RootsFileInput.ensure_uploaded = async (_file, config) => {
        calls += 1
        config.on_request({abort(){ aborted = true; uploaded.resolve() }})
        began.resolve()
        await uploaded.promise
        config.on_request(undefined)
    }
    RootSecurity.request = () => { throw new Error('No job should be created') }
    const starting = RootsTraining.on_start_training()
    await began.promise
    await RootsTraining.on_start_training() // A second click cannot start another upload.
    await RootsTraining.on_cancel_training()
    await starting
    assert(aborted)
    assert.strictEqual(calls, 1)
    assert.strictEqual(RootsTraining.training_states.detection, 'cancelled')
    assert.strictEqual(RootsTraining.start_pending, false)
}

async function cancellation_during_create_reaches_returned_job(){
    reset()
    const created = deferred()
    const began = deferred()
    const requests = []
    RootsFileInput.ensure_uploaded = async () => {}
    RootSecurity.request = async (url, method) => {
        requests.push([url, method])
        if(url == '/api/training/runs'){
            began.resolve()
            return created.promise
        }
        if(url.endsWith('/cancel')) return {}
        return {state: 'cancelled', progress: 0}
    }
    const starting = RootsTraining.on_start_training()
    await began.promise
    await RootsTraining.on_cancel_training()
    created.resolve({id: 'test-run'})
    await starting
    assert(requests.some(([url]) => url == '/api/training/runs/test-run/cancel'))
    assert.strictEqual(RootsTraining.training_states.detection, 'cancelled')
    assert.strictEqual(RootsTraining.active_run_id, undefined)
}

async function retry_after_lost_poll_reconnects_without_retraining(){
    reset()
    let creates = 0
    let polls = 0
    RootsFileInput.ensure_uploaded = async () => {}
    RootSecurity.request = async url => {
        if(url == '/api/training/runs'){
            creates += 1
            return {id: 'test-run'}
        }
        polls += 1
        if(polls == 1) throw new Error('Connection interrupted')
        return {state: 'completed', progress: 1}
    }
    const previous_error = console.error
    console.error = () => {} // Expected transient failure under test.
    try {
        await RootsTraining.on_start_training()
    } finally {
        console.error = previous_error
    }
    assert.strictEqual(RootsTraining.active_run_id, 'test-run')
    assert.strictEqual(RootsTraining.training_states.detection, 'running')
    RootsTraining.get_training_options = () => ({...options, training_type: 'exclusion_mask'})
    await RootsTraining.on_retry_training()
    assert.strictEqual(creates, 1)
    assert.strictEqual(polls, 2)
    assert.strictEqual(RootsTraining.training_states.detection, 'completed')
    assert.strictEqual(RootsTraining.active_run_id, undefined)
}

async function settings_refresh_failure_preserves_confirmed_completion(){
    reset()
    RootsTraining.get_training_options = () => options
    RootsFileInput.ensure_uploaded = async () => {}
    RootSecurity.request = async url => url == '/api/training/runs'
        ? {id: 'test-run'} : {state: 'completed', progress: 1}
    GLOBAL.App.Settings.load_settings = async () => { throw new Error('Offline') }
    const result = await RootsTraining.on_start_training()
    assert.strictEqual(result.state, 'completed')
    assert.strictEqual(RootsTraining.training_states.detection, 'completed')
}

async function lost_create_response_recovers_same_request(cancel){
    reset()
    const created = deferred()
    const began = deferred()
    let server_jobs = 0
    let submissions = 0
    let request_id
    let cancelled = false
    RootsFileInput.ensure_uploaded = async () => {}
    RootSecurity.request = async (url, _method, payload) => {
        if(url == '/api/training/runs'){
            submissions += 1
            if(!request_id){
                request_id = payload.request_id
                assert.match(request_id, /^[0-9a-f]{32}$/)
                server_jobs += 1
                began.resolve()
                return created.promise
            }
            assert.strictEqual(payload.request_id, request_id)
            return {id: 'server-run'}
        }
        if(url.endsWith('/cancel')){
            cancelled = true
            return {}
        }
        return {state: cancelled ? 'cancelled' : 'completed', progress: 1}
    }
    const previous_error = console.error
    console.error = () => {}
    try {
        const starting = RootsTraining.on_start_training()
        await began.promise
        if(cancel) await RootsTraining.on_cancel_training()
        created.reject(new Error('Create response lost'))
        await starting
        assert.strictEqual(RootsTraining.training_states.detection, 'unknown')
        assert.strictEqual(RootsTraining.pending_submission.request_id, request_id)
        await RootsTraining.on_start_training() // Unknown request blocks a fresh submission.
        await RootsTraining.on_retry_training()
    } finally {
        console.error = previous_error
    }
    assert.strictEqual(submissions, 2)
    assert.strictEqual(server_jobs, 1)
    assert.strictEqual(cancelled, cancel)
    assert.strictEqual(RootsTraining.training_states.detection, cancel ? 'cancelled' : 'completed')
    assert.strictEqual(RootsTraining.pending_submission, undefined)
}

cancelled_upload_never_creates_a_job()
    .then(cancellation_during_create_reaches_returned_job)
    .then(retry_after_lost_poll_reconnects_without_retraining)
    .then(settings_refresh_failure_preserves_confirmed_completion)
    .then(() => lost_create_response_recovers_same_request(false))
    .then(() => lost_create_response_recovers_same_request(true))
    .then(() => console.log('Training cancellation and reconnect tests passed.'))
    .catch(error => { console.error(error); process.exitCode = 1 })
