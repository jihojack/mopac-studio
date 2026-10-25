// MOPAC Studio 프론트엔드
"use strict";

let viewer = null;
let currentMol = null;      // {name, atoms, bonds, charge, formula}
let currentStyle = "stick";
let showLabels = false;
let dipoleVec = null;       // 최근 계산에서 얻은 쌍극자
let showDipole = false;     // 쌍극자 화살표 표시 여부 (툴바 토글)
// 3D 화면(WebGL)에 고성능 GPU를 요청할지 여부. 계산 엔진(MOPAC)의 연산과는 무관하다.
let gpuAccel = (() => { try { return localStorage.getItem("mopacGpuPref") !== "low-power"; } catch (_) { return true; } })();
let leftOpen = true;
let rightOpen = false;
let lastResults = [];      // The completed result cards currently displayed.

// 3Dmol은 powerPreference 를 넘기지 않고, 보통 OffscreenCanvas 하나에 WebGL2 컨텍스트를 만들어
// 모든 뷰어가 공유한다. 두 캔버스 종류의 getContext 를 모두 감싸 GPU 선택을 직접 요청한다.
(function patchWebGLPower() {
  for (const Canvas of [window.HTMLCanvasElement, window.OffscreenCanvas]) {
    if (!Canvas?.prototype?.getContext) continue;
    const orig = Canvas.prototype.getContext;
    Canvas.prototype.getContext = function (type, attrs) {
      if (typeof type === "string" && type.includes("webgl")) {
        attrs = Object.assign({}, attrs || {}, {
          powerPreference: gpuAccel ? "high-performance" : "low-power",
          failIfMajorPerformanceCaveat: false,
        });
      }
      return orig.call(this, type, attrs);
    };
  }
})();

const $ = (s) => document.querySelector(s);
const toastEl = $("#toast");
function toast(msg, ms = 2600) {
  toastEl.textContent = msg; toastEl.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => toastEl.classList.remove("show"), ms);
}
async function postJSON(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) });
  const text = await r.text();
  try {
    const data = text ? JSON.parse(text) : {};
    if (!r.ok && data.ok == null) data.ok = false;
    if (!r.ok) data.status = r.status;
    return data;
  } catch (e) {
    return { ok: false, status: r.status, error: `HTTP ${r.status}: ${r.statusText || "응답 오류"}`, text };
  }
}
function startServerHeartbeat() {
  const ping = () => fetch("/api/heartbeat", { method: "POST", keepalive: true }).catch(() => {});
  ping();
  setInterval(ping, 10000);
}

// ---------- 3D 뷰어 (WebGL = GPU) ----------
function initViewer() {
  const cfg = {
    backgroundColor: document.body.classList.contains("light") ? "white" : "black",
    antialias: true,
    preserveDrawingBuffer: true,
  };
  viewer = $3Dmol.createViewer($("#viewer"), cfg);
  viewer.setBackgroundColor(cfg.backgroundColor);
}

function molToXYZ(mol) {
  let s = mol.atoms.length + "\n" + (mol.name || "") + "\n";
  for (const a of mol.atoms)
    s += `${a.symbol} ${a.x} ${a.y} ${a.z}\n`;
  return s;
}

function renderMol(mol, { keepView = false } = {}) {
  currentMol = mol;
  $("#calcBtn").disabled=!!window.MopacEditor?.active || !!mol.editor_draft;
  if (!viewer) initViewer();
  viewer.removeAllModels();
  viewer.removeAllShapes();
  viewer.removeAllLabels();
  if (mol.atoms?.length) {
    const editor = window.MopacEditor;
    const editing = !!editor?.active || !!mol.editor_draft;
    viewer.addModel(editing ? editor.toMolBlock(mol) : molToXYZ(mol), editing ? "mol" : "xyz");
  }
  applyStyle();
  if (showLabels) addLabels();
  if (showDipole && dipoleVec) drawDipole(dipoleVec);
  if (window.MopacEditor?.active) window.MopacEditor.onRender();
  if (!keepView && mol.atoms?.length) viewer.zoomTo();
  viewer.render();
  $("#mol-info").innerHTML =
    `<b>${escapeHtml(mol.name || "molecule")}</b> · ${escapeHtml(mol.formula || "")} · ${mol.atoms.length} atoms · charge ${mol.charge ?? 0}` +
    (mol.warnings?.length ? `<br>⚠ ${escapeHtml(mol.warnings.join(" "))}` : "");
}

function applyStyle() {
  if (!viewer) return;
  const styles = {
    stick: { stick: { radius: 0.13 } },
    sphere: { stick: { radius: 0.13 }, sphere: { scale: 0.28 } },
    line: { line: {} },
  };
  const editing = !!window.MopacEditor?.active || !!currentMol?.editor_draft;
  // Standalone (unbonded) atoms must remain visible during free placement.
  const style = editing ? { ...styles[currentStyle], sphere: { scale: 0.33 } } : styles[currentStyle];
  viewer.setStyle({}, style);
  // Metals / noble gases can be valid standalone atoms without inferred bonds.
  const isolated=(viewer.getModel()?.selectedAtoms({})||[]).filter(a=>!a.bonds?.length).map(a=>a.index);
  if(isolated.length)viewer.addStyle({index:isolated},{sphere:{scale:0.33}});
  viewer.render();
}

function addLabels() {
  if (!currentMol) return;
  currentMol.atoms.forEach((a, i) => {
    viewer.addLabel(`${a.symbol}${i + 1}`, {
      position: { x: a.x, y: a.y, z: a.z }, fontSize: 11,
      backgroundColor: "rgba(0,0,0,0.5)", fontColor: "white", inFront: true,
    });
  });
}

function drawDipole(d) {
  if (!d || d.total == null) return;
  // 분자 중심에서 쌍극자 방향 화살표
  const c = currentMol.atoms.reduce((s, a) => ({ x: s.x + a.x, y: s.y + a.y, z: s.z + a.z }),
    { x: 0, y: 0, z: 0 });
  const n = currentMol.atoms.length;
  const o = { x: c.x / n, y: c.y / n, z: c.z / n };
  const k = 1.6;
  viewer.addArrow({
    start: o, end: { x: o.x + d.x * k, y: o.y + d.y * k, z: o.z + d.z * k },
    radius: 0.14, radiusRatio: 2.2, color: "magenta", mid: 0.75,
  });
  viewer.render();
}

// 최적화 구조 시각화: 새 좌표로 교체
function showOptimized(atoms, name) {
  if (!atoms || !atoms.length) { toast("최적화 좌표 없음"); return; }
  const mol = { name: (name || currentMol.name) + " (최적화됨)", atoms,
    bonds: [], charge: currentMol?.charge ?? 0, formula: currentMol?.formula || "" };
  renderMol(mol);
  toast("최적화된 구조를 표시합니다");
}

// 분자 오비탈 3D 등가면 (GPU, 3Dmol volumetric isosurface)
let _cubeCache = {};
let _orbitalRequestSerial = 0;
async function showOrbital(mgfPath, orbIndex, isoval, optAtoms, name) {
  const requestSerial = ++_orbitalRequestSerial;
  const key = mgfPath + "#" + orbIndex;
  toast("오비탈 " + orbIndex + " 계산 중...");
  let info = _cubeCache[key];
  if (!info) {
    const r = await postJSON("/api/cube", {
      mgf_path: mgfPath, orbital_index: orbIndex, spacing: 0.12
    });
    if (requestSerial !== _orbitalRequestSerial) return; // 이전 비동기 응답 무시
    if (!r.ok) { toast("오비탈 생성 실패: " + r.error, 4000); return; }
    info = { cube: r.cube, atoms: r.atoms, unit: r.unit };
    _cubeCache[key] = info;
  }
  if (requestSerial !== _orbitalRequestSerial) return;
  // MGF에는 파동함수 계산에 사용한 원자 좌표가 포함돼 있다.
  // 최적화 출력(.out) 또는 현재 편집 분자의 별도 좌표계 대신 이 좌표를 사용한다.
  // (백엔드가 구버전인 경우에만 optAtoms로 fallback.)
  const atoms = info.atoms?.length ? info.atoms : optAtoms;
  if (!atoms?.length) { toast("오비탈 원자 좌표를 찾을 수 없습니다.", 4000); return; }
  const sameMgf = currentMol?.orbitalSource === mgfPath;
  const orbitalInfo=lastResults.find(r=>r.mgf_path===mgfPath)?.data?.orbitals?.find(o=>o.index===orbIndex);
  const orbitalLabel=orbitalInfo?.tag||`MO ${orbIndex+1}`;
  viewer.removeAllSurfaces && viewer.removeAllSurfaces();
  renderMol({ name: (name || "MO") + " " + orbitalLabel + " 오비탈", atoms, bonds: [],
    charge: currentMol?.charge ?? 0, formula: currentMol?.formula || "",
    orbitalSource: mgfPath, orbitalIndex:orbIndex, orbitalLabel,
    orbitalIsovalue:isoval }, { keepView: sameMgf });
  try {
    const vol = new $3Dmol.VolumeData(info.cube, "cube");
    viewer.addIsosurface(vol, { isoval: isoval, color: "#1f6fff", opacity: 0.9, smoothness: 10 });
    viewer.addIsosurface(vol, { isoval: -isoval, color: "#ff3b30", opacity: 0.9, smoothness: 10 });
    if (showDipole && dipoleVec) drawDipole(dipoleVec);
    viewer.render();
    toast("오비탈 표시 완료 (파랑 +, 빨강 −)");
  } catch (e) {
    toast("오비탈 렌더링 오류: " + (e?.message || e), 5000);
  }
}

// 결과 도착 시 최적화 구조 자동 표시
function autoShowGeometry(results) {
  for (const res of results) {
    const a = res.data?.optimized_atoms;
    if (a?.length && res.status !== "error") { showOptimized(a, res.label); return; }
  }
}

// ---------- 구조 입력 ----------
async function loadSmiles() {
  if (window.MopacEditor?.active) {toast("먼저 3D 편집을 완료하거나 취소하세요.");return;}
  const s = $("#smilesInput").value.trim();
  if (!s) return;
  toast("3D 구조 생성 중...");
  const r = await postJSON("/api/structure/smiles", { smiles: s });
  if (r.ok) { dipoleVec = null; renderMol(r.mol); toast("생성 완료"); }
  else toast("오류: " + r.error, 4000);
}
async function loadPubchem() {
  if (window.MopacEditor?.active) {toast("먼저 3D 편집을 완료하거나 취소하세요.");return;}
  const q = $("#pubchemInput").value.trim();
  if (!q) return;
  toast("PubChem 조회 중...");
  const r = await postJSON("/api/structure/pubchem", { query: q });
  if (r.ok) { dipoleVec = null; renderMol(r.mol); toast("불러옴: " + r.mol.name); }
  else toast("오류: " + r.error, 4000);
}
async function loadFile(path) {
  if (window.MopacEditor?.active) {toast("먼저 3D 편집을 완료하거나 취소하세요.");return;}
  toast("파일 로드 중...");
  const r = await postJSON("/api/files/load", { path });
  if (r.ok) {
    dipoleVec = null;
    if(Array.isArray(r.results)){
      if(r.results.length)openRight();
      renderResults(r.results);
    }
    renderMol(r.mol);toast("로드 완료");
  }
  else toast("오류: " + r.error, 4000);
}
async function saveMol() {
  if(window.MopacEditor?.active || currentMol?.editor_draft){
    const r=await postJSON('/api/export',{format:'json',structure:window.MopacExports.currentStructure(),results:[]});
    if(r.ok){toast('편집 초안 저장됨: '+r.path,6000);refreshFiles();}
    else toast('저장 오류: '+r.error,5000);
    return;
  }
  if (!currentMol) { toast("저장할 분자가 없습니다"); return; }
  const payload = { name: currentMol.name || "molecule", xyz: molToXYZ(currentMol) };
  if (currentMol.bonds?.length) payload.molblock = window.MopacEditor.toMolBlock(currentMol);
  const r = await postJSON("/api/files/save", payload);
  if (r.ok) { toast("저장됨: " + r.path + (r.mol_path ? " · .mol 결합정보 포함" : "")); refreshFiles(); }
  else toast("저장 오류: " + r.error, 4000);
}
async function openDraw() {
  const r = await postJSON("/api/draw", {});
  toast(r.ok ? r.msg : "오류: " + r.error, 5000);
}

// ---------- 파일 트리 ----------
async function refreshFiles() {
  const r = await (await fetch("/api/files")).json();
  const root = $("#fileTree"); root.innerHTML = "";
  root.appendChild(renderTree(r.tree));
}
function renderTree(items) {
  const frag = document.createDocumentFragment();
  const loadable = [".xyz", ".mol", ".sdf", ".pdb", ".mop", ".arc", ".json"];
  for (const it of items) {
    const el = document.createElement("div");
    if (it.type === "dir") {
      el.className = "tree-item dir";
      const label=document.createElement('span');label.textContent=`▸ ${it.name}`;
      const open=document.createElement('button');open.className='tree-open-folder';
      open.textContent='↗';open.title='파일 탐색기에서 폴더 열기';
      open.onclick=e=>{e.stopPropagation();window.MopacExports.openFolder(it.path);};
      el.append(label,open);
      const children = document.createElement("div");
      children.className = "tree-children"; children.style.display = "none";
      children.appendChild(renderTree(it.children || []));
      el.onclick = (e) => { e.stopPropagation();
        const open = children.style.display === "none";
        children.style.display = open ? "block" : "none";
        label.textContent = `${open ? "▾" : "▸"} ${it.name}`; };
      el.appendChild(children);
    } else {
      el.className = "tree-item";
      el.innerHTML = `📄 ${it.name}<span class="ext">${it.ext}</span>`;
      el.title = it.path;
      el.onclick = (e) => { e.stopPropagation();
        if (loadable.includes(it.ext)) loadFile(it.path);
        else if (it.ext === ".out") viewRaw(it.path);
        else toast("미리보기 불가: " + it.ext); };
    }
    frag.appendChild(el);
  }
  return frag;
}
async function viewRaw(path) {
  openRight();
  $("#results").innerHTML = `<div style="padding:14px;color:var(--muted)">
    <span class="spinner"></span> 로컬 결과 불러오는 중...</div>`;
  const parsed = await postJSON("/api/files/result", { path });
  if (parsed.ok) {
    renderResults(parsed.results);
    toast("로컬 결과 표시 완료");
    return;
  }
  const r = await postJSON("/api/files/read", { path });
  if (!r.ok) { toast(r.error); return; }
  $("#results").innerHTML = `<div class="rcard"><div class="rh">${path.split(/[\\/]/).pop()}</div>` +
    `<div class="rb"><pre class="raw">${escapeHtml(r.text)}</pre></div></div>`;
}
function escapeHtml(s){return s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}

// ---------- 계산 모달 ----------
let calcTypes = [];
async function loadCalcTypes() {
  calcTypes = await (await fetch("/api/calc_types")).json();
  const grid = $("#calcGrid"); grid.innerHTML = "";
  for (const c of calcTypes) {
    const lab = document.createElement("label");
    lab.className = "calc-opt";
    lab.innerHTML = `<input type="checkbox" value="${c.key}">
      <span><b>${c.label}</b>${c.note ? `<div class="note">⚠ ${c.note}</div>` : ""}</span>`;
    const cb = lab.querySelector("input");
    cb.onchange = () => { lab.classList.toggle("on", cb.checked); updateCount(); };
    grid.appendChild(lab);
  }
  updateCount();
}
function updateCount() {
  const n = document.querySelectorAll("#calcGrid input:checked").length;
  $("#calcCount").textContent = `${n}개 선택됨`;
}
function openCalcModal() {
  if(window.MopacEditor?.active || currentMol?.editor_draft){
    toast("3D 편집기에서 '수소 추가 → 계산에 적용'을 먼저 누르세요.");return;
  }
  if (!currentMol) { toast("먼저 분자를 불러오세요"); return; }
  $("#calcModal").classList.add("show");
}

async function runCalculations() {
  if(window.MopacEditor?.active || currentMol?.editor_draft){
    toast("편집 초안을 먼저 계산에 적용하세요.");return;
  }
  const keys = [...document.querySelectorAll("#calcGrid input:checked")].map(c => c.value);
  if (!keys.length) { toast("계산을 1개 이상 선택하세요"); return; }
  lastResults=[];
  $("#calcModal").classList.remove("show");
  openRight();
  const startedAt = performance.now();
  const results = [];
  let runDir = null;
  $("#results").innerHTML = `<div class="progress-card" id="calcProgress"></div><div id="liveResults"></div>`;
  for (let i = 0; i < keys.length; i++) {
    const key = keys[i];
    updateProgress(i, keys.length, key, startedAt, false);
    const r = await postJSON("/api/calculate_one", {
      mol: currentMol, calc_key: key, run_dir: runDir,
      charge: +$("#chargeIn").value, mult: +$("#multIn").value, eps: +$("#epsIn").value,
    });
    if (r.status === 404) {
      await runCalculationsLegacy(keys, startedAt);
      return;
    }
    if (r.ok) {
      runDir = r.run_dir;
      results.push(r.result);
    } else {
      results.push({ calc_key: key, label: calcLabel(key), status: "error", errors: [r.error || "실행 실패"], data: {} });
    }
    activateDipoleFromResults(results);
    renderLiveResults(results);
    updateProgress(i + 1, keys.length, keys[i + 1], startedAt, i + 1 === keys.length);
  }
  autoShowGeometry(results);
  refreshFiles();
}

async function runCalculationsLegacy(keys, startedAt) {
  updateProgress(0, keys.length, "기존 계산 API", startedAt, false);
  toast("서버가 이전 버전입니다. 기존 계산 API로 실행합니다.", 3500);
  const r = await postJSON("/api/calculate", {
    mol: currentMol, calc_keys: keys,
    charge: +$("#chargeIn").value, mult: +$("#multIn").value, eps: +$("#epsIn").value,
  });
  if (!r.ok) {
    $("#results").innerHTML = `<div class="errline">실행 실패: ${escapeHtml(r.error || "알 수 없는 오류")}</div>`;
    return;
  }
  updateProgress(keys.length, keys.length, null, startedAt, true);
  renderResults(r.results || []);
  refreshFiles();
}

// ---------- 결과 렌더 ----------
function activateDipoleFromResults(results) {
  for (const res of results) {
    if (res.status !== "error" && res.data?.dipole?.total != null) {
      dipoleVec = res.data.dipole; showDipole = true; return;
    }
  }
}
function renderResults(results) {
  lastResults=results.slice();
  const box = $("#results"); box.innerHTML = "";
  // 쌍극자가 계산되면 자동으로 활성화 (툴바 '쌍극자' 버튼이 바로 동작하도록)
  activateDipoleFromResults(results);
  for (const res of results) box.appendChild(renderCard(res));
  autoShowGeometry(results);
}
function renderLiveResults(results) {
  lastResults=results.slice();
  const box = $("#liveResults");
  if (!box) return;
  box.innerHTML = "";
  for (const res of results) box.appendChild(renderCard(res));
}
function calcLabel(key) {
  return calcTypes.find(c => c.key === key)?.label || key;
}
function formatDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "계산 중";
  seconds = Math.max(0, Math.round(seconds));
  const m = Math.floor(seconds / 60), s = seconds % 60;
  return m ? `${m}분 ${s}초` : `${s}초`;
}
function updateProgress(done, total, currentKey, startedAt, finished) {
  const el = $("#calcProgress");
  if (!el) return;
  const elapsed = (performance.now() - startedAt) / 1000;
  const avg = done ? elapsed / done : null;
  const eta = finished ? 0 : avg == null ? null : avg * (total - done);
  const pct = total ? Math.round((done / total) * 100) : 0;
  const current = finished ? "완료" : `진행 중: ${calcLabel(currentKey)}`;
  el.innerHTML = `<div class="progress-head"><span class="spinner"></span>${current}</div>
    <div class="progress-body">
      <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
      <div class="progress-meta">
        <span>${done}/${total} 완료 (${pct}%)</span>
        <span>경과 ${formatDuration(elapsed)}</span>
        <span>예상 남은 시간 ${formatDuration(eta)}</span>
      </div>
    </div>`;
}
function fmt(v) {
  if (v == null) return '<span style="color:var(--err)">—</span>';
  if (typeof v === "number") return v.toFixed(Math.abs(v) < 1 ? 5 : 4).replace(/\.?0+$/, "");
  return v;
}
function renderCard(res) {
  const card = document.createElement("div");
  const isErr = res.status === "error";
  card.className = "rcard" + (isErr ? " err" : "");
  let body = "";

  if (res.note) body += `<div class="notebox">⚠ ${res.note}</div>`;
  if (isErr && res.errors?.length)
    body += res.errors.map(e => `<div class="errline">✖ Error: ${escapeHtml(e)}</div>`).join("");

  const d = res.data || {};
  // 일반 키-값 표
  const rows = [];
  for (const [k, v] of Object.entries(d)) {
    if (["optimized_atoms", "thermo_table", "bond_orders", "mulliken_bond_orders", "charges",
         "frequencies_cm1", "imaginary_modes", "spin_density", "internal",
         "mo_energies", "dipole", "orbitals", "pKa_per_atom", "homo_index",
         "lumo_index", "mo_viz_error"].includes(k)) continue;
    rows.push(`<tr><td>${k}</td><td>${fmt(v)}</td></tr>`);
  }
  if (rows.length) body += `<table>${rows.join("")}</table>`;

  // 쌍극자
  if (d.dipole) {
    const dp = d.dipole;
    body += `<table><tr><td>μx,μy,μz (D)</td><td>${fmt(dp.x)}, ${fmt(dp.y)}, ${fmt(dp.z)}</td></tr>
      <tr><td>전체 |μ| (D)</td><td><b>${fmt(dp.total)}</b></td></tr></table>
      <span class="minilink" data-act="dipole">▶ 3D에 쌍극자 표시</span>`;
  }
  // 최적화 구조
  if (d.optimized_atoms?.length) {
    body += `<div style="margin-top:6px"><span class="minilink" data-act="opt">▶ 최적화 구조 3D 보기 (${d.optimized_atoms.length} atoms)</span></div>`;
    if (d.internal?.bond_lengths?.length) {
      body += `<details style="margin-top:6px"><summary class="minilink">결합 길이 보기</summary><table>` +
        d.internal.bond_lengths.map(b => `<tr><td>${b.pair}</td><td>${b.length_A} Å</td></tr>`).join("") +
        `</table></details>`;
    }
  }
  // 전하
  if (d.charges?.length) {
    body += `<details style="margin-top:6px"><summary class="minilink">원자 전하 (${d.charges.length})</summary><table>` +
      d.charges.map(c => `<tr><td>${c.symbol}${c.idx}</td><td>${fmt(c.charge)}</td></tr>`).join("") +
      `</table></details>`;
  }
  // 결합차수
  const bondOrders = d.bond_orders || d.mulliken_bond_orders;
  if (bondOrders?.length) {
    body += `<details style="margin-top:6px"><summary class="minilink">결합 차수 (${bondOrders.length})</summary><table>` +
      bondOrders.map(b => `<tr><td>${b.a}-${b.b}</td><td>${fmt(b.order)}</td></tr>`).join("") +
      `</table></details>`;
  }
  // 스핀밀도
  if (d.spin_density?.length) {
    body += `<details style="margin-top:6px"><summary class="minilink">스핀 밀도 (${d.spin_density.length})</summary><table>` +
      d.spin_density.map(s => `<tr><td>${s.symbol}${s.idx}</td><td>${fmt(s.spin)}</td></tr>`).join("") +
      `</table></details>`;
  }
  // pKa (원자별)
  if (d.pKa_per_atom?.length) {
    body += `<table>` + d.pKa_per_atom.map(p =>
      `<tr><td>원자 #${p.atom ?? "-"}</td><td>pKa = <b>${fmt(p.pKa)}</b></td></tr>`).join("") + `</table>`;
  }
  // 진동수 + IR
  if (d.frequencies_cm1?.length) {
    body += `<div style="margin-top:6px">진동 모드 ${d.n_modes}개` +
      (d.imaginary_modes?.length ? ` · <span style="color:var(--err)">허수 ${d.imaginary_modes.length}개</span>` : "") + `</div>`;
    body += `<canvas class="modiagram irspec" height="120"></canvas>`;
  }
  // 분자 오비탈: 3D 등가면 + 에너지 준위도
  if (res.calc_key === "molecular_orbitals") {
    if (d.mo_viz_error) body += `<div class="errline">${d.mo_viz_error}</div>`;
    if (d.orbitals?.length && res.mgf_path) {
      body += `<div style="margin:6px 0 4px;font-weight:600">오비탈 선택 → 3D 등가면 (GPU)</div>`;
      body += `<div class="orb-list">`;
      // HOMO 주변 위주로 정렬해 보여줌
      d.orbitals.forEach(o => {
        const hot = o.tag === "HOMO" || o.tag === "LUMO";
        body += `<button class="orb-btn ${hot ? "hot" : ""}" data-orb="${o.index}"
          data-mgf="${encodeURIComponent(res.mgf_path)}">
          ${o.tag ? `<b>${o.tag}</b> ` : ""}${o.label} · ${o.energy} eV</button>`;
      });
      body += `</div><div class="iso-ctl">등가면 값
        <input type="range" class="isoval" min="0.005" max="0.08" step="0.005" value="0.03">
        <span class="isoval-lbl">0.030</span></div>`;
    }
    body += `<canvas class="modiagram modgm" height="160"></canvas>`;
  }
  // THERMO 표
  if (d.thermo_table?.length) {
    body += `<details style="margin-top:6px"><summary class="minilink">열역학 표(T/Cp/S)</summary><table>
      <tr><td>T(K)</td><td>Cp</td><td>S</td></tr>` +
      d.thermo_table.filter((_,i)=>i%3===0).map(t => `<tr><td>${t.T}</td><td>${fmt(t.Cp)}</td><td>${fmt(t.S)}</td></tr>`).join("") +
      `</table></details>`;
  }
  // 입력/출력 보기
  if (res.input)
    body += `<details style="margin-top:6px"><summary class="minilink">MOPAC 입력(.mop)</summary><pre class="raw">${escapeHtml(res.input)}</pre></details>`;

  card.innerHTML = `<div class="rh">${res.label || res.calc_key}
    <span class="spacer" style="flex:1"></span>
    <span class="badge ${isErr ? "err" : "ok"}">${isErr ? "ERROR" : "OK"}</span></div>
    <div class="rb">${body || '<span style="color:var(--muted)">결과 없음</span>'}</div>`;
  if(res.run_dir){
    const folder=document.createElement('button');folder.className='btn sm result-folder';
    folder.textContent='계산 폴더 열기';folder.onclick=()=>window.MopacExports.openFolder(res.run_dir);
    card.querySelector('.rb').appendChild(folder);
  }

  // 인터랙션
  card.querySelectorAll(".minilink[data-act]").forEach(el => {
    el.onclick = () => {
      if (el.dataset.act === "opt") showOptimized(d.optimized_atoms, res.label);
      if (el.dataset.act === "dipole") { dipoleVec = d.dipole; showDipole = true; renderMol(currentMol, { keepView: true }); toast(`쌍극자 |μ| = ${d.dipole.total} D`); }
    };
  });
  // 오비탈 등가면 버튼
  let isoval = 0.03, activeOrb = null, activeMgf = null;
  card.querySelectorAll(".orb-btn").forEach(b => {
    b.onclick = () => {
      card.querySelectorAll(".orb-btn").forEach(x => x.classList.remove("sel"));
      b.classList.add("sel");
      activeOrb = +b.dataset.orb;
      activeMgf = decodeURIComponent(b.dataset.mgf);
      showOrbital(activeMgf, activeOrb, isoval, d.optimized_atoms, res.label);
    };
  });
  const slider = card.querySelector(".isoval");
  if (slider) slider.oninput = () => {
    isoval = +slider.value;
    card.querySelector(".isoval-lbl").textContent = isoval.toFixed(3);
    if (activeOrb != null) showOrbital(activeMgf, activeOrb, isoval, d.optimized_atoms, res.label);
  };
  // 캔버스 그리기 (다음 틱)
  setTimeout(() => {
    const irc = card.querySelector(".irspec");
    if (irc) drawIR(irc, d.frequencies_cm1);
    const mog = card.querySelector(".modgm");
    if (mog) drawMODiagram(mog, d);
  }, 0);
  return card;
}

// IR 스펙트럼 (막대)
function drawIR(canvas, freqs) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width = canvas.clientWidth, H = canvas.height;
  const cs = getComputedStyle(document.body);
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = cs.getPropertyValue("--muted"); ctx.beginPath();
  ctx.moveTo(30, H - 18); ctx.lineTo(W - 6, H - 18); ctx.stroke();
  const max = 4000;
  ctx.fillStyle = cs.getPropertyValue("--accent");
  ctx.strokeStyle = cs.getPropertyValue("--accent");
  freqs.forEach(f => {
    if (f <= 0) return;
    const x = 30 + (f / max) * (W - 40);
    ctx.beginPath(); ctx.moveTo(x, H - 18); ctx.lineTo(x, 10); ctx.stroke();
  });
  ctx.fillStyle = cs.getPropertyValue("--muted"); ctx.font = "10px sans-serif";
  ctx.fillText("0", 28, H - 4); ctx.fillText("4000 cm⁻¹", W - 60, H - 4);
}

// MO 에너지 준위 다이어그램
function drawMODiagram(canvas, d) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width = canvas.clientWidth, H = canvas.height;
  const cs = getComputedStyle(document.body);
  ctx.clearRect(0, 0, W, H);

  // 에너지/HOMO·LUMO 표시는 .mgf 오비탈 목록(d.orbitals)을 우선 사용 — 인덱스·에너지가
  // 같은 출처라 일관됨. (AUX mo_energies 와 mgf 로컬 인덱스를 섞으면 어긋남)
  let items = null;   // {e, occ, isHomo, isLumo}
  if (d.orbitals?.length) {
    items = d.orbitals.map(o => ({ e: o.energy, occ: o.occ,
      isHomo: o.tag === "HOMO", isLumo: o.tag === "LUMO" }));
  } else if (d.homo_ev != null && d.lumo_ev != null) {
    items = [{ e: d.homo_ev, occ: 2, isHomo: true, isLumo: false },
             { e: d.lumo_ev, occ: 0, isHomo: false, isLumo: true }];
  }
  if (!items?.length) return;

  const es = items.map(i => i.e);
  const mn = Math.min(...es), mx = Math.max(...es), rng = (mx - mn) || 1;
  const yOf = (e) => H - 22 - ((e - mn) / rng) * (H - 44);
  ctx.font = "10px sans-serif";
  // 일반 준위
  items.forEach(it => {
    const y = yOf(it.e);
    ctx.strokeStyle = it.isHomo ? "#3fb950" : it.isLumo ? "#f85149"
      : (it.occ > 0 ? cs.getPropertyValue("--muted") : "rgba(140,150,160,.45)");
    ctx.lineWidth = (it.isHomo || it.isLumo) ? 3 : 1.5;
    ctx.beginPath(); ctx.moveTo(58, y); ctx.lineTo(W - 92, y); ctx.stroke();
  });
  // HOMO/LUMO 라벨 (겹치지 않게 위/아래로 분리 배치)
  const homo = items.find(i => i.isHomo), lumo = items.find(i => i.isLumo);
  if (homo) { ctx.fillStyle = "#3fb950";
    ctx.fillText(`HOMO ${homo.e.toFixed(2)} eV`, W - 90, yOf(homo.e) + 11); }
  if (lumo) { ctx.fillStyle = "#f85149";
    ctx.fillText(`LUMO ${lumo.e.toFixed(2)} eV`, W - 90, yOf(lumo.e) - 4); }
  if (homo && lumo) { ctx.fillStyle = cs.getPropertyValue("--accent");
    ctx.fillText(`gap ${(lumo.e - homo.e).toFixed(2)} eV`, 58, (yOf(homo.e) + yOf(lumo.e)) / 2 + 3); }
  ctx.fillStyle = cs.getPropertyValue("--text");
  ctx.fillText("E (eV)", 6, 12);
}

// ---------- 패널/테마 ----------
function openRight() {
  rightOpen = true;
  const current = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--right-w"), 10) || 460;
  setPanelWidth("right", current);
  $("#right").classList.add("open");
  $("#right").classList.remove("closed");
  $("#right").style.overflow = "";
  const resizer = $("#rightResizer");
  if (resizer) { resizer.classList.remove("hidden"); resizer.style.display = ""; }
  setTimeout(() => viewer && viewer.resize(), 220);
}
function closeRight() {
  rightOpen = false;
  $("#right").classList.remove("open");
  $("#right").classList.add("closed");
  $("#right").style.width = "0px";
  $("#right").style.flexBasis = "0px";
  $("#right").style.overflow = "hidden";
  const resizer = $("#rightResizer");
  if (resizer) { resizer.classList.add("hidden"); resizer.style.display = "none"; }
  setTimeout(() => viewer && viewer.resize(), 220);
}
function openLeft() {
  leftOpen = true;
  const current = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--left-w"), 10) || 300;
  setPanelWidth("left", current);
  $("#left").classList.remove("closed");
  $("#left").style.overflow = "";
  const resizer = $("#leftResizer");
  if (resizer) { resizer.classList.remove("hidden"); resizer.style.display = ""; }
  setTimeout(() => viewer && viewer.resize(), 220);
}
function closeLeft() {
  leftOpen = false;
  $("#left").classList.add("closed");
  $("#left").style.width = "0px";
  $("#left").style.flexBasis = "0px";
  $("#left").style.overflow = "hidden";
  const resizer = $("#leftResizer");
  if (resizer) { resizer.classList.add("hidden"); resizer.style.display = "none"; }
  setTimeout(() => viewer && viewer.resize(), 220);
}
function toggleLeft() { leftOpen ? closeLeft() : openLeft(); }
function toggleRight() { rightOpen ? closeRight() : openRight(); }

function ensurePanelControls() {
  const header = document.querySelector("header");
  const gpu = $("#gpuToggle");
  if (header && gpu && !$("#toggleLeft")) {
    const b = document.createElement("button");
    b.className = "btn sm";
    b.id = "toggleLeft";
    b.textContent = "왼쪽 패널";
    header.insertBefore(b, gpu);
  }
  if (header && gpu && !$("#toggleRight")) {
    const b = document.createElement("button");
    b.className = "btn sm";
    b.id = "toggleRight";
    b.textContent = "결과 패널";
    header.insertBefore(b, gpu);
  }
  const left = $("#left"), center = $("#center"), right = $("#right");
  if (left && center && !$("#leftResizer")) {
    const r = document.createElement("div");
    r.className = "resizer";
    r.id = "leftResizer";
    r.title = "왼쪽 패널 크기 조절";
    left.insertAdjacentElement("afterend", r);
  }
  if (center && right && !$("#rightResizer")) {
    const r = document.createElement("div");
    r.className = "resizer hidden";
    r.id = "rightResizer";
    r.title = "결과 패널 크기 조절";
    right.insertAdjacentElement("beforebegin", r);
  }
  document.querySelectorAll(".resizer").forEach(r => {
    Object.assign(r.style, {
      width: "10px",
      flex: "0 0 10px",
      cursor: "col-resize",
      background: "var(--border)",
      zIndex: "8",
    });
  });
}

function setPanelWidth(which, px) {
  const root = document.documentElement;
  const panel = which === "left" ? $("#left") : $("#right");
  const prop = which === "left" ? "--left-w" : "--right-w";
  root.style.setProperty(prop, `${Math.round(px)}px`);
  if (panel) {
    panel.style.width = `${Math.round(px)}px`;
    panel.style.flexBasis = `${Math.round(px)}px`;
  }
}

function initPanelResizers() {
  ensurePanelControls();
  const root = document.documentElement;
  const main = $("#main");
  const leftResizer = $("#leftResizer");
  const rightResizer = $("#rightResizer");
  if (!main || !leftResizer || !rightResizer) return;
  let active = null;
  function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }
  function start(which, e) {
    active = which;
    e.currentTarget.classList.add("dragging");
    document.body.style.userSelect = "none";
    e.preventDefault();
  }
  function stop() {
    if (!active) return;
    document.querySelectorAll(".resizer").forEach(r => r.classList.remove("dragging"));
    document.body.style.userSelect = "";
    active = null;
    viewer && viewer.resize();
  }
  leftResizer.addEventListener("pointerdown", e => start("left", e));
  rightResizer.addEventListener("pointerdown", e => start("right", e));
  window.addEventListener("pointermove", e => {
    if (!active) return;
    const rect = main.getBoundingClientRect();
    if (active === "left") {
      const w = clamp(e.clientX - rect.left, 180, window.innerWidth * 0.65);
      setPanelWidth("left", w);
    } else {
      const w = clamp(rect.right - e.clientX, 260, window.innerWidth * 0.8);
      setPanelWidth("right", w);
    }
    viewer && viewer.resize();
  });
  window.addEventListener("pointerup", stop);
  closeRight();
}

function toggleTheme() {
  document.body.classList.toggle("light");
  if (viewer) {
    const bg = document.body.classList.contains("light") ? "white" : "black";
    $("#center").style.background = bg;
    viewer.setBackgroundColor(bg); viewer.render();
  }
}
// 현재 3D 화면이 실제로 받은 WebGL 설정과 GPU 이름 (브라우저가 감추면 null)
function viewerGPU() {
  const gl = viewer?.renderer?._gl;
  if (!gl || gl.isContextLost()) return null;
  const info = gl.getExtension("WEBGL_debug_renderer_info");
  return { gl, preference: gl.getContextAttributes()?.powerPreference,
           renderer: info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : null };
}
function updateGpuButton() {
  const btn = $("#gpuToggle"), gpu = viewerGPU();
  btn.textContent = "3D GPU: " + (gpuAccel ? "고성능" : "절전");
  btn.title = "3D 화면을 그릴 GPU 선택 (그래픽 칩이 둘인 PC에서 차이가 납니다. MOPAC 계산은 CPU로 실행됩니다.)\n" +
    `요청: ${gpuAccel ? "high-performance" : "low-power"} · 적용: ${gpu?.preference || "확인 불가"}` +
    (gpu?.renderer ? `\nGPU: ${gpu.renderer}` : "");
}
function toggleGPU() {
  gpuAccel = !gpuAccel;
  try { localStorage.setItem("mopacGpuPref", gpuAccel ? "high-performance" : "low-power"); } catch (_) {}
  // 공유 WebGL 컨텍스트를 놓아야 3Dmol이 새 설정으로 컨텍스트를 다시 만든다.
  const view = viewer?.getView?.();
  viewerGPU()?.gl.getExtension("WEBGL_lose_context")?.loseContext();
  const mol = currentMol;
  $("#viewer").innerHTML = ""; viewer = null; initViewer();
  if (mol) { renderMol(mol, { keepView: true }); if (view) { viewer.setView(view); viewer.render(); } }
  updateGpuButton();
  const applied = viewerGPU()?.preference;
  toast(`3D 화면 GPU: ${gpuAccel ? "고성능" : "절전"} 요청` + (applied ? ` (적용: ${applied})` : ""));
}

// ---------- 이벤트 바인딩 ----------
window.addEventListener("DOMContentLoaded", () => {
  startServerHeartbeat();
  initViewer();
  initPanelResizers();
  loadCalcTypes();
  refreshFiles();

  $("#smilesBtn").onclick = loadSmiles;
  $("#smilesInput").addEventListener("keydown", e => { if (e.key === "Enter") loadSmiles(); });
  $("#pubchemBtn").onclick = loadPubchem;
  $("#pubchemInput").addEventListener("keydown", e => { if (e.key === "Enter") loadPubchem(); });
  $("#drawBtn").onclick = openDraw;
  window.MopacEditor.init();
  $("#saveBtn").onclick = saveMol;
  $("#refreshBtn").onclick = refreshFiles;

  $("#calcBtn").onclick = openCalcModal;
  $("#cancelCalc").onclick = () => $("#calcModal").classList.remove("show");
  $("#runCalc").onclick = runCalculations;
  $("#selectAll").onclick = () => { document.querySelectorAll("#calcGrid input").forEach(c => { c.checked = true; c.dispatchEvent(new Event("change")); }); };
  $("#selectNone").onclick = () => { document.querySelectorAll("#calcGrid input").forEach(c => { c.checked = false; c.dispatchEvent(new Event("change")); }); };
  $("#closeRight").onclick = closeRight;
  if ($("#toggleLeft")) $("#toggleLeft").onclick = toggleLeft;
  if ($("#toggleRight")) $("#toggleRight").onclick = toggleRight;
  $("#calcModal").onclick = (e) => { if (e.target.id === "calcModal") $("#calcModal").classList.remove("show"); };

  $("#themeToggle").onclick = toggleTheme;
  $("#gpuToggle").onclick = toggleGPU;
  updateGpuButton();

  document.querySelectorAll("#viewer-toolbar .chip[data-style]").forEach(b => {
    b.onclick = () => { currentStyle = b.dataset.style; applyStyle(); };
  });
  $("#labelToggle").onclick = () => { showLabels = !showLabels; if (currentMol) renderMol(currentMol, { keepView: true }); };
  $("#dipoleToggle").onclick = () => {
    if (!dipoleVec) { toast("먼저 '쌍극자 모멘트' 계산을 실행하세요"); return; }
    showDipole = !showDipole;
    renderMol(currentMol, { keepView: true });
    toast(showDipole ? `쌍극자 표시 (|μ|=${dipoleVec.total} D)` : "쌍극자 숨김");
  };
});
