/* Drag-and-drop batches never replace currentMol, editor state or result cards. */
'use strict';
window.addEventListener('DOMContentLoaded', () => {
  const el = id => document.getElementById(id);
  const terminal = new Set(['completed', 'cancelled', 'error', 'interrupted']);
  const labels = {queued:'대기', running:'계산 중', ok:'완료', error:'실패', cancelled:'중단'};
  let files = [], job = null, submitting = false, timer = null, downloading = null;
  let autoDownload = false;
  const calcNames = {};
  const show = () => el('batchModal').classList.add('show');
  const busy = () => submitting || (job && !terminal.has(job.status));
  function remember(id) { try { id ? localStorage.setItem('mopacBatch', id) : localStorage.removeItem('mopacBatch'); } catch (_) {} }
  function errorText(error) { return error.message || String(error); }
  async function responseJSON(response) {
    let data;
    try { data = await response.json(); } catch (_) { throw new Error(`일괄 계산 API 응답 오류 (${response.status}). 프로그램을 최신 코드로 다시 실행하세요.`); }
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }
  function count() {
    const n = el('batchGrid').querySelectorAll('input:checked').length;
    el('batchCount').textContent = `${n}개 선택됨`;
  }
  function selected(incoming) {
    if (busy()) { show(); toast('일괄 계산이 진행 중입니다. 완료 후 새 파일을 선택하세요.'); return; }
    if (!incoming.length) return;
    if (incoming.length > 200 || incoming.some(f => f.size > 10000000) || incoming.reduce((s,f) => s+f.size,0) > 100000000) {
      show(); toast('최대 200개 파일, 파일당 10 MB, 전체 100 MB까지 지원합니다.',6000); return;
    }
    reset(); files = incoming;
    el('batchFileInfo').textContent = `${files.length}개 파일 · ${(files.reduce((s,f)=>s+f.size,0)/1000000).toFixed(2)} MB`;
    for (const file of files) {
      const li = document.createElement('li'); li.textContent = file.name; el('batchFileList').append(li);
    }
    show();
  }
  function reset() {
    clearTimeout(timer); files = []; job = null; remember(null); downloading = null;
    el('batchOptions').hidden = false; el('batchChoose').disabled = false;
    el('batchFileInfo').textContent = '선택한 파일이 없습니다.';
    el('batchFileList').replaceChildren(); el('batchProgress').hidden = true;
    el('batchSaved').hidden = true; el('batchNew').hidden = true; el('batchStop').hidden = true;
    el('batchRun').hidden = false; el('batchRun').disabled = false;
    el('batchHint').textContent = '완료 ZIP: workspace/exports'; el('batchBtn').textContent = '일괄 계산';
  }
  function render() {
    if (!job) return;
    const done = terminal.has(job.status);
    el('batchOptions').hidden = true; el('batchChoose').disabled = true;
    el('batchRun').hidden = true; el('batchProgress').hidden = false;
    el('batchStop').hidden = done; el('batchNew').hidden = !done;
    const current = job.current || '';
    const parts = current.split(' · ');
    if(calcNames[parts[parts.length-1]]) parts[parts.length-1]=calcNames[parts[parts.length-1]];
    el('batchMessage').textContent = parts.join(' · ');
    el('batchMeter').max = Math.max(job.total,1); el('batchMeter').value = job.completed;
    const entries = job.entries || [];
    const good = entries.filter(e=>e.status==='ok').length;
    const bad = entries.filter(e=>e.status==='error').length;
    el('batchSummary').textContent = `${entries.length}개 구조 · 완료 ${good} · 실패 ${bad} · 처리 ${job.completed}/${job.total}`;
    el('batchFileInfo').textContent = `일괄 계산 ${job.id.slice(0,8)}`;
    el('batchFileList').replaceChildren(); el('batchEntries').replaceChildren();
    for (const entry of entries) {
      const row = document.createElement('div'); row.className = 'batch-entry';
      const failures = entry.results.filter(r=>r.status==='error').flatMap(r=>r.errors||[]);
      row.textContent = `${entry.filename} · 구조 ${entry.record} · ${labels[entry.status] || entry.status}` +
        (entry.error || failures.length ? ` — ${entry.error || failures.join('; ')}` : '');
      el('batchEntries').append(row);
    }
    el('batchBtn').textContent = done ? '일괄 계산 결과' : `일괄 계산 ${job.completed}/${job.total}`;
    el('batchHint').textContent = done ? '완료된 결과와 입력 파일은 로컬 폴더에 저장됩니다.' : '창을 닫아도 계속 계산합니다. 앱은 계산 완료 후 종료하세요.';
    if (job.export) {
      el('batchDownload').hidden = false;
      el('batchSaved').hidden = false; el('batchSavedPath').textContent = job.export;
      el('batchDownload').href = '/api/files/download?path=' + encodeURIComponent(job.export);
      el('batchDownload').download = job.export.split(/[\\/]/).pop();
      if (done && autoDownload && downloading !== job.export) {
        downloading = job.export; el('batchDownload').click();
      }
    } else if (done) {
      el('batchSaved').hidden = false; el('batchSavedPath').textContent = job.directory || '';
      el('batchDownload').hidden = true;
    }
  }
  async function poll() {
    if (!job) return;
    const id = job.id;
    try {
      const data = await responseJSON(await fetch('/api/batch/'+id));
      if (job?.id !== id) return;
      job = data.job; render();
      if (terminal.has(job.status)) { refreshFiles(); return; }
    } catch (error) {
      el('batchMessage').textContent = `진행 상태 연결 실패: ${errorText(error)} 다시 확인하는 중…`;
      // A stale ID from another workspace is not an active calculation.
      if (errorText(error).includes('찾을 수 없습니다')) {
        job.status = 'interrupted'; job.current = errorText(error); render(); return;
      }
    }
    timer = setTimeout(poll,1500);
  }
  el('batchBtn').onclick = show;
  el('batchClose').onclick = () => el('batchModal').classList.remove('show');
  el('batchModal').onclick = event => { if(event.target===el('batchModal')) el('batchClose').click(); };
  el('batchChoose').onclick = () => el('batchFiles').click();
  el('batchFiles').onchange = event => { selected(Array.from(event.target.files)); event.target.value=''; };
  el('batchUseCharge').onchange = () => el('batchCharge').disabled = el('batchUseCharge').checked;
  el('batchNew').onclick = reset;
  for (const [id,checked] of [['batchAll',true],['batchNone',false]]) {
    el(id).onclick = () => { el('batchGrid').querySelectorAll('input').forEach(c=>c.checked=checked); count(); };
  }
  el('batchStop').onclick = async () => {
    el('batchStop').disabled = true;
    try {
      const data=await responseJSON(await fetch('/api/batch/'+job.id+'/cancel',{method:'POST'}));
      job=data.job; render();
    } catch(error) { toast(errorText(error),6000); }
    finally { el('batchStop').disabled=false; }
  };
  el('batchRun').onclick = async () => {
    if (busy()) return;
    if (!files.length) { toast('먼저 구조 파일을 선택하세요.'); return; }
    const keys = Array.from(el('batchGrid').querySelectorAll('input:checked'), c=>c.value);
    if (!keys.length) { toast('계산을 1개 이상 선택하세요.'); return; }
    const settings = {calc_keys:keys, charge:el('batchUseCharge').checked?null:Number(el('batchCharge').value),
      mult:Number(el('batchMult').value), eps:Number(el('batchEps').value)};
    if ((!el('batchUseCharge').checked && (!el('batchCharge').value || !Number.isInteger(settings.charge) || Math.abs(settings.charge)>100)) ||
        !el('batchMult').value || !Number.isInteger(settings.mult) || settings.mult<1 || settings.mult>5 ||
        !el('batchEps').value || !Number.isFinite(settings.eps) || settings.eps<1) {
      toast('전하·스핀다중도·용매 값을 확인하세요.'); return;
    }
    const form = new FormData(); form.append('options',JSON.stringify(settings));
    files.forEach(file=>form.append('files',file,file.name));
    submitting=true; el('batchRun').disabled=true; el('batchChoose').disabled=true;
    el('batchHint').textContent='파일 업로드 중…'; autoDownload=el('batchAutoDownload').checked;
    try {
      const data=await responseJSON(await fetch('/api/batch',{method:'POST',body:form}));
      job=data.job; remember(job.id); render(); poll();
    } catch(error) { toast(errorText(error),7000); el('batchHint').textContent=errorText(error); }
    finally { submitting=false; el('batchRun').disabled=false; el('batchChoose').disabled=!!job; }
  };
  el('batchFolder').onclick = () => window.MopacExports.openFolder(job.export || job.directory);
  const isFileDrag = event => Array.from(event.dataTransfer?.types || []).includes('Files');
  let depth=0;
  document.addEventListener('dragenter',event=>{ if(isFileDrag(event)){event.preventDefault();depth++;el('fileDropOverlay').hidden=false;} });
  document.addEventListener('dragover',event=>{ if(isFileDrag(event)){event.preventDefault();event.dataTransfer.dropEffect='copy';} });
  document.addEventListener('dragleave',event=>{ if(isFileDrag(event)&&--depth<=0){depth=0;el('fileDropOverlay').hidden=true;} });
  document.addEventListener('drop',event=>{
    if(!isFileDrag(event))return;
    event.preventDefault();depth=0;el('fileDropOverlay').hidden=true;
    selected(Array.from(event.dataTransfer.files));
  });
  window.addEventListener('blur',()=>{depth=0;el('fileDropOverlay').hidden=true;});
  window.addEventListener('beforeunload',event=>{if(busy()){event.preventDefault();event.returnValue='';}});
  fetch('/api/calc_types').then(response=>response.json()).then(types=>{
    for(const type of types) {
      calcNames[type.key]=type.label;
      const label=document.createElement('label');label.className='calc-opt';
      const check=document.createElement('input');check.type='checkbox';check.value=type.key;
      check.checked=type.key==='geometry';check.onchange=count;
      const span=document.createElement('span');const name=document.createElement('b');name.textContent=type.label;span.append(name);
      if(type.note){const note=document.createElement('div');note.className='note';note.textContent='⚠ '+type.note;span.append(note);}
      label.append(check,span);el('batchGrid').append(label);
    }
    count();
  }).catch(error=>{el('batchHint').textContent='계산 옵션을 읽을 수 없습니다: '+errorText(error);});
  try { const id=localStorage.getItem('mopacBatch'); if(id){job={id,status:'preparing',entries:[],completed:0,total:0};poll();} } catch(_) {}
});
