/* Real WebGL/browser regressions. Install playwright and run with the server up:
   node tests/browser_recovery.cjs http://127.0.0.1:5042 [report-directory]
   Set MOPAC_BROWSER to an existing Chrome/Edge executable if needed. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const baseURL = process.argv[2] || 'http://127.0.0.1:5042';
const reportDir = process.argv[3];
const tests = [];
let browser;

(async () => {
  browser = await chromium.launch({ headless: true,
    ...(process.env.MOPAC_BROWSER ? { executablePath: process.env.MOPAC_BROWSER } : {}),
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(baseURL);
  await page.waitForFunction(() => viewer && window.MopacEditor?.init && document.querySelector('#calcGrid input'));
  const graph = () => page.evaluate(() => JSON.parse(JSON.stringify(MopacEditor.molecule)));
  const read = () => page.evaluate(() => ({ active: MopacEditor.active,
    current: currentMol, selected: MopacEditor.selected, history: MopacEditor.history,
    view: viewer.getView(), rendered: viewer.getModel()?.selectedAtoms({}).length || 0,
    calcDisabled: document.getElementById('calcBtn').disabled,
    pending: !!MopacEditor.pendingRequest }));
  const done = async (name, fn) => { await fn(); tests.push({ name, passed: true }); console.log('PASS', name); };
  const requestURL = '**/api/structure/editor';
  const fail = route => route.fulfill({ status: 422, contentType: 'application/json',
    body: JSON.stringify({ ok: false, code: 'optimization_failed', recoverable: true,
      error: 'MMFF/UFF 최적화 실패: bad direction in linearSearch. 현재 좌표는 유지됩니다.' }) });
  const idle = () => page.waitForFunction(() => !MopacEditor.pendingRequest);
  const changedReply = async payload => {
    const response = await page.request.post(baseURL + '/api/structure/editor', { data: { mol: payload, relax: false } });
    const result = await response.json();
    assert(result.ok);
    result.mol.atoms[0].x = 123;
    return result;
  };

  await done('Free placement, explicit bonds, coordinate editing and WebGL model', async () => {
    await page.click('#edit3DBtn');
    await page.click('#viewer', { position: { x: 220, y: 260 } });
    await page.click('#viewer', { position: { x: 330, y: 330 } });
    assert.equal((await graph()).atoms.length, 2);
    await page.evaluate(() => {
      document.querySelector('[data-edit-mode="bond"]').click();
      MopacEditor.onAtomClick(0); MopacEditor.onAtomClick(1);
    });
    await page.fill('#editorX', '2.123456789'); await page.locator('#editorX').press('Tab');
    assert.equal((await graph()).bonds.length, 1);
    assert.equal((await read()).rendered, 2);
  });
  await done('BFGS error leaves graph, coordinates, selection and undo intact', async () => {
    await page.route(requestURL, fail);
    const before = await graph(), state = await read();
    await page.click('#editorRelax'); await idle();
    assert.deepEqual(await graph(), before);
    assert.deepEqual((await read()).history, state.history);
    assert.equal((await read()).selected, state.selected);
    assert.equal((await read()).active, true);
    assert.match(await page.textContent('#toast'), /현재/);
    if (reportDir) { fs.mkdirSync(reportDir, { recursive: true }); await page.screenshot({ path: path.join(reportDir, 'error-preserved.png') }); }
  });
  await done('X preserves graph and camera; reopen restores graph and undo', async () => {
    const before = await graph(), state = await read();
    await page.click('#editorClose');
    const closed = await read();
    assert.equal(closed.active, false); assert.equal(closed.rendered, before.atoms.length);
    assert.deepEqual(closed.current.atoms, before.atoms); assert.deepEqual(closed.current.bonds, before.bonds);
    assert.equal(closed.calcDisabled, true);
    assert.deepEqual(closed.view, state.view);
    if (reportDir) await page.screenshot({ path: path.join(reportDir, 'closed-preserved.png') });
    await page.click('#edit3DBtn');
    assert.deepEqual((await graph()).atoms, before.atoms);
    assert.deepEqual((await graph()).bonds, before.bonds);
    assert.deepEqual((await read()).history, state.history);
    await page.click('#editorUndo');
    assert.notDeepEqual((await graph()).atoms, before.atoms);
    await page.unroute(requestURL, fail);
  });
  await done('Network failure, HTTP 404 and malformed response preserve graph', async () => {
    for (const handler of [r => r.abort('failed'),
      r => r.fulfill({ status: 404, body: 'Not found' }),
      r => r.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }),
      r => r.fulfill({ status: 500, contentType: 'text/html', body: '<html>error</html>' })]) {
      await page.route(requestURL, handler);
      const before = await graph(); await page.click('#editorApply'); await idle();
      assert.deepEqual(await graph(), before); assert((await read()).active);
      await page.unroute(requestURL, handler);
    }
  });
  await done('Closing and reopening during request ignores late success', async () => {
    const payload = await graph(), response = await changedReply(payload);
    let received; const arrived = new Promise(r => received = r);
    let release; const gate = new Promise(r => release = r);
    const handler = async route => { received(); await gate; await route.fulfill({ json: response }); };
    await page.route(requestURL, handler);
    await page.click('#editorRelax'); await arrived;
    await page.click('#editorClose'); await page.click('#edit3DBtn');
    const before = await graph();
    release(); await page.waitForResponse(r => r.url().endsWith('/api/structure/editor'));
    // Flush the fetch response handler before assertions.
    await page.waitForTimeout(100);
    assert.deepEqual(await graph(), before); assert((await read()).active);
    assert.notEqual((await graph()).atoms[0].x, 123);
    await page.unroute(requestURL, handler);
  });
  await done('Edits during request survive; repeated Apply/Relax cannot race', async () => {
    const response = await changedReply(await graph());
    let received; const arrived = new Promise(r => received = r);
    let release; const gate = new Promise(r => release = r); let requests = 0;
    const handler = async route => { requests++; received(); await gate; await route.fulfill({ json: response }); };
    await page.route(requestURL, handler);
    await page.click('#editorApply'); await arrived;
    assert(await page.isDisabled('#editorRelax')); assert(await page.isDisabled('#editorApply'));
    await page.click('#editorAdd'); const before = await graph();
    release(); await idle(); assert.equal(requests, 1);
    assert.deepEqual(await graph(), before); assert((await read()).active);
    await page.unroute(requestURL, handler);
  });
  await done('Close after editing an imported molecule keeps edits, not original', async () => {
    await page.click('#editorClose');
    await page.fill('#smilesInput', 'CO'); await page.click('#smilesBtn');
    await page.waitForFunction(() => !currentMol.editor_draft && currentMol.formula === 'CH4O');
    await page.click('#edit3DBtn'); await page.fill('#editorX', '4.25');
    await page.locator('#editorX').press('Tab');
    const before = await graph(); await page.click('#editorClose');
    assert.deepEqual((await read()).current.atoms, before.atoms);
    await page.click('#edit3DBtn'); assert.equal((await graph()).atoms[0].x, 4.25);
  });
  await done('Real MMFF/UFF relaxation and hydrogen apply remain functional', async () => {
    await page.click('#editorRelax'); await idle();
    assert((await read()).active);
    const before = await graph();
    assert.notEqual(before.atoms[0].x, 4.25);
    await page.click('#editorApply'); await idle();
    const state = await read(); assert.equal(state.active, false); assert.equal(state.calcDisabled, false);
    assert.equal(state.current.formula, 'CH4O'); assert.equal(state.current.atoms.length, 6);
    for (let i = 0; i < before.atoms.length; i++) {
      for (const k of ['x','y','z']) assert.equal(state.current.atoms[i][k], before.atoms[i][k]);
    }
  });
  await done('Calculation modal cancel, backdrop, result X retain current molecule', async () => {
    const before = (await read()).current;
    await page.click('#calcBtn'); await page.click('#cancelCalc');
    assert.deepEqual((await read()).current, before);
    await page.click('#calcBtn'); await page.locator('#calcModal').click({ position: { x: 4, y: 4 } });
    assert.deepEqual((await read()).current, before);
    await page.click('#toggleRight'); await page.click('#closeRight');
    assert.deepEqual((await read()).current, before);
  });
  await done('Hydrogen-only fallback warning is visible and input coordinates remain exact', async () => {
    await page.click('#edit3DBtn'); const before = await graph();
    const response = await changedReply(before);
    for(let i=0;i<before.atoms.length;i++)Object.assign(response.mol.atoms[i],before.atoms[i]);
    response.mol.warnings=['수소는 추가했지만 MMFF/UFF 보정은 완료되지 않았습니다. 입력한 원자 좌표는 유지됩니다.'];
    const handler=route=>route.fulfill({json:response});
    await page.route(requestURL,handler); await page.click('#editorApply'); await idle();
    assert.equal((await read()).active,false);
    assert.match(await page.textContent('#mol-info'),/보정은 완료되지/);
    for(let i=0;i<before.atoms.length;i++)for(const k of ['x','y','z'])
      assert.equal((await read()).current.atoms[i][k],before.atoms[i][k]);
    await page.unroute(requestURL,handler);
  });
  await done('XYZ coordinate-only imports retain existing bond inference', async () => {
    await page.evaluate(()=>renderMol({name:'XYZ import',atoms:[{symbol:'C',x:0,y:0,z:0},
      {symbol:'O',x:1.4,y:0,z:0}],bonds:[],charge:0,formula:'CO'}));
    await page.click('#edit3DBtn'); assert.equal((await graph()).bonds.length,1);
    await page.click('#editorClose');
  });
  await done('Close/reopen retains empty explicit bonds and standalone atoms', async () => {
    await page.click('#edit3DBtn'); await page.click('#editorClear');
    await page.click('#editorAdd'); await page.click('#editorAdd');
    await page.fill('#editorX', '.75'); await page.locator('#editorX').press('Tab');
    const before = await graph(); assert.equal(before.bonds.length, 0);
    await page.click('#editorClose'); assert.equal((await read()).rendered, 2);
    await page.click('#edit3DBtn'); assert.deepEqual((await graph()).bonds, []);
  });
  await done('Empty draft close/reopen and explicit H do not restore previous molecule', async () => {
    await page.click('#editorClear'); await page.click('#editorClose');
    assert.equal((await read()).current.atoms.length, 0); assert.equal((await read()).rendered, 0);
    await page.click('#edit3DBtn'); await page.selectOption('#editorElement', 'H'); await page.click('#editorAdd');
    const before = await graph(); await page.click('#editorClose'); await page.click('#edit3DBtn');
    assert.deepEqual((await graph()).atoms, before.atoms);
    assert.equal((await graph()).atoms[0].symbol, 'H');
  });
  await done('No uncaught browser errors', async () => assert.deepEqual(errors, []));
  if (reportDir) fs.writeFileSync(path.join(reportDir, 'browser-results.json'), JSON.stringify({ browser: await browser.version(), tests }, null, 2));
  console.log(`${tests.length} browser scenarios passed`);
  await browser.close();
})().catch(async error => { console.error(error); if (browser) await browser.close(); process.exit(1); });
