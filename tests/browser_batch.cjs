/* Real UI drop -> options -> official engine -> downloadable ZIP. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
let browser;
(async()=>{
  browser=await chromium.launch({headless:true,
    ...(process.env.MOPAC_BROWSER?{executablePath:process.env.MOPAC_BROWSER}:{}),
    args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1440,height:960},acceptDownloads:true});
  const base=process.argv[2]||'http://127.0.0.1:5048', reports=process.argv[3];
  const errors=[],passed=[];
  page.on('pageerror',error=>errors.push(error.message));
  const done=name=>{passed.push(name);console.log('PASS '+name);};
  const graph=()=>page.evaluate(()=>JSON.parse(JSON.stringify({mol:MopacEditor.molecule,
    history:MopacEditor.history,view:viewer.getView(),current:currentMol,results:lastResults})));
  const water='3\nwater\nO 0 0 0\nH .9572 0 0\nH -.2399872 .927297 0\n';
  await page.goto(base);
  await page.waitForFunction(()=>document.querySelectorAll('#batchGrid input').length===22);
  await page.fill('#smilesInput','CCO');await page.click('#smilesBtn');
  await page.waitForFunction(()=>currentMol?.atoms.length===9);
  await page.click('#edit3DBtn');await page.fill('#editorX','3.123456789');await page.locator('#editorX').press('Tab');
  const before=await graph();
  await page.evaluate(water=>{
    const transfer=new DataTransfer();
    transfer.items.add(new File([water],'물.xyz'));
    transfer.items.add(new File([water],'물.xyz'));
    transfer.items.add(new File(['broken'],'bad.xyz'));
    document.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
  },water);
  assert(await page.locator('#batchModal').evaluate(el=>el.classList.contains('show')));
  assert.equal(await page.locator('#batchFileList li').count(),3);
  assert.deepEqual(await graph(),before);
  if(reports){fs.mkdirSync(reports,{recursive:true});await page.screenshot({path:path.join(reports,'batch-options.png')});}
  done('Multiple file drop opens batch options without changing the active draft');
  await page.click('#batchNone');await page.click('#batchRun');
  assert.match(await page.locator('#toast').textContent(),/1개 이상/);
  assert.equal(await page.locator('#batchProgress').isVisible(),false);
  await page.locator('#batchGrid input[value="geometry"]').check();
  await page.locator('#batchGrid input[value="dipole"]').check();
  done('Calculation selection is required and independent of the single-molecule dialog');
  const started=page.waitForResponse(r=>r.url().endsWith('/api/batch')&&r.request().method()==='POST');
  const downloadEvent=page.waitForEvent('download',{timeout:120000});
  await page.click('#batchRun');const job=(await (await started).json()).job;
  await page.click('#batchClose');assert.deepEqual(await graph(),before);
  const download=await downloadEvent;
  const bytes=fs.readFileSync(await download.path());assert.equal(bytes.subarray(0,2).toString(),'PK');
  await page.click('#batchBtn');await page.waitForFunction(()=>document.getElementById('batchSaved').hidden===false);
  const status=(await (await page.request.get(base+'/api/batch/'+job.id)).json()).job;
  assert.equal(status.status,'completed');assert.deepEqual(status.entries.map(e=>e.status),['ok','ok','error']);
  assert.equal(await page.locator('#batchEntries .batch-entry').count(),3);
  assert.match(await page.locator('#batchSummary').textContent(),/완료 2 · 실패 1/);
  assert.deepEqual(await graph(),before);assert(await page.evaluate(()=>MopacEditor.active));
  done('Real batch calculations continue with dialog closed and automatically download the ZIP');
  done('Duplicate filenames and malformed input retain separate success/failure entries');
  done('Batch completion preserves coordinates, camera, undo history and existing result cards');
  await page.reload();await page.waitForFunction(()=>document.getElementById('batchSaved').hidden===false);
  await page.click('#batchBtn');assert.match(await page.locator('#batchSummary').textContent(),/완료 2 · 실패 1/);
  done('Reload restores saved batch status and its download link');
  let opened;
  await page.route('**/api/files/open-folder',async route=>{opened=route.request().postDataJSON().path;await route.fulfill({json:{ok:true}});});
  await page.click('#batchFolder');assert.equal(opened,status.export);
  done('Result folder button targets the completed ZIP');
  const molecule=(await (await page.request.post(base+'/api/structure/smiles',{data:{smiles:'O'}})).json()).mol;
  const molExport=(await (await page.request.post(base+'/api/export',{data:{format:'mol',structure:molecule}})).json());
  const mol=await (await page.request.get(base+'/api/files/download?path='+encodeURIComponent(molExport.path))).text();
  await page.click('#batchNew');await page.locator('#batchFiles').setInputFiles({name:'pair.sdf',mimeType:'chemical/x-mdl-sdfile',buffer:Buffer.from(mol+'\n$$$$\n'+mol+'\n$$$$\n')});
  await page.uncheck('#batchAutoDownload');await page.click('#batchNone');await page.locator('#batchGrid input[value="geometry"]').check();
  await page.click('#batchRun');await page.waitForFunction(()=>document.getElementById('batchSaved').hidden===false,{},{timeout:120000});
  assert.match(await page.locator('#batchSummary').textContent(),/2개 구조 · 완료 2 · 실패 0/);
  done('File chooser accepts a multi-record SDF and calculates both structures');
  if(reports){fs.mkdirSync(reports,{recursive:true});await page.screenshot({path:path.join(reports,'batch-completed.png')});}
  assert.deepEqual(errors,[]);done('No uncaught browser errors');
  if(reports)fs.writeFileSync(path.join(reports,'results.json'),JSON.stringify({passed,job:status,downloadBytes:bytes.length},null,2));
  await browser.close();browser=null;
})().catch(async error=>{console.error(error);if(browser)await browser.close();process.exitCode=1;});
