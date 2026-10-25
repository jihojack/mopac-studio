"use strict";
(function(){
  const byId=id=>document.getElementById(id);
  let lastPath=null;
  function currentStructure(){
    const editor=window.MopacEditor;
    const mol=JSON.parse(JSON.stringify(editor?.active?editor.molecule:currentMol));
    if(mol&&editor?.active){
      mol.name=byId('editorName').value.trim()||'직접 그린 분자';
      mol.editor_draft=true;
      mol.formula='편집 초안';
      mol.charge=mol.atoms.reduce((s,a)=>s+(Number(a.formal_charge)||0),0);
    }
    return mol;
  }
  async function openFolder(path=null){
    try{
      const response=await postJSON('/api/files/open-folder',path?{path}:{});
      if(!response.ok)toast('폴더 열기 오류: '+response.error,5000);
    }catch(error){toast('폴더를 열지 못했습니다: '+error.message,5000);}
  }
  function image(){
    viewer.render();
    if(typeof viewer.pngURI==='function')return viewer.pngURI();
    return document.querySelector('#viewer canvas').toDataURL('image/png');
  }
  function show(){
    const mol=currentStructure();
    if(!mol?.atoms?.length){toast('먼저 분자를 만들거나 불러오세요.');return;}
    byId('exportInfo').textContent=`${mol.name||'molecule'} · ${mol.atoms.length}개 원자 · 표시된 계산 결과 ${lastResults.length}개`+
      (mol.editor_draft?' · 미검증 편집 초안':'');
    byId('exportResults').disabled=!lastResults.length;
    byId('exportResults').checked=!!lastResults.length;
    byId('exportModal').classList.add('show');
  }
  async function save(){
    const button=byId('exportSave');button.disabled=true;
    try{
      const format=byId('exportFormat').value;
      const payload={format,structure:currentStructure(),
        results:byId('exportResults').checked?lastResults:[],
        include_raw:byId('exportRaw').checked,
        visualization:{style:currentStyle,labels:showLabels,dipole:showDipole,
          camera:viewer.getView(),orbitalSource:currentMol?.orbitalSource||null,
          orbitalIndex:currentMol?.orbitalIndex??null,orbitalLabel:currentMol?.orbitalLabel||null,
          orbitalIsovalue:currentMol?.orbitalIsovalue??null}};
      if(format==='zip'||format==='png')payload.image=image();
      const response=await postJSON('/api/export',payload);
      if(!response.ok){toast('내보내기 오류: '+response.error,6500);return;}
      lastPath=response.path;
      byId('exportPath').textContent=response.path;
      byId('exportSaved').hidden=false;
      byId('exportDownload').href='/api/files/download?path='+encodeURIComponent(response.path);
      byId('exportDownload').download=response.filename;
      refreshFiles();toast('내보내기 파일을 저장했습니다.',4000);
    }catch(error){toast('내보내기 오류: '+error.message,6500);}
    finally{button.disabled=false;}
  }
  window.MopacExports={currentStructure,openFolder,show,save};
  window.addEventListener('DOMContentLoaded',()=>{
    byId('exportBtn').onclick=show;
    byId('openWorkspace').onclick=()=>openFolder();
    byId('exportClose').onclick=()=>byId('exportModal').classList.remove('show');
    byId('exportSave').onclick=save;
    byId('exportOpenFolder').onclick=()=>openFolder(lastPath);
    byId('exportModal').onclick=e=>{if(e.target.id==='exportModal')byId('exportClose').click();};
    document.addEventListener('keydown',e=>{if(e.key==='Escape')byId('exportClose').click();});
  });
})();
