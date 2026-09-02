const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')


const repository = path.resolve(__dirname, '..', '..')
global.$ = {
    get: async () => ({}),
    ajax: () => ({}),
}
global.BaseFileInput = class {}
global.sleep = async () => {}
global.upload_file_to_flask = undefined

vm.runInThisContext(
    fs.readFileSync(path.join(repository, 'frontend/roots/security.js'), 'utf8'),
    {filename: 'security.js'},
)
vm.runInThisContext(
    fs.readFileSync(path.join(repository, 'frontend/roots/file_input.js'), 'utf8'),
    {filename: 'file_input.js'},
)


async function test_error_normalization(){
    assert.strictEqual(
        RootSecurity.error_message({responseJSON: {message: 'Structured failure'}}),
        'Structured failure',
    )
    assert.match(
        RootSecurity.error_message({status: 0}),
        /connection to the local RootDetector process was interrupted/i,
    )
    assert.notStrictEqual(
        RootSecurity.error_message({message: '[object Object]'}),
        '[object Object]',
    )
}


async function test_item_71_resume(){
    RootsFileInput.reset_uploaded_files()
    const files = Array.from({length: 86}, (_value, index) => ({
        name: `image-${String(index + 1).padStart(2, '0')}.tiff`,
        size: 1000 + index,
        lastModified: 1234,
        type: 'image/tiff',
    }))
    const attempts = new Map()
    let fail_item_71 = true
    global.upload_file_to_flask = file => {
        const attempt = (attempts.get(file.name) ?? 0) + 1
        attempts.set(file.name, attempt)
        if(file == files[70] && fail_item_71)
            return Promise.reject({status: 0})
        return Promise.resolve({files: [{name: file.name}]})
    }

    for(const file of files.slice(0, 70))
        await RootsFileInput.ensure_uploaded(file)
    await assert.rejects(
        RootsFileInput.ensure_uploaded(files[70], {max_attempts: 3}),
    )
    assert.strictEqual(attempts.get(files[70].name), 3)

    fail_item_71 = false
    for(const file of files)
        await RootsFileInput.ensure_uploaded(file)

    for(const file of files.slice(0, 70))
        assert.strictEqual(attempts.get(file.name), 1)
    assert.strictEqual(attempts.get(files[70].name), 4)
    assert.strictEqual(attempts.get(files[85].name), 1)
}


Promise.resolve()
    .then(test_error_normalization)
    .then(test_item_71_resume)
    .then(() => console.log('Browser-side upload reliability tests passed.'))
    .catch(error => {
        console.error(error)
        process.exitCode = 1
    })
