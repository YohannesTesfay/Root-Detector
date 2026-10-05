/* Opt-in crop, prepared ZIP, and original-coordinate mask roundtrip in a real browser. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {chromium} = require('playwright');
const {deflateSync} = require('node:zlib');
const baseURL = process.env.ROOTDETECTOR_BROWSER_TEST_URL;
if (!baseURL || process.env.ROOTDETECTOR_BROWSER_TEST_ALLOW_CLEAR !== '1') {
    throw new Error('Set ROOTDETECTOR_BROWSER_TEST_URL and ROOTDETECTOR_BROWSER_TEST_ALLOW_CLEAR=1 for a disposable server.');
}
if (!['localhost', '127.0.0.1', '[::1]'].includes(new URL(baseURL).hostname)) {
    throw new Error('Use a loopback server or SSH tunnel.');
}
const artifacts = path.join(__dirname, 'artifacts');

function rgbPNG(width, height, pixel) {
    const chunk = (type, data) => {
        const header = Buffer.alloc(4);
        header.writeUInt32BE(data.length);
        const content = Buffer.concat([Buffer.from(type), data]);
        let crc = 0xffffffff;
        for (const value of content) {
            crc ^= value;
            for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
        }
        const checksum = Buffer.alloc(4);
        checksum.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
        return Buffer.concat([header, content, checksum]);
    };
    const header = Buffer.alloc(13);
    header.writeUInt32BE(width, 0);
    header.writeUInt32BE(height, 4);
    header[8] = 8;
    header[9] = 2; // True RGB, without implicit browser-canvas alpha.
    const scanlines = Buffer.alloc((width * 3 + 1) * height);
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
        const offset = y * (width * 3 + 1) + 1 + x * 3;
        scanlines.set(pixel(x, y), offset);
    }
    return Buffer.concat([Buffer.from('89504e470d0a1a0a', 'hex'), chunk('IHDR', header), chunk('IDAT', deflateSync(scanlines)), chunk('IEND', Buffer.alloc(0))]);
}

async function run() {
    await fs.mkdir(artifacts, {recursive: true});
    const browser = await chromium.launch({headless: process.env.HEADED !== '1'});
    const page = await browser.newPage({acceptDownloads: true, viewport: {width: 1440, height: 1000}});
    page.setDefaultTimeout(20000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    let cropConfirmations = 0;
    page.on('dialog', async dialog => {
        if (dialog.message().startsWith('Crop training annotation')) cropConfirmations += 1;
        await dialog.accept();
    });
    const sourceName = 'TestTube_04.04.24_scan.png';
    try {
        await page.goto(baseURL);
        await page.waitForFunction(() => Array.isArray(GLOBAL.available_models?.detection));
        const source = rgbPNG(1400, 1400, x => x >= 300 && x < 330 ? [240, 224, 208] : [32, 48, 16]);
        const mask = rgbPNG(1400, 1400, x => x >= 300 && x < 330 ? [255, 255, 255] : [0, 0, 0]);
        const exclusion = rgbPNG(1400, 1400, x => x < 100 ? [255, 255, 255] : [0, 0, 0]);
        await page.locator('#preparation-input').setInputFiles({name: sourceName, mimeType: 'image/png', buffer: source});
        await page.locator('#preparation-fields').waitFor({state: 'visible'});
        for (const [key, value] of Object.entries({left: 10, top: 20, width: 1280, height: 1280})) {
            await page.locator(`#crop-${key}`).fill(String(value));
        }
        await page.locator('#preparation-apply').click();
        await page.locator('#preparation-download').waitFor({state: 'visible'});
        const pendingPrepared = page.waitForEvent('download');
        await page.locator('#preparation-download').click();
        const preparedDownload = await pendingPrepared;
        const preparedPath = path.join(artifacts, 'RootDetector-prepared-images.zip');
        await preparedDownload.saveAs(preparedPath);
        await page.locator('#preparation-dialog .actions button').filter({hasText: /Close|Cancel/}).click();
        await page.locator('#preparation-dialog').waitFor({state: 'hidden'});
        await page.locator('#prepared-import-input').setInputFiles(preparedPath);
        await page.waitForFunction(() => Object.values(GLOBAL.files).length === 1 && Object.values(GLOBAL.files)[0].preparation);
        const restored = await page.evaluate(() => Object.values(GLOBAL.files)[0].preparation);
        assert.deepEqual(restored.rectangle, {left: 10, top: 20, width: 1280, height: 1280});
        assert.equal(restored.source.source_name, sourceName);
        await page.locator('#input_masks').setInputFiles({name: sourceName, mimeType: 'image/png', buffer: exclusion});
        await page.waitForFunction(() => Object.values(GLOBAL.files)[0].prepared_companions?.some(record => record.kind === 'exclusion_mask'));
        await page.locator('#annotations-input').setInputFiles({name: sourceName, mimeType: 'image/png', buffer: mask});
        await page.waitForFunction(() => RootsTraining.imported_labels.size === 1);
        assert.equal(cropConfirmations, 1);
        const companion = await page.evaluate(() => Object.values(GLOBAL.files)[0].prepared_companions.find(record => record.kind === 'training_annotation'));
        assert.equal(companion.operation, 'pixel_preserving_crop');
        assert.equal(companion.user_confirmed_original_coordinates, true);
        assert.equal(companion.preparation_id, restored.preparation_id);
        assert.equal(await page.locator('#training-reviewed-labels-checkbox').isChecked(), false);
        const filename = restored.output_name;
        await page.locator(`#filetable .title[filename="${filename}"]`).click();
        const pendingResults = page.waitForEvent('download');
        await page.locator(`#filetable [filename="${filename}"] a.download`).click();
        const resultPath = path.join(artifacts, 'prepared-detection-results.zip');
        await (await pendingResults).saveAs(resultPath);

        // A fresh image set proves provenance and mask coordinates survive export/import.
        await page.locator('#prepared-import-input').setInputFiles(preparedPath);
        await page.waitForFunction(() => Object.values(GLOBAL.files).length === 1 && !Object.values(GLOBAL.files)[0].results);
        await page.locator('#annotations-input').setInputFiles(resultPath);
        await page.waitForFunction(() => RootsTraining.imported_labels.size === 1);
        const reopened = await page.evaluate(() => Object.values(GLOBAL.files)[0].prepared_companions.find(record => record.kind === 'training_annotation'));
        assert.equal(reopened.operation, companion.operation);
        assert.equal(reopened.source_mask_sha256, companion.source_mask_sha256);
        assert.equal(reopened.output_sha256, companion.output_sha256);
        assert.equal(cropConfirmations, 1, 'Already cropped mask should not be cropped a second time.');
        assert.equal(await page.locator('#training-reviewed-labels-checkbox').isChecked(), false);
        const freshDetection = page.waitForResponse(response => response.url().includes('/process_image/') && response.request().method() === 'POST');
        await page.locator('.tab[data-tab="detection"] .process-all').click();
        const freshResult = await (await freshDetection).json();
        assert.equal(freshResult.statistics.sum_mask, 90 * 1280, 'Restored exclusion mask must affect newly computed results.');
        await page.waitForFunction(() => Object.values(GLOBAL.files)[0].results?.statistics?.sum_mask === 90 * 1280);
        assert.deepEqual(errors, []);
        await page.screenshot({path: path.join(artifacts, 'preparation-completed.png'), fullPage: true});
        console.log('PASS crop preparation, prepared ZIP restore, original mask confirmation, result/provenance roundtrip, restored exclusion on fresh detection, and explicit training review');
    } catch (error) {
        await page.screenshot({path: path.join(artifacts, 'preparation-failure.png'), fullPage: true}).catch(() => {});
        throw error;
    } finally {
        await fs.writeFile(path.join(artifacts, 'preparation-browser-errors.json'), JSON.stringify(errors, null, 2));
        await browser.close();
    }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
