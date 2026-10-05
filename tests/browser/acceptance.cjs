/* Live, rendered acceptance. Requires a dedicated disposable RootDetector server. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {chromium} = require('playwright');

const baseURL = process.env.ROOTDETECTOR_BROWSER_TEST_URL;
if (!baseURL || process.env.ROOTDETECTOR_BROWSER_TEST_ALLOW_CLEAR !== '1') {
    throw new Error('Set ROOTDETECTOR_BROWSER_TEST_URL and ROOTDETECTOR_BROWSER_TEST_ALLOW_CLEAR=1 for a dedicated test server. Tests clear its cache and temporarily change settings.');
}
const parsedURL = new URL(baseURL);
if (parsedURL.protocol !== 'http:' || !['localhost', '127.0.0.1', '[::1]'].includes(parsedURL.hostname)) {
    throw new Error('Use a loopback server or SSH tunnel for browser acceptance.');
}
const assets = path.resolve(__dirname, '../testcases/assets');
const artifacts = path.join(__dirname, 'artifacts');
const earlier = 'PD_T088_L004_17.10.18_140056_014_SS_crop.tiff';
const later = 'PD_T088_L004_13.11.18_091057_015_SS_crop.tiff';
const timeout = Number(process.env.ROOTDETECTOR_BROWSER_TEST_TIMEOUT_MS || 180000);

async function run() {
    await fs.mkdir(artifacts, {recursive: true});
    const browser = await chromium.launch({headless: process.env.HEADED !== '1'});
    const page = await browser.newPage({acceptDownloads: true, viewport: {width: 1440, height: 1000}});
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const failedResponses = [];
    page.on('response', response => {
        if (response.status() >= 400) failedResponses.push(`${response.status()} ${response.url()}`);
    });
    let savedSettings;
    try {
        await page.goto(baseURL);
        await page.waitForFunction(() => window.RootSecurity?.token && Array.isArray(window.GLOBAL?.available_models?.detection));
        savedSettings = await page.evaluate(() => structuredClone(GLOBAL.settings));
        const models = await page.evaluate(() => GLOBAL.available_models.detection.map(model => typeof model === 'string' ? model : model.name));
        assert(models.length >= 2, 'Install both released detection models for the model-switch case.');
        await page.evaluate(async () => {
            await RootSecurity.request('/settings', 'POST', {use_gpu: false, tracking_sampling_mode: 'legacy', tracking_exclusion_policy: 'first'});
            await RootsSettings.load_settings();
        });

        // Import existing predictions through the actual file input and re-export.
        await page.locator('#input_images').setInputFiles([path.join(assets, earlier), path.join(assets, later)]);
        await page.waitForFunction(() => Object.keys(GLOBAL.files).length === 2);
        await page.locator('#annotations-input').setInputFiles(path.join(assets, later + '.results.zip'));
        await waitDetection(page, later);
        const imported = await downloadDetection(page, later);
        await assertDetectionArchive(page, imported, later);
        await page.locator('#annotations-input').setInputFiles(path.join(assets, earlier.replace(/\.tiff$/, '.png')));
        await waitDetection(page, earlier);
        console.log('PASS imported ZIP/plain PNG masks and detection re-export');

        // Run inference via the rendered Process All button, then change model via Settings.
        await page.locator('#input_images').setInputFiles([path.join(assets, earlier), path.join(assets, later)]);
        await page.waitForFunction(() => Object.values(GLOBAL.files).length === 2 && Object.values(GLOBAL.files).every(file => !file.results));
        await selectDetectionModel(page, models[0]);
        await page.locator('.tab[data-tab="detection"] .process-all').click();
        await waitDetection(page, earlier);
        await waitDetection(page, later);
        const firstArchive = await downloadDetection(page, later);
        const first = await assertDetectionArchive(page, firstArchive, later);
        await selectDetectionModel(page, models[1]);
        const responsePromise = page.waitForResponse(response => response.url().includes('/process_image/') && response.request().method() === 'POST', {timeout});
        await page.locator('.tab[data-tab="detection"] .process-all').click();
        assert.equal((await responsePromise).status(), 200);
        await page.waitForFunction(() => !document.querySelector('.tab[data-tab="detection"] .process-all').style.display.includes('none'), null, {timeout});
        await waitDetection(page, later);
        const second = await assertDetectionArchive(page, await downloadDetection(page, later), later);
        assert.notEqual(first.segmentation, second.segmentation, 'Different released models should not reuse the same prediction for the fixture.');
        console.log('PASS rendered detection completion, model switch, and PNG/CSV export');

        // Restore the known working model before exercising actual chronological tracking.
        await selectDetectionModel(page, savedSettings.active_models.detection);
        await page.locator('.tabs.menu .item[data-tab="tracking"]').click();
        const title = page.locator(`#tracking-filetable tr.title[filename0="${earlier}"][filename1="${later}"]`);
        await title.click();
        await page.locator('.tab[data-tab="tracking"] .process-all').click();
        await page.waitForFunction(([a, b]) => GLOBAL.files[a]?.tracking_results?.[b]?.success === true, [earlier, later], {timeout});
        assert(Number(await title.locator('label').first().evaluate(element => getComputedStyle(element).fontWeight)) >= 600);
        const row = page.locator(`#tracking-filetable tr[filename="${earlier}.${later}"]`);
        const button = row.locator('a.download');
        assert(!(await button.getAttribute('class')).includes('disabled'));
        const pending = page.waitForEvent('download');
        await button.click();
        const download = await pending;
        assert.match(download.suggestedFilename(), /tracking.*\.zip$/);
        const trackingPath = path.join(artifacts, 'tracking.zip');
        await download.saveAs(trackingPath);
        const tracking = await readArchive(page, trackingPath);
        assert(tracking.names.some(name => name.endsWith('.growthmap.png')));
        const csvName = tracking.names.find(name => name.endsWith('.csv'));
        assert(csvName, 'Tracking archive must contain statistics.');
        assertCsv(tracking.text[csvName]);
        assert(tracking.names.some(name => name.endsWith('.json')));
        console.log('PASS chronological tracking completion, enabled download, and archive content');
        assert.deepEqual(errors, [], 'Unexpected browser JavaScript errors');
        assert.deepEqual(failedResponses, [], 'Unexpected failed HTTP requests');
        await page.screenshot({path: path.join(artifacts, 'completed.png'), fullPage: true});
    } catch (error) {
        await page.screenshot({path: path.join(artifacts, 'failure.png'), fullPage: true}).catch(() => {});
        throw error;
    } finally {
        await fs.writeFile(path.join(artifacts, 'browser-errors.json'), JSON.stringify({errors, failedResponses}, null, 2));
        if (savedSettings) {
            await page.evaluate(async settings => { await RootSecurity.request('/settings', 'POST', settings); }, savedSettings).catch(error => console.error('Could not restore test settings:', error.message));
        }
        await browser.close();
    }
}

async function waitDetection(page, name) {
    await page.waitForFunction(filename => Boolean(GLOBAL.files[filename]?.results?.skeleton && GLOBAL.files[filename]?.results?.segmentation), name, {timeout});
    const label = page.locator(`#filetable .title[filename="${name}"] label`).first();
    assert(Number(await label.evaluate(element => getComputedStyle(element).fontWeight)) >= 600);
}

async function selectDetectionModel(page, name) {
    await page.locator('#settings-button').click();
    await page.locator('#settings-dialog').waitFor({state: 'visible'});
    await page.locator('#settings-active-model').click();
    await page.locator('#settings-active-model .item').filter({hasText: name}).click();
    await page.locator('#settings-ok-button').click();
    await page.locator('#settings-dialog').waitFor({state: 'hidden'});
    const response = await page.request.get(new URL('/settings', baseURL).href);
    assert.equal((await response.json()).settings.active_models.detection, name);
}

async function downloadDetection(page, name) {
    const title = page.locator(`#filetable .title[filename="${name}"]`);
    if (!(await title.getAttribute('class')).includes('active')) await title.click();
    const pending = page.waitForEvent('download');
    await page.locator(`#filetable [filename="${name}"] a.download`).click();
    const download = await pending;
    assert.equal(download.suggestedFilename(), `${name}.detection-results.zip`);
    const destination = path.join(artifacts, `${name}.detection-results.zip`);
    await download.saveAs(destination);
    return destination;
}

async function readArchive(page, filename) {
    const bytes = [...await fs.readFile(filename)];
    return page.evaluate(async bytes => {
        const archive = await JSZip.loadAsync(new Uint8Array(bytes));
        const names = Object.keys(archive.files).filter(name => !archive.files[name].dir);
        const text = {};
        const png = {};
        for (const name of names) {
            if (name.endsWith('.csv') || name.endsWith('.json')) text[name] = await archive.file(name).async('string');
            if (name.endsWith('.png')) png[name] = await archive.file(name).async('base64');
        }
        return {names, text, png};
    }, bytes);
}

function assertCsv(text) {
    const rows = text.trim().split(/\r?\n/).map(line => line.replace(/;$/, '').split(',').map(value => value.trim()));
    assert(rows.length >= 2, 'CSV must contain headers and data.');
    assert(rows[0].length > 1);
    for (const row of rows.slice(1)) assert.equal(row.length, rows[0].length, 'CSV headers and values must align.');
}

async function assertDetectionArchive(page, filename, source) {
    const data = await readArchive(page, filename);
    const segmentation = data.png[`${source}.segmentation.png`];
    const skeleton = data.png[`${source}.skeleton.png`];
    for (const png of [segmentation, skeleton]) {
        assert(png, 'Detection archive must contain segmentation and skeleton.');
        assert.equal(Buffer.from(png, 'base64').subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    }
    assertCsv(data.text['statistics.csv']);
    return {segmentation, skeleton};
}

run().catch(error => { console.error(error); process.exitCode = 1; });
