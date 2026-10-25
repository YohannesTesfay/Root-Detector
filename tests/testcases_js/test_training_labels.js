const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const repository = path.resolve(__dirname, '..', '..')
let confirmed = false
const controls = {}
global.$ = selector => ({
    prop(name, value){
        if(value !== undefined) controls[selector + ':' + name] = value
        return this
    },
    attr(){ return this },
    text(){ return this },
    removeClass(){ return this },
    toast(){ return this },
    is(){ return confirmed },
})
global.BaseTraining = class {}
global.GLOBAL = {files: {
    'first.tif': {name: 'first.tif', results: {segmentation: {name: 'prediction.png'}}},
    'second.tif': {name: 'second.tif', results: {segmentation: {name: 'prediction2.png'}}},
}}
const uploads = []
global.RootsFileInput = {
    ensure_uploaded: async file => { uploads.push(file.name) },
}
vm.runInThisContext(
    fs.readFileSync(path.join(repository, 'frontend/roots/training.js'), 'utf8'),
    {filename: 'training.js'},
)

async function test_reviewed_labels_only(){
    assert.deepStrictEqual(RootsTraining.get_selected_files(), [])
    const label = {name: 'first.tif.segmentation.png'}
    RootsTraining.register_imported_label('first.tif', label)
    assert.deepStrictEqual(RootsTraining.get_selected_files(), ['first.tif'])
    assert.strictEqual(controls['#start-training-button:disabled'], true)
    confirmed = true
    RootsTraining.update_number_of_training_files_info()
    assert.strictEqual(controls['#start-training-button:disabled'], false)
    await RootsTraining.upload_training_data(['first.tif'])
    assert.deepStrictEqual(uploads, ['first.tif', label.name])
    RootsTraining.forget_imported_label('first.tif')
    assert.deepStrictEqual(RootsTraining.get_selected_files(), [])
    RootsTraining.clear_imported_labels()
}

async function test_import_does_not_replace_existing_detection(){
    global.BaseFileInput = class {}
    global.File = class {
        constructor(_parts, name){ this.name = name }
    }
    vm.runInThisContext(
        fs.readFileSync(path.join(repository, 'frontend/roots/file_input.js'), 'utf8'),
        {filename: 'file_input.js'},
    )
    const previous = GLOBAL.files['first.tif'].results
    await RootsFileInput.load_result('first.tif', [{name: 'reviewed.png'}], {as_training_labels: true})
    assert.strictEqual(GLOBAL.files['first.tif'].results, previous)
    assert.match(RootsTraining.imported_labels.get('first.tif').name, /^training-label-.*\.png$/)
}

async function test_restored_prediction_is_not_a_training_label(){
    RootsTraining.clear_imported_labels()
    global.RootSecurity = {request: async () => ({segmentation: 'restored-prediction'})}
    RootsFileInput.ensure_uploaded = async () => ({})
    global.App = {Detection: {set_results: async (filename, result) => {
        GLOBAL.files[filename].results = result
    }}}
    await RootsFileInput.load_result('first.tif', [{name: 'first.tif.segmentation.png'}])
    assert.strictEqual(GLOBAL.files['first.tif'].results.segmentation, 'restored-prediction')
    assert.deepStrictEqual(RootsTraining.get_selected_files(), [])
    assert.strictEqual(await RootsFileInput.load_result('other.tif', [{name: 'other.png'}]), false)

    let shown_error
    RootsFileInput.show_file_error = error => { shown_error = error.message }
    await RootsFileInput.on_annotations_select({target: {
        files: [{name: 'RootDetector-detection-results.zip'}], value: 'selected',
    }})
    assert.match(shown_error, /not a detection-results ZIP/)
    assert.deepStrictEqual(RootsTraining.get_selected_files(), [])

    const original_loader = RootsFileInput.load_result_files
    const modes = []
    RootsFileInput.load_result_files = async (_files, options={}) => {
        modes.push(options.as_training_labels ?? false)
        return 1
    }
    await RootsFileInput.on_results_select({target: {files: [{name: 'results.zip'}], value: 'selected'}})
    await RootsFileInput.on_annotations_select({target: {files: [{name: 'reviewed.png'}], value: 'selected'}})
    assert.deepStrictEqual(modes, [false, true])
    RootsFileInput.load_result_files = original_loader
}

test_reviewed_labels_only()
    .then(test_import_does_not_replace_existing_detection)
    .then(test_restored_prediction_is_not_a_training_label)
    .then(() => console.log('Reviewed training label tests passed.'))
    .catch(error => { console.error(error); process.exitCode = 1 })
