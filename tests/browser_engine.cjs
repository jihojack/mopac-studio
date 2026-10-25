/* Real-engine browser smoke test. Install the engine and start the app first.
   node tests/browser_engine.cjs http://127.0.0.1:5005 [screenshot-directory] */
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
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.argv[2]||'http://127.0.0.1:5005');
  await page.waitForFunction(()=>document.querySelector('#calcGrid input'));
  await page.fill('#smilesInput','O');await page.click('#smilesBtn');
  await page.waitForFunction(()=>currentMol?.atoms?.length===3);
  await page.click('#calcBtn');
  for(const key of ['geometry','dipole','molecular_orbitals','vibrations'])
    await page.locator(`#calcGrid input[value="${key}"]`).check();
  await page.click('#runCalc');
  await page.waitForFunction(()=>document.querySelectorAll('#results .badge.ok').length===4,{},{timeout:120000});
  assert.equal(await page.locator('#results .badge.err').count(),0);
  console.log('PASS real engine: geometry, dipole, molecular orbitals and vibrations through UI');
  for(const tag of ['HOMO','LUMO']){
    await page.locator('.orb-btn').filter({has:page.locator('b',{hasText:new RegExp('^'+tag+'$')})}).click();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('오비탈 표시 완료'));
    assert.equal(await page.evaluate(()=>currentMol.atoms.length),3);
    if(process.argv[3]){
      fs.mkdirSync(process.argv[3],{recursive:true});
      await page.screenshot({path:path.join(process.argv[3],tag+'.png')});
    }
    console.log('PASS real '+tag+' isosurface from the newly calculated MGF');
  }
  assert.deepEqual(errors,[]);
  console.log('PASS no uncaught browser errors');
  await browser.close();
})().catch(async e=>{console.error(e);if(browser)await browser.close();process.exit(1)});
