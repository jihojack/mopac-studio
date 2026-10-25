// Interactive 3D molecular editor. Uses the existing embedded 3Dmol viewer;
// no Avogadro window, downloads or additional browser libraries are needed.
"use strict";
(function () {
  const E = {
    active: false,
    selected: -1,
    bondStart: -1,
    mode: "add",
    suspendedMol: null,
    pendingRequest: null,
    molecule: null,
    history: [],
    maxUndo: 40,
    pointerDrag: null,
    pointerAction: null,
    dragFrame: 0,
  };
  const el = id => document.getElementById(id);
  const deepCopy = x => x == null ? x : JSON.parse(JSON.stringify(x));
  const elements = new Map(JSON.parse(el('editorElements').textContent).map(e=>[e.symbol,e]));
  // Keep established organic import behavior; use the shared covalent radii
  // for newly available elements instead of treating every metal as carbon.
  const radii = Object.assign(Object.fromEntries([...elements].map(([s,e])=>[s,e.radius])),
    { H:.31, B:.85, C:.76, N:.71, O:.66, F:.57, Si:1.11, P:1.07, S:1.05, Cl:1.02, Br:1.20, I:1.39 });
  function elementInfo(symbol) {
    const e=elements.get(symbol);
    return e ? `${e.symbol} · ${e.name} · 원자번호 ${e.number} · ` +
      (e.pm7?'기본 PM7 계산 지원':'표시·편집용 (기본 PM7 계산 미지원)') +
      (e.auto_h?'':' · 수소 자동 추가 제외') : '';
  }
  const modes = {
    add:"빈 3D 화면을 클릭하면 그 위치에 원자가 놓입니다. 결합은 '결합' 도구에서 별도로 연결하세요. 화면을 회전한 뒤 다른 깊이에도 배치할 수 있습니다.",
    bond:"결합할 원자 두 개를 차례로 클릭하세요. 원자는 먼저 자유롭게 배치해 두면 됩니다.",
    select:"원자를 드래그하면 좌표가 바뀝니다. Shift+드래그는 깊이 방향, 빈 공간 드래그는 회전입니다.",
    fragment:"원자를 드래그하면 연결된 분자 조각 전체가 이동합니다. 서로 결합하지 않은 분자 간 위치를 조절할 수 있습니다.",
    delete:"삭제할 원자를 클릭하세요. 연결된 결합도 함께 삭제됩니다."
  };
  function compactBond(b) {return {a:b.a,b:b.b,order:Math.round(Number(b.order)||1)};}
  const len = v => Math.hypot(v.x,v.y,v.z);
  const diff = (a,b) => ({x:a.x-b.x,y:a.y-b.y,z:a.z-b.z});
  const norm = v => {const n=len(v)||1;return {x:v.x/n,y:v.y/n,z:v.z/n};};
  function guessBonds(atoms) {
    // Imported XYZ/ARC files have only coordinates. Infer connectivity only;
    // double/triple bonds must be assigned explicitly by the user.
    const bonds=[];
    for (let i=0;i<atoms.length;i++) for (let j=i+1;j<atoms.length;j++) {
      const a=atoms[i],b=atoms[j];
      const r=(radii[a.symbol]||.7)+(radii[b.symbol]||.7);
      const d=len(diff(a,b));
      if(d>.4 && d < Math.min(2.35,1.22*r)) bonds.push({a:i,b:j,order:1});
    }
    return bonds;
  }
  function withoutHs(mol) {
    const atoms=mol.atoms||[];
    // Metal hydrides / pre-built complexes may contain intentional explicit H.
    // Retain all atoms when reopening these structures instead of deleting H
    // that the restricted auto-hydrogen rule cannot reconstruct.
    const retainHs=atoms.some(a=>!elements.get(a.symbol)?.auto_h);
    const included=atoms.map((a,i)=>retainHs || a.symbol!=="H"?i:-1).filter(i=>i>=0);
    // Hydrogen-only molecules are editable as well.
    if (!included.length) included.push(...atoms.map((_,i)=>i));
    const ids=new Map(included.map((i,ni)=>[i,ni]));
    const heavy=included.map(i=>({...atoms[i], formal_charge: Number(atoms[i].formal_charge)||0}));
    const hasExplicitBonds=Array.isArray(mol.bonds) &&
      (mol.bonds.length>0 || mol.editor_draft || mol.editor_source);
    const origBonds=hasExplicitBonds ? mol.bonds.filter(b=>ids.has(b.a)&&ids.has(b.b))
      .map(b=>({a:ids.get(b.a),b:ids.get(b.b),order:Math.round(b.order)})) : guessBonds(heavy);
    return {name:mol.name||"직접 그린 분자",atoms:heavy,bonds:origBonds,charge:mol.charge||0,formula:""};
  }
  function toMolBlock(mol) {
    const atoms=mol.atoms||[], bonds=mol.bonds||[];
    const pad=(v,n)=>String(v).padStart(n," ");
    const lines=[String(mol.name||"Drawn molecule").substring(0,80),"  MOPAC Studio 3D Editor","",
      `${pad(atoms.length,3)}${pad(bonds.length,3)}  0  0  0  0            999 V2000`];
    for(const a of atoms) lines.push(`${Number(a.x).toFixed(4).padStart(10)}${Number(a.y).toFixed(4).padStart(10)}${Number(a.z).toFixed(4).padStart(10)} ${String(a.symbol).padEnd(3)} 0  0  0  0  0  0  0  0  0  0  0  0`);
    for(const b of bonds) lines.push(`${pad(b.a+1,3)}${pad(b.b+1,3)}${pad(b.order,3)}  0  0  0  0`);
    const charged=atoms.map((a,i)=>[i+1,Number(a.formal_charge)||0]).filter(a=>a[1]);
    for(let start=0;start<charged.length;start+=8){
      const subset=charged.slice(start,start+8);
      lines.push("M  CHG"+pad(subset.length,3)+subset.map(p=>pad(p[0],4)+pad(p[1],4)).join(""));
    }
    lines.push("M  END","");
    return lines.join("\n");
  }
  function cache() {
    E.history.push({mol:deepCopy(E.molecule), selected:E.selected});
    if(E.history.length>E.maxUndo) E.history.shift();
  }
  function connectedComponents(mol){
    const adj=(mol.atoms||[]).map(()=>[]);
    for(const b of mol.bonds||[]){
      if(adj[b.a] && adj[b.b]){adj[b.a].push(b.b);adj[b.b].push(b.a);}
    }
    const seen=new Set(),parts=[];
    for(let i=0;i<adj.length;i++){
      if(seen.has(i))continue;
      const part=[],stack=[i];seen.add(i);
      while(stack.length){const u=stack.pop();part.push(u);
        for(const v of adj[u])if(!seen.has(v)){seen.add(v);stack.push(v);}
      }
      parts.push(part);
    }
    return parts;
  }
  function componentFor(i){return connectedComponents(E.molecule).find(p=>p.includes(i))||[i];}
  function fragmentDistanceSummary(mol){
    const parts=connectedComponents(mol);
    if(parts.length<2)return "한 개의 연결된 분자 조각";
    let best=Infinity,which=null;
    for(let i=0;i<parts.length;i++)for(let j=i+1;j<parts.length;j++){
      for(const k of parts[i])for(const l of parts[j]){
        const d=len(diff(mol.atoms[k],mol.atoms[l]));
        if(d<best){best=d;which=[k,l];}
      }
    }
    const pair=which?` · 최소 원자간 거리 ${best.toFixed(2)} Å (${which[0]+1}–${which[1]+1}번)`:"";
    return `독립 조각 ${parts.length}개${pair} · PM7 복합체 계산 가능 (상호작용 에너지는 별도 기준 계산 필요)`;
  }
  function updateSelection() {
    if(!E.active) return;
    const mol=E.molecule,a=mol.atoms[E.selected];
    el("editorSelectedLabel").textContent = a ? `선택: ${a.symbol}${E.selected+1}` : "원자를 선택하세요";
    el('editorSelectedElementInfo').textContent=a?elementInfo(a.symbol):'';
    const fragments=connectedComponents(mol).length;
    el("editorFragmentInfo").textContent=fragmentDistanceSummary(mol);
    el("editorAtomCount").textContent=`${mol.atoms.length} 원자 · ${mol.bonds.length} 결합 · 독립 조각 ${fragments}개`;
    ["editorAtomElement","editorFormalCharge","editorX","editorY","editorZ"].forEach(id=>el(id).disabled=!a);
    if(a){
      el("editorAtomElement").value=a.symbol;
      el("editorFormalCharge").value=a.formal_charge||0;
      for(const axis of "xyz") el("editor"+axis.toUpperCase()).value=String(a[axis]);
    }else{
      for(const axis of "xyz") el("editor"+axis.toUpperCase()).value="";
    }
    el("editorHint").textContent= E.bondStart>=0 && E.mode==="bond"
      ? `${E.bondStart+1}번 원자 선택됨 → 연결할 다른 원자를 클릭하세요.` : modes[E.mode];
    el("editorUndo").disabled=!E.history.length;
    document.querySelectorAll("[data-edit-mode]").forEach(b=>b.classList.toggle("active",b.dataset.editMode===E.mode));
  }
  function redraw(keep=true) {
    if(!E.active)return;
    E.molecule.name=(el("editorName").value.trim()||"직접 그린 분자");
    renderMol(E.molecule,{keepView:keep});
    updateSelection();
  }
  function onRender() {
    if(!E.active||!E.molecule.atoms.length) return;
    // Hit testing is handled at the pointer layer, so empty-canvas clicks work
    // and 3Dmol's own synthetic clicks cannot create duplicate atoms/bonds.
    viewer.setClickable({},false,()=>{});
    // Selected atom visual ring; bond picking start is tinted cyan.
    const mark = (i,color) => {
      const a=E.molecule.atoms[i];
      if(a) viewer.addSphere({center:{x:a.x,y:a.y,z:a.z},radius:.43,color,opacity:.32,wireframe:false});
    };
    mark(E.selected,"#ffd54a");
    if(E.mode==="bond" && E.bondStart!==E.selected) mark(E.bondStart,"#1ee9ee");
  }
  function setMode(mode){
    E.mode=mode;E.bondStart=-1;updateSelection();
  }
  function select(i) {E.selected=i;redraw();}
  function addAtom(xyz=null){
    if(E.molecule.atoms.length>=300){toast("300개 원자 제한에 도달했습니다.");return;}
    cache();
    const element=el("editorElement").value;
    let x=xyz?.x??0,y=xyz?.y??0,z=xyz?.z??0;
    if(!xyz && E.molecule.atoms.length){
      const prev=E.molecule.atoms[E.molecule.atoms.length-1];
      x=prev.x+2.2;y=prev.y;z=prev.z;
    }
    E.molecule.atoms.push({symbol:element,x,y,z,formal_charge:0});
    const added=E.molecule.atoms.length-1;
    E.selected=added;
    // Avoid auto-zooming to a single atom: that would make subsequent placement unusably tight.
    redraw(true);
  }
  function connectAtoms(i,j){
    if(i===j){toast("같은 원자끼리 결합할 수 없습니다.");return;}
    cache();const order=Number(el("editorOrder").value);
    const old=E.molecule.bonds.find(b=>(b.a===i&&b.b===j)||(b.a===j&&b.b===i));
    if(old)old.order=order;
    else E.molecule.bonds.push({a:i,b:j,order});
    E.bondStart=-1;E.selected=j;redraw();
  }
  function eraseAtom(i){
    cache();E.molecule.atoms.splice(i,1);
    E.molecule.bonds=E.molecule.bonds.filter(b=>b.a!==i&&b.b!==i).map(b=>({
      a:b.a>i?b.a-1:b.a,b:b.b>i?b.b-1:b.b,order:b.order}));
    E.selected=E.molecule.atoms.length?Math.min(i,E.molecule.atoms.length-1):-1;
    E.bondStart=-1;redraw();
  }
  function onAtomClick(i){
    if(!E.active)return;
    if(E.mode==="add")select(i);
    else if(E.mode==="delete")eraseAtom(i);
    else if(E.mode==="bond"){
      if(E.bondStart===-1){E.bondStart=i;E.selected=i;redraw();}
      else connectAtoms(E.bondStart,i);
    }
    else select(i);
  }
  function changeCoord(axis,val){
    const a=E.molecule.atoms[E.selected];if(!a)return;
    const n=Number(val);
    if(!Number.isFinite(n)||Math.abs(n)>10000){toast("유효한 좌표를 입력하세요.");updateSelection();return;}
    cache();a[axis]=n;redraw();
  }
  // 3Dmol's local build does not expose draggable atoms, but it does expose
  // modelToScreen(). We pick atom centers in screen-space and invert the local
  // projection numerically. This works at arbitrary camera orientations and
  // keeps dragged coordinates in the actual editor graph (not only the view).
  const dot=(a,b)=>a.reduce((sum,x,i)=>sum+x*b[i],0);
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const magnitude=v=>Math.hypot(...v);
  function screenJacobian(atom){
    if(!viewer?.modelToScreen) return null;
    const base=viewer.modelToScreen(atom),h=.02;
    const basis=["x","y","z"].map(axis=>{
      const p=viewer.modelToScreen({...atom,[axis]:atom[axis]+h});
      return [(p.x-base.x)/h,(p.y-base.y)/h];
    });
    return [[basis[0][0],basis[1][0],basis[2][0]],
            [basis[0][1],basis[1][1],basis[2][1]]];
  }
  function pickAtom(pageX,pageY){
    if(!E.active||!E.molecule.atoms.length) return -1;
    let found=-1,best=Infinity;
    const coords=viewer.modelToScreen(E.molecule.atoms);
    for(let i=0;i<coords.length;i++){
      const d=Math.hypot(coords[i].x-pageX,coords[i].y-pageY);
      // Atoms may be shown as small spheres or thin sticks. A fixed hit radius
      // remains easy to use even in the line rendering mode.
      if(d<23 && d<best){found=i;best=d;}
    }
    return found;
  }
  function axisDelta(atom,dx,dy,mode){
    const j=screenJacobian(atom);
    if(!j) return [0,0,0];
    const a=j[0],b=j[1];
    if(mode==="depth"){
      const n=cross(a,b),nn=magnitude(n),scale=Math.sqrt((dot(a,a)+dot(b,b))/2);
      if(nn<1e-8||scale<1e-6)return [0,0,0];
      // Vertical screen motion moves along the camera viewing direction.
      return n.map(v=>v/nn*(-dy/scale));
    }
    if(["x","y","z"].includes(mode)){
      const k={x:0,y:1,z:2}[mode],den=a[k]*a[k]+b[k]*b[k];
      if(den<1e-6)return [0,0,0];
      const move=(a[k]*dx+b[k]*dy)/den;
      return [0,1,2].map(i=>i===k?move:0);
    }
    // Pseudoinverse J^T (J J^T)^-1 : minimum-norm translation in
    // the local screen plane, so the cursor follows the chosen atom.
    const aa=dot(a,a),ab=dot(a,b),bb=dot(b,b),det=aa*bb-ab*ab;
    if(det<1e-8)return [0,0,0];
    const u=(bb*dx-ab*dy)/det,v=(aa*dy-ab*dx)/det;
    return a.map((x,i)=>x*u+b[i]*v);
  }
  function placeAtScreen(pageX,pageY){
    // Unproject a mouse point onto a camera-facing plane through the molecular
    // centroid. Depth offset is adjustable (Angstrom) for genuine 3D placement.
    const atoms=E.molecule.atoms;
    const center={x:0,y:0,z:0};
    if(atoms.length){for(const a of atoms)for(const k of "xyz")center[k]+=a[k]/atoms.length;}
    const jac=screenJacobian(center);
    if(!jac){toast("3D 뷰어를 초기화할 수 없습니다.");return null;}
    const normal=cross(jac[0],jac[1]),m=magnitude(normal);
    const depth=Number(el("editorPlaceDepth").value)||0;
    const xyz={...center};
    if(m>1e-9)for(const [i,k] of ["x","y","z"].entries())xyz[k]+=normal[i]/m*depth;
    const target={x:pageX,y:pageY};
    // Newton projection inversion on the local plane (works after rotation).
    for(let it=0;it<8;it++){
      const projected=viewer.modelToScreen(xyz);
      const dx=target.x-projected.x,dy=target.y-projected.y;
      if(!Number.isFinite(dx+dy)){toast("클릭 좌표를 계산하지 못했습니다.");return null;}
      if(Math.hypot(dx,dy)<.15)break;
      const delta=axisDelta(xyz,dx,dy,"screen");
      for(const [i,k] of ["x","y","z"].entries())xyz[k]+=Math.max(-12,Math.min(12,delta[i]));
    }
    if(Object.values(xyz).some(v=>!Number.isFinite(v)||Math.abs(v)>1000))return null;
    return xyz;
  }
  function placeAtomAtScreen(pageX,pageY){
    const xyz=placeAtScreen(pageX,pageY);if(xyz)addAtom(xyz);
  }
  function proposedPosition(d,e){
    const axis=e.shiftKey?"depth":el("editorDragAxis").value;
    const original=d.startAtom,position=deepCopy(d.previewAtom||original);
    const totalDx=e.pageX-d.startX,totalDy=e.pageY-d.startY;
    let delta;
    if(axis==="depth"){
      delta=axisDelta(original,totalDx,totalDy,"depth");
      position.x=original.x+delta[0];position.y=original.y+delta[1];position.z=original.z+delta[2];
    }else if(axis!=="screen"){
      delta=axisDelta(original,totalDx,totalDy,axis);
      position.x=original.x+delta[0];position.y=original.y+delta[1];position.z=original.z+delta[2];
    }else{
      // A few damped Newton steps handle perspective changes during a long drag.
      const initial=viewer.modelToScreen(original);
      const target={x:initial.x+totalDx,y:initial.y+totalDy};
      for(let k=0;k<4;k++){
        const projected=viewer.modelToScreen(position);
        const error=[target.x-projected.x,target.y-projected.y];
        if(magnitude(error)<.02)break;
        delta=axisDelta(position,error[0],error[1],"screen");
        for(const [i,key] of ["x","y","z"].entries()) position[key]+=Math.max(-3,Math.min(3,delta[i]));
      }
    }
    const moved=Math.hypot(position.x-original.x,position.y-original.y,position.z-original.z);
    if(!Number.isFinite(moved)||moved>100) return null;
    return position;
  }
  function paintDrag(){
    E.dragFrame=0;
    const d=E.pointerDrag;
    if(!d||!d.moved||!d.lastEvent)return;
    const next=proposedPosition(d,d.lastEvent);
    if(!next)return;
    const a=E.molecule.atoms[d.index];if(!a)return;
    const translation={};for(const k of "xyz")translation[k]=next[k]-d.startAtom[k];
    for(const i of d.indices){
      const item=E.molecule.atoms[i],start=d.startAtoms[i];
      if(item&&start)for(const k of "xyz")item[k]=Math.round((start[k]+translation[k])*10000)/10000;
    }
    d.previewAtom=deepCopy(a);
    // Keep zoom and molecule orientation while re-rendering bonds and atoms.
    redraw(true);
  }
  function onPointerDown(e){
    if(!E.active||!e.isPrimary||e.button!==0)return;
    const index=pickAtom(e.pageX,e.pageY);
    if(index<0 && E.mode!=="add")return; // Empty area retains camera orbit.
    if(index<0){
      // A normal short click places an atom; if dragged, 3Dmol rotates the camera.
      E.pointerAction={pointerId:e.pointerId,mode:E.mode,index:-1,x:e.pageX,y:e.pageY};
      return;
    }
    // Block 3Dmol's own mousedown, since we implement atom interactions.
    e.preventDefault();e.stopImmediatePropagation();
    const a=E.molecule.atoms[index];
    E.pointerAction={pointerId:e.pointerId,mode:E.mode,index,x:e.pageX,y:e.pageY};
    if(E.mode==="select" || E.mode==="fragment"){
      const indices=E.mode==="fragment"?componentFor(index):[index];
      const startAtoms={};for(const i of indices)startAtoms[i]=deepCopy(E.molecule.atoms[i]);
      E.pointerDrag={pointerId:e.pointerId,index,indices,startAtoms,startX:e.pageX,startY:e.pageY,
        startAtom:deepCopy(a),previewAtom:deepCopy(a),lastEvent:e,moved:false};
      el("viewer").classList.add("atom-dragging");
    }
    E.selected=index;updateSelection();
    try{el("viewer").setPointerCapture(e.pointerId);}catch(_){}
  }
  function blockViewerMouse(e){
    if(E.pointerDrag || (E.pointerAction && E.pointerAction.index>=0)){
      e.preventDefault();e.stopImmediatePropagation();
    }
  }
  function onPointerMove(e){
    const d=E.pointerDrag;
    if(!d){
      if(E.active&&(E.mode==="select"||E.mode==="fragment")&&e.target.closest?.("#viewer")){
        el("viewer").classList.toggle("atom-draggable",pickAtom(e.pageX,e.pageY)>=0);
      }
      return;
    }
    if(e.pointerId!==d.pointerId)return;
    e.preventDefault();e.stopImmediatePropagation();d.lastEvent=e;
    if(!d.moved && Math.hypot(e.pageX-d.startX,e.pageY-d.startY)>=3){cache();d.moved=true;}
    if(d.moved&&!E.dragFrame)E.dragFrame=requestAnimationFrame(paintDrag);
  }
  function finishPointer(e){
    const a=E.pointerAction;
    if(!a||e.pointerId!==a.pointerId)return;
    const d=E.pointerDrag;
    if(a.index>=0){e.preventDefault();e.stopImmediatePropagation();}
    if(E.dragFrame){cancelAnimationFrame(E.dragFrame);E.dragFrame=0;}
    if(d?.moved){d.lastEvent=e;paintDrag();}
    const moved=Math.hypot(e.pageX-a.x,e.pageY-a.y);
    E.pointerDrag=null;E.pointerAction=null;
    el("viewer").classList.remove("atom-dragging");
    try{el("viewer").releasePointerCapture(a.pointerId);}catch(_){}
    if(!d?.moved&&moved<7){
      if(a.mode==="add"&&a.index<0)placeAtomAtScreen(e.pageX,e.pageY);
      else if(a.index>=0)onAtomClick(a.index);
    }
    redraw(true);
    E.suppressClickUntil=Date.now()+300;
  }
  function cancelPointer(){
    const d=E.pointerDrag;
    if(E.dragFrame){cancelAnimationFrame(E.dragFrame);E.dragFrame=0;}
    if(d?.moved){
      for(const i of d.indices){const a=E.molecule.atoms[i];if(a)for(const k of "xyz")a[k]=d.startAtoms[i][k];}
      E.history.pop();
    }
    E.pointerDrag=null;E.pointerAction=null;
    el("viewer").classList.remove("atom-dragging");
    if(E.active)redraw(true);
  }
  function installDragging(){
    const viewport=el("viewer");
    viewport.addEventListener("pointerdown",onPointerDown,true);
    viewport.addEventListener("mousedown",blockViewerMouse,true);
    window.addEventListener("pointermove",onPointerMove,true);
    window.addEventListener("mousemove",blockViewerMouse,true);
    window.addEventListener("pointerup",finishPointer,true);
    window.addEventListener("pointercancel",cancelPointer,true);
    window.addEventListener("blur",cancelPointer);
    viewport.addEventListener("click",e=>{
      if(E.active&&Date.now()<(E.suppressClickUntil||0)){
        e.preventDefault();e.stopImmediatePropagation();
      }
    },true);
    document.addEventListener("keydown",e=>{
      if(!E.active||!(e.ctrlKey||e.metaKey)||e.key.toLowerCase()!=="z"||
        /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName||"")) return;
      e.preventDefault();el("editorUndo").click();
    });
  }
  function start(){
    if(E.active) return;
    const resume=currentMol && currentMol===E.suspendedMol;
    if(!resume){
      E.molecule=currentMol?(currentMol.editor_draft?deepCopy(currentMol):withoutHs(currentMol))
        :{name:"직접 그린 분자",atoms:[],bonds:[],charge:0,formula:""};
      E.selected=E.molecule.atoms.length?0:-1;
      E.history=[];E.mode="add";
    }
    E.suspendedMol=null;E.bondStart=-1;
    dipoleVec=null;showDipole=false;
    E.active=true;
    el("editorName").value=E.molecule.name;
    el("editorPanel").classList.add("open");
    el("center").classList.add("editor-active");
    el("edit3DBtn").textContent="3D 편집 중...";
    el("calcBtn").disabled=true;
    redraw(resume);toast(resume?"보존한 편집 구조를 이어서 편집합니다.":"빈 3D 화면을 클릭해 원자를 자유 배치한 뒤, 결합 도구로 연결하세요.",5000);
  }
  function setBusy(busy){
    el("editorRelax").disabled=busy;el("editorApply").disabled=busy;
  }
  function snapshot(){
    const mol=deepCopy(E.molecule);
    mol.name=el("editorName").value.trim()||"직접 그린 분자";
    return mol;
  }
  function stop(preserveDraft){
    if(E.pointerDrag || E.pointerAction) cancelPointer();
    E.pendingRequest=null;setBusy(false);
    if(preserveDraft){
      E.molecule=snapshot();
      E.molecule.editor_draft=true;
      E.molecule.formula="편집 초안";
      E.molecule.charge=E.molecule.atoms.reduce((s,a)=>s+(Number(a.formal_charge)||0),0);
    }
    E.active=false;
    el("editorPanel").classList.remove("open");
    el("center").classList.remove("editor-active");
    el("edit3DBtn").textContent="🧩 화면에서 3D 그리기";
    el("calcBtn").disabled=preserveDraft;
    if(preserveDraft){
      E.suspendedMol=E.molecule;
      renderMol(E.molecule,{keepView:true});
      toast("편집 구조와 좌표를 보존했습니다. 3D 그리기를 누르면 이어서 편집할 수 있습니다.",5000);
    }
  }
  async function prepare(relax){
    if(E.pendingRequest)return;
    if(!E.molecule.atoms.length){toast("먼저 원자를 추가하세요.");return;}
    const request={};E.pendingRequest=request;setBusy(true);
    toast(relax?"분자 구조 MMFF/UFF 최적화 중...":"원자가 검사 및 수소 배치 중...");
    const payload=snapshot();
    try{
      const resp=await postJSON("/api/structure/editor",{mol:payload,relax});
      // Closing/reopening or changing a draft must invalidate any older reply.
      if(!E.active || E.pendingRequest!==request)return;
      if(JSON.stringify(snapshot())!==JSON.stringify(payload)){
        toast("요청 중 편집 내용이 변경되어 결과를 적용하지 않았습니다. 현재 구조는 유지됩니다.",6000);return;
      }
      if(resp.status===404){
        toast("편집기 API(404): 이전 서버에 접속 중일 수 있습니다. 프로그램을 새 ZIP에서 다시 실행하고 새로 열린 주소를 사용하세요.",9500);
        return;
      }
      if(!resp.ok){toast("구조 오류: "+(resp.error||"변환 실패")+" 현재 편집 구조는 유지됩니다.",6500);return;}
      if(!Array.isArray(resp.mol?.atoms)||!resp.mol.atoms.length ||
        resp.mol.atoms.some(a=>![a.x,a.y,a.z].every(Number.isFinite))){
        throw new Error("유효한 3D 좌표가 없는 응답입니다. 현재 구조는 유지됩니다.");
      }
      if(relax){
        cache();E.molecule=withoutHs(resp.mol);
        E.selected=Math.min(E.selected,E.molecule.atoms.length-1);
        redraw();
        toast("구조 정리 완료. '수소 추가 → 계산에 적용'을 누르면 계산할 수 있습니다.",4500);
      }else{
        stop(false);dipoleVec=null;showDipole=false;
        el("chargeIn").value=resp.mol.charge;
        renderMol(resp.mol);
        toast(resp.mol.warnings?.length?resp.mol.warnings.join(" ")
          :`분자 생성 완료: ${resp.mol.atoms.length}개 원자 (수소 포함). 계산할 수 있습니다.`,resp.mol.warnings?.length?9500:4000);
      }
    }catch(err){if(E.active&&E.pendingRequest===request)toast("편집기 오류: "+err.message+" 현재 편집 구조는 유지됩니다.",6500);}
    finally{if(E.pendingRequest===request){E.pendingRequest=null;setBusy(false);}}
  }
  function init(){
    el('editorElement').onchange=()=>{el('editorElementInfo').textContent=elementInfo(el('editorElement').value);};
    el('editorElement').onchange();
    el("edit3DBtn").onclick=()=>E.active?toast("이미 3D 편집 중입니다."):start();
    el("editorClose").onclick=()=>stop(true);
    el("editorModes").addEventListener("click",e=>{const b=e.target.closest("[data-edit-mode]");if(b)setMode(b.dataset.editMode);});
    el("editorAdd").onclick=()=>addAtom();
    el("editorUndo").onclick=()=>{
      const h=E.history.pop();if(!h)return;
      E.molecule=h.mol;E.selected=h.selected;E.bondStart=-1;redraw();
    };
    el("editorClear").onclick=()=>{cache();E.molecule={name:el("editorName").value||"직접 그린 분자",atoms:[],bonds:[],charge:0,formula:""};E.selected=-1;E.bondStart=-1;redraw();};
    el("editorName").onchange=()=>{if(E.active)redraw();};
    el("editorAtomElement").onchange=()=>{
      const a=E.molecule.atoms[E.selected];if(!a)return;cache();a.symbol=el("editorAtomElement").value;redraw();
    };
    el("editorFormalCharge").onchange=()=>{
      const a=E.molecule.atoms[E.selected];if(!a)return;
      const val=Number(el("editorFormalCharge").value);
      if(!Number.isInteger(val)||Math.abs(val)>4){toast("형식전하는 -4~+4의 정수입니다.");updateSelection();return;}
      cache();a.formal_charge=val;redraw();
    };
    for(const axis of "xyz")el("editor"+axis.toUpperCase()).onchange=e=>changeCoord(axis,e.target.value);
    document.querySelectorAll("[data-nudge]").forEach(b=>b.onclick=()=>{
      const [axis,step]=b.dataset.nudge.split(":");const a=E.molecule.atoms[E.selected];
      if(a)changeCoord(axis,a[axis]+Number(step));
    });
    installDragging();
    el("editorApply").onclick=()=>prepare(false);
    el("editorRelax").onclick=()=>prepare(true);
    updateSelection();
  }
  window.MopacEditor=Object.assign(E,{init,onRender,onAtomClick,toMolBlock,placeAtomAtScreen,connectedComponents,fragmentDistanceSummary});
})();
