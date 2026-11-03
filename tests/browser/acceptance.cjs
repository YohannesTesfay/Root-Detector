/* Live, rendered acceptance. Requires a dedicated disposable RootDetector server. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
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
        await assertStartupContrast(browser);
        await assertCompactStickyControls(page);
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
        await page.locator('#results-input').setInputFiles(path.join(assets, later + '.results.zip'));
        await waitDetection(page, later);
        assert.equal(await page.evaluate(() => RootsTraining.imported_labels.size), 0, 'Restored predictions must not become training labels.');
        const imported = await downloadDetection(page, later);
        await assertDetectionArchive(page, imported, later);
        await assertBulkRecovery(page);
        await page.locator('#results-input').setInputFiles(path.join(assets, earlier.replace(/\.tiff$/, '.png')));
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
        await page.waitForFunction(() => !document.querySelector('.tab[data-tab="detection"] .process-all').disabled, null, {timeout});
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
    // Fomantic makes the modal visible before its entrance transition finishes.
    // Its onComplete then autofocuses the first field, which can close a dropdown
    // clicked too early. Wait for the real interactive state, not a fixed delay.
    await page.waitForFunction(() => {
        const dialog = document.querySelector('#settings-dialog');
        return dialog.classList.contains('active') && dialog.classList.contains('visible')
            && !dialog.classList.contains('animating');
    });
    const dropdown = page.locator('#settings-active-model');
    if (!(await dropdown.evaluate(element => element.classList.contains('active')))) {
        await dropdown.click();
    }
    await page.waitForFunction(() => {
        const dropdown = document.querySelector('#settings-active-model');
        const menu = dropdown.querySelector('.menu');
        return dropdown.classList.contains('active') && menu.classList.contains('visible')
            && !menu.classList.contains('animating');
    });
    const exactName = new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`);
    await dropdown.locator('.item').filter({hasText: exactName}).click();
    await page.waitForFunction(expected => {
        const dropdown = document.querySelector('#settings-active-model');
        return dropdown.querySelector('input').value === expected
            && !dropdown.classList.contains('active')
            && !dropdown.querySelector('.menu').classList.contains('animating');
    }, name);
    await page.locator('#settings-ok-button').click();
    await page.locator('#settings-dialog').waitFor({state: 'hidden'});
    const response = await page.request.get(new URL('/settings', baseURL).href);
    assert.equal((await response.json()).settings.active_models.detection, name);
}

async function assertStartupContrast(browser) {
    const python = process.platform === 'win32' ? 'python' : 'python3';
    const startupHTML = execFileSync(python, ['-c',
        'from desktop_main import status_page; print(status_page("Starting Root Detector", "Preparing the local analysis process."))'],
        {cwd: path.resolve(__dirname, '../..'), encoding: 'utf8'});
    const page = await browser.newPage();
    try {
        await page.setContent(startupHTML);
        for (const colorScheme of ['light', 'dark']) {
            await page.emulateMedia({colorScheme});
            const ratio = await page.evaluate(() => {
                const luminance = color => color.match(/\d+/g).slice(0, 3).map(value => {
                    const c = Number(value) / 255;
                    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
                }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
                const bg = luminance(getComputedStyle(document.documentElement).backgroundColor);
                const fg = luminance(getComputedStyle(document.querySelector('p')).color);
                return (Math.max(bg, fg) + 0.05) / (Math.min(bg, fg) + 0.05);
            });
            assert(ratio >= 7, `Startup text should have strong contrast in ${colorScheme}: ${ratio}`);
        }
    } finally {
        await page.close();
    }
}

async function assertCompactStickyControls(page) {
    for (const width of [1440, 390]) {
        await page.setViewportSize({width, height: 850});
        const geometry = await page.evaluate(async () => {
            const rect = selector => document.querySelector(selector).getBoundingClientRect();
            const tab = document.querySelector('[data-tab="detection"].tab.segment');
            const original = tab.style.minHeight;
            const workflowGap = rect('#main-container > .tabs.menu').top - rect('#workflow-guide').bottom;
            const actionGap = rect('.detection-actions-menu').top - rect('#image-preparation-tools').bottom;
            const buttonHeight = rect('.detection-actions-menu .process-all').height;
            try {
                tab.style.minHeight = '1600px';
                window.scrollTo(0, 500);
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                return {workflowGap, actionGap, buttonHeight, scrolled: window.scrollY,
                    top: rect('#root-top-menu').top,
                    tabsOffset: rect('#main-container > .tabs.menu').top - rect('#root-top-menu').bottom,
                    actionsOffset: rect('.detection-actions-menu').top - rect('#main-container > .tabs.menu').bottom};
            } finally {
                window.scrollTo(0, 0);
                tab.style.minHeight = original;
            }
        });
        assert(geometry.workflowGap <= 16 && geometry.actionGap <= 8 && geometry.buttonHeight <= 42,
            `Expected compact controls at ${width}px: ${JSON.stringify(geometry)}`);
        assert(geometry.scrolled > 0 && [geometry.top, geometry.tabsOffset, geometry.actionsOffset]
            .every(offset => Math.abs(offset) <= 2), `Sticky controls overlap or drift at ${width}px: ${JSON.stringify(geometry)}`);
    }
    await page.setViewportSize({width: 1440, height: 1000});
    console.log('PASS startup contrast and compact sticky controls at desktop and narrow widths');
}

async function assertBulkRecovery(page) {
    await page.setViewportSize({width: 390, height: 850});
    const toolbar = page.locator('.detection-actions-menu');
    const download = toolbar.getByRole('button', {name: 'Download All'});
    const before = await download.boundingBox();
    let allowRequest;
    const gate = new Promise(resolve => { allowRequest = resolve; });
    const endpoint = '**/api/exports/detection';
    const holdPreparation = async route => {
        if (route.request().method() === 'POST') await gate;
        await route.continue();
    };
    await page.route(endpoint, holdPreparation);
    try {
        const saved = page.waitForEvent('download');
        await download.click();
        const busy = toolbar.getByRole('button', {name: 'Preparing ZIP 0 of 1'});
        await busy.waitFor();
        assert(await busy.isDisabled());
        const during = await busy.boundingBox();
        assert.deepEqual(during, before, 'Download button should not move or resize while busy');
        allowRequest();
        const first = await saved;
        assert.match(first.suggestedFilename(), /^RootDetector-detection-results_\d{4}-\d\d-\d\d_\d\d-\d\d-\d\dZ_[a-f0-9]{8}\.zip$/);
        await download.waitFor();
        await page.reload();
        await page.locator('#file-import-menu').press('Enter');
        const retry = page.locator('#detection-export-retry');
        await retry.waitFor();
        assert.equal((await retry.innerText()).trim(), 'Download Last Detection ZIP');
        const tooltip = await retry.getAttribute('title');
        assert.match(tooltip, /without rerunning detection\.\nPrepared .+ · 1 image · .+Previous image selection/);
        assert.equal(await retry.getAttribute('aria-describedby'), 'detection-export-details');
        assert.equal(await page.locator('#detection-export-details').textContent(), tooltip);
        assert(!(await page.locator('#detection-export-details').isVisible()));
        const restore = await page.locator('#load-results-button').boundingBox();
        assert(Math.abs((await retry.boundingBox()).height - restore.height) <= 2, 'Recovery should fit one normal menu row');
        const retried = page.waitForEvent('download');
        await retry.press('Enter');
        const second = await retried;
        assert.equal(second.suggestedFilename(), first.suggestedFilename());
        assert.deepEqual(await fs.readFile(await second.path()), await fs.readFile(await first.path()));
    } finally {
        allowRequest();
        await page.unroute(endpoint, holdPreparation);
        await page.setViewportSize({width: 1440, height: 1000});
    }
    // Reload resets the in-memory selection, not the recoverable ZIP.
    await page.locator('#input_images').setInputFiles([path.join(assets, earlier), path.join(assets, later)]);
    await page.waitForFunction(() => Object.keys(GLOBAL.files).length === 2);
    await page.locator('#results-input').setInputFiles(path.join(assets, later + '.results.zip'));
    await waitDetection(page, later);
    console.log('PASS compact bulk export and keyboard ZIP recovery after reload');
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
