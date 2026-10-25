/* node tests/browser_elements.cjs http://127.0.0.1:5050 [report-directory] */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
let browser;
(async()=>{
  browser=await chromium.launch({headless:true,
    ...(process.env.MOPAC_BROWSER?{executablePath:process.env.MOPAC_BROWSER}:{}),
    args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1440,height:960}});
  const base=process.argv[2]||'http://127.0.0.1:5050',reports=process.argv[3],errors=[],passed=[];
  page.on('pageerror',error=>errors.push(error.message));
  const done=name=>{passed.push(name);console.log('PASS '+name);};
  const graph=()=>page.evaluate(()=>JSON.parse(JSON.stringify(MopacEditor.molecule)));
  const idle=()=>page.waitForFunction(()=>!MopacEditor.pendingRequest);
  await page.goto(base);await page.waitForFunction(()=>window.MopacEditor&&viewer);
  for(const id of ['editorElement','editorAtomElement']) {
    assert.equal(await page.locator(`#${id} option`).count(),118);
    assert.match(await page.locator(`#${id} option[value="Fe"]`).textContent(),/철.*26/);
  }
  done('Both element selectors expose all 118 elements, including Fe with name and atomic number');
  await page.click('#edit3DBtn');await page.selectOption('#editorElement','Fe');
  assert.match(await page.locator('#editorElementInfo').textContent(),/PM7 계산 지원/);
  await page.click('#editorAdd');await page.fill('#editorX','3.123456789');await page.locator('#editorX').press('Tab');
  assert.equal((await graph()).atoms[0].symbol,'Fe');
  assert.equal(await page.locator('#editorAtomElement').inputValue(),'Fe');
  await page.selectOption('#editorAtomElement','Zn');assert.equal((await graph()).atoms[0].symbol,'Zn');
  await page.click('#editorUndo');assert.equal((await graph()).atoms[0].symbol,'Fe');
  done('Place Fe, edit precise coordinates, change to Zn and undo without losing coordinates');
  await page.fill('#editorFormalCharge','2');await page.locator('#editorFormalCharge').press('Tab');
  const before=await graph();await page.click('#editorClose');await page.click('#edit3DBtn');
  assert.deepEqual((await graph()).atoms,before.atoms);assert.deepEqual((await graph()).bonds,before.bonds);
  assert.equal((await graph()).charge,2);
  const saveResponse=page.waitForResponse(r=>r.url().endsWith('/api/export'));
  await page.click('#saveBtn');const saved=(await (await saveResponse).json());assert(saved.ok);
  const restored=(await (await page.request.post(base+'/api/files/load',{data:{path:saved.path}})).json()).mol;
  assert.deepEqual(restored.atoms,before.atoms);
  done('Fe charge and coordinates survive close/reopen and exact JSON save/restore');
  await page.click('#editorApply');await idle();
  const applied=await page.evaluate(()=>({mol:currentMol,atom:viewer.getModel().selectedAtoms({})[0],active:MopacEditor.active}));
  assert.equal(applied.active,false);assert.equal(applied.mol.atoms.length,1);assert.equal(applied.mol.atoms[0].symbol,'Fe');
  assert.equal(applied.mol.atoms[0].x,3.123456789);assert.equal(applied.mol.charge,2);assert(applied.atom.style.sphere);
  done('Apply retains isolated Fe, adds no unintended hydrogens and keeps it visibly rendered');
  await page.evaluate(()=>renderMol({name:'Metal hydride',atoms:[{symbol:'Fe',x:0,y:0,z:0},{symbol:'H',x:1.5,y:0,z:0}],bonds:[{a:0,b:1,order:1}]}));
  await page.click('#edit3DBtn');assert.deepEqual((await graph()).atoms.map(a=>a.symbol),['Fe','H']);
  done('Reopening a metal hydride preserves explicit H instead of removing it');
  await page.click('#editorClear');await page.selectOption('#editorElement','Og');await page.click('#editorAdd');
  assert.match(await page.locator('#editorElementInfo').textContent(),/계산 미지원/);
  await page.click('#editorApply');await idle();
  assert.equal(await page.evaluate(()=>currentMol.atoms[0].symbol),'Og');
  const denied=(await (await page.request.post(base+'/api/calculate_one',{data:{mol:await page.evaluate(()=>currentMol),calc_key:'dipole'}})).json());
  assert.equal(denied.result.status,'error');assert.match(denied.result.errors.join(' '),/PM6\/PM7/);
  done('Display-only element Og remains editable while unsupported calculations return a clear error');
  await page.click('#edit3DBtn');
  await page.evaluate(()=>{
    const data=JSON.parse(document.getElementById('editorElements').textContent);
    MopacEditor.molecule={name:'All elements',atoms:data.map((e,i)=>({symbol:e.symbol,x:(i%18)*3,y:Math.floor(i/18)*3,z:0})),bonds:[],editor_draft:true};
    MopacEditor.selected=25;renderMol(MopacEditor.molecule);MopacEditor.onRender();
  });
  assert.equal(await page.evaluate(()=>viewer.getModel().selectedAtoms({}).length),118);
  done('All 118 element symbols render in the actual WebGL editor');
  if(reports){fs.mkdirSync(reports,{recursive:true});await page.screenshot({path:path.join(reports,'elements.png')});}
  assert.deepEqual(errors,[]);done('No uncaught browser errors');
  if(reports)fs.writeFileSync(path.join(reports,'results.json'),JSON.stringify({passed},null,2));
  await browser.close();browser=null;
})().catch(async error=>{console.error(error);if(browser)await browser.close();process.exitCode=1;});
