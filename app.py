# -*- coding: utf-8 -*-
"""MOPAC Studio - Flask 백엔드.

API
  GET  /                      메인 UI
  GET  /api/calc_types        계산 종류 목록
  POST /api/structure/smiles  {smiles}            -> 분자 dict
  POST /api/structure/pubchem {query}             -> 분자 dict
  GET  /api/files             워크스페이스 파일 트리
  POST /api/files/load        {path}              -> 분자 dict
  POST /api/files/save        {name, xyz}         -> 저장
  POST /api/draw              Avogadro 실행
  POST /api/calculate         {mol, calc_keys[], charge, mult, eps} -> 결과들
"""
import os
import json
import time
import threading
import subprocess
import tempfile
import socket

from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

import structure
import mopac_runner as mr
import mo_cube
from editor_3d import from_editor, OptimizationError

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(HERE, "workspace")
os.makedirs(WORKSPACE, exist_ok=True)
AVOGADRO = os.environ.get("AVOGADRO_EXE", r"C:\Program Files (x86)\Avogadro\bin\avogadro.exe")

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

SERVER_STATE = {
    "last_heartbeat": time.time(),
    "active_calculations": 0,
    "idle_monitor_started": False,
}
SERVER_STATE_LOCK = threading.Lock()


@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/version")
def api_version():
    return jsonify({"ok": True, "version": "3.0.1", "build": "v3-orbital-atomic-number-fix-2026-10-25", "editor_api": True,
                    "fragments": True, "dragging": True})


@app.route("/api/calc_types")
def calc_types():
    return jsonify(mr.list_calc_types())


@app.route("/api/structure/smiles", methods=["POST"])
def api_smiles():
    data = request.get_json(force=True)
    try:
        mol = structure.from_smiles(data.get("smiles", ""), data.get("name"))
        return jsonify({"ok": True, "mol": mol})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/structure/editor", methods=["POST"])
def api_editor():
    """Build explicitly hydrogenated MOPAC-ready structure from a 3D drawing."""
    data = request.get_json(silent=True) or {}
    try:
        mol = from_editor(data.get("mol"), relax_heavy=data.get("relax", False) is True)
        return jsonify({"ok": True, "mol": mol})
    except OptimizationError as e:
        return jsonify({"ok": False, "error": str(e), "code": "optimization_failed",
                        "recoverable": True}), 422
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "recoverable": True}), 400


@app.route("/api/structure/pubchem", methods=["POST"])
def api_pubchem():
    data = request.get_json(force=True)
    try:
        mol = structure.from_pubchem(data.get("query", ""))
        return jsonify({"ok": True, "mol": mol})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


def _walk(path):
    items = []
    try:
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                items.append({"name": name, "type": "dir", "path": full,
                              "children": _walk(full)})
            else:
                items.append({"name": name, "type": "file", "path": full,
                              "ext": os.path.splitext(name)[1].lower(),
                              "size": os.path.getsize(full)})
    except PermissionError:
        pass
    return items


@app.route("/api/files")
def api_files():
    return jsonify({"root": WORKSPACE, "tree": _walk(WORKSPACE)})


@app.route("/api/heartbeat", methods=["POST"])
def api_heartbeat():
    with SERVER_STATE_LOCK:
        SERVER_STATE["last_heartbeat"] = time.time()
    return jsonify({"ok": True})


def _begin_calculation():
    with SERVER_STATE_LOCK:
        SERVER_STATE["active_calculations"] += 1


def _end_calculation():
    with SERVER_STATE_LOCK:
        SERVER_STATE["active_calculations"] = max(0, SERVER_STATE["active_calculations"] - 1)


def start_idle_shutdown_monitor(timeout_s=90, check_interval_s=5):
    with SERVER_STATE_LOCK:
        if SERVER_STATE["idle_monitor_started"]:
            return
        SERVER_STATE["idle_monitor_started"] = True

    def monitor():
        while True:
            time.sleep(check_interval_s)
            with SERVER_STATE_LOCK:
                idle_for = time.time() - SERVER_STATE["last_heartbeat"]
                active = SERVER_STATE["active_calculations"]
            if active == 0 and idle_for >= timeout_s:
                os._exit(0)

    threading.Thread(target=monitor, daemon=True).start()


@app.route("/api/files/load", methods=["POST"])
def api_load():
    data = request.get_json(force=True)
    path = data.get("path", "")
    # 워크스페이스 밖 임의 경로도 허용(좌측 로컬 탐색 요구사항). 단 존재 확인.
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "파일이 없습니다."}), 400
    try:
        mol = structure.from_file(path)
        return jsonify({"ok": True, "mol": mol})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/files/read", methods=["POST"])
def api_read():
    """텍스트 파일 원문 보기 (.out 등)."""
    data = request.get_json(force=True)
    path = data.get("path", "")
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "파일이 없습니다."}), 400
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return jsonify({"ok": True, "text": f.read()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


def _safe_run_dir(run_dir=None):
    root = os.path.join(WORKSPACE, "runs")
    os.makedirs(root, exist_ok=True)
    if not run_dir:
        return os.path.join(root, time.strftime("%Y%m%d_%H%M%S"))
    full = os.path.abspath(run_dir)
    root_abs = os.path.abspath(root)
    if not (full == root_abs or full.startswith(root_abs + os.sep)):
        raise ValueError("허용되지 않은 실행 폴더입니다.")
    return full


def _assemble_from_files(key, base, run_dir=None):
    out_text = ""
    if os.path.exists(base + ".out"):
        with open(base + ".out", "r", encoding="utf-8", errors="ignore") as f:
            out_text = f.read()
    aux_text = ""
    if os.path.exists(base + ".aux"):
        with open(base + ".aux", "r", encoding="utf-8", errors="ignore") as f:
            aux_text = f.read()
    res = mr.assemble_result(key, out_text, aux_text)
    if os.path.exists(base + ".mop"):
        with open(base + ".mop", "r", encoding="utf-8", errors="ignore") as f:
            res["input"] = f.read()
    res["files"] = mr.cleanup_aux(base)
    if run_dir:
        res["run_dir"] = run_dir
    if key == "molecular_orbitals" and os.path.exists(base + ".mgf"):
        try:
            with open(base + ".mgf", "r", encoding="utf-8", errors="ignore") as f:
                mgf = mo_cube.parse_mgf(f.read())
            olist, homo, lumo = mo_cube.orbital_list(mgf)
            res["data"]["orbitals"] = olist
            res["data"]["homo_index"] = homo
            res["data"]["lumo_index"] = lumo
            res["mgf_path"] = base + ".mgf"
        except Exception as e:
            res["data"]["mo_viz_error"] = f"오비탈 파싱 실패: {e}"
    return res


def _needs_stationary_geometry(key):
    keywords = mr.CALC_TYPES[key]["keywords"].upper().split()
    return "FORCE" in keywords


def _mol_with_atoms(mol, atoms, name_suffix=" optimized"):
    out = dict(mol)
    out["atoms"] = atoms
    out["name"] = (mol.get("name") or "molecule") + name_suffix
    return out


def _read_out_atoms(base):
    out_path = base + ".out"
    if not os.path.exists(out_path):
        return []
    with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
        return mr.parse_optimized_geometry(f.read())


def _preoptimized_mol(mol, charge, mult, eps, run_dir):
    cache_path = os.path.join(run_dir, "_preoptimized_geometry.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            atoms = cached.get("atoms") or []
            if atoms:
                return _mol_with_atoms(mol, atoms), {
                    "source": cached.get("source", "cache"),
                    "message": "사전 최적화 좌표 사용",
                }
        except Exception:
            pass

    for source_key in ("geometry", "heat_of_formation"):
        atoms = _read_out_atoms(os.path.join(run_dir, source_key))
        if atoms:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"source": source_key, "atoms": atoms}, f, ensure_ascii=False)
            return _mol_with_atoms(mol, atoms), {
                "source": source_key,
                "message": "이미 계산된 최적화 좌표 사용",
            }

    base = os.path.join(run_dir, "_preopt_geometry")
    mop_path = base + ".mop"
    inp = mr.build_input(mol, "geometry", charge=charge, mult=mult, eps=eps)
    with open(mop_path, "w", encoding="utf-8") as f:
        f.write(inp)
    rc, stdout = mr.run_mopac(mop_path)
    if not os.path.exists(base + ".out") and stdout:
        with open(base + ".out", "w", encoding="utf-8", errors="ignore") as f:
            f.write(stdout)

    atoms = _read_out_atoms(base)
    if atoms:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"source": "_preopt_geometry", "atoms": atoms}, f, ensure_ascii=False)
        return _mol_with_atoms(mol, atoms), {
            "source": "_preopt_geometry",
            "message": "FORCE 계산 전 geometry 사전 최적화 적용",
        }
    return mol, {
        "source": "input_geometry",
        "message": "사전 최적화 좌표를 얻지 못해 입력 좌표 사용",
        "returncode": rc,
    }


def _run_single_calculation(mol, key, charge=0, mult=1, eps=None, run_dir=None):
    if key not in mr.CALC_TYPES:
        return {"calc_key": key, "status": "error",
                "errors": [f"알 수 없는 계산: {key}"], "label": key}, run_dir
    run_dir = _safe_run_dir(run_dir)
    os.makedirs(run_dir, exist_ok=True)
    base = os.path.join(run_dir, key)
    mop_path = base + ".mop"
    _begin_calculation()
    try:
        calc_mol = mol
        preopt_info = None
        if _needs_stationary_geometry(key):
            calc_mol, preopt_info = _preoptimized_mol(mol, charge, mult, eps, run_dir)
        inp = mr.build_input(calc_mol, key, charge=charge, mult=mult, eps=eps)
        with open(mop_path, "w", encoding="utf-8") as f:
            f.write(inp)
        rc, stdout = mr.run_mopac(mop_path)
        if not os.path.exists(base + ".out") and stdout:
            with open(base + ".out", "w", encoding="utf-8", errors="ignore") as f:
                f.write(stdout)
        res = _assemble_from_files(key, base, run_dir)
        res["input"] = inp
        if preopt_info:
            res["preoptimization"] = preopt_info
            if preopt_info.get("source") != "input_geometry":
                res.setdefault("data", {})["사전최적화"] = preopt_info["message"]
        if rc == -1:
            res["status"] = "error"
            res.setdefault("errors", []).append("실행 시간 초과(timeout).")
        return res, run_dir
    except Exception as e:
        return {"calc_key": key, "label": mr.CALC_TYPES[key]["label"],
                "status": "error", "errors": [f"실행 예외: {e}"]}, run_dir
    finally:
        _end_calculation()


@app.route("/api/files/result", methods=["POST"])
def api_file_result():
    """기존 .out 결과 파일을 계산 결과 카드 데이터로 재구성."""
    data = request.get_json(force=True)
    path = data.get("path", "")
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "파일이 없습니다."}), 400
    base, ext = os.path.splitext(path)
    if ext.lower() != ".out":
        return jsonify({"ok": False, "error": ".out 파일만 결과로 표시할 수 있습니다."}), 400
    key = os.path.basename(base)
    if key not in mr.CALC_TYPES:
        return jsonify({"ok": False, "error": f"알 수 없는 계산 결과 파일입니다: {key}"}), 400
    try:
        res = _assemble_from_files(key, base, os.path.dirname(base))
        return jsonify({"ok": True, "results": [res]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/files/save", methods=["POST"])
def api_save():
    data = request.get_json(force=True)
    name = data.get("name", "molecule").strip() or "molecule"
    name = "".join(c for c in name if c not in '\\/:*?"<>|')
    xyz = data.get("xyz", "")
    molblock = data.get("molblock")
    mol_path = None
    if molblock is not None:
        if not isinstance(molblock, str) or len(molblock) > 2_000_000:
            return jsonify({"ok": False, "error": "MOL 파일 크기/형식 오류"}), 400
        from rdkit import Chem
        parsed = Chem.MolFromMolBlock(molblock, removeHs=False)
        if parsed is None or parsed.GetNumConformers() == 0:
            return jsonify({"ok": False, "error": "MOL 구조 또는 결합 정보가 유효하지 않습니다."}), 400
        mol_path = os.path.join(WORKSPACE, name + ".mol")
        with open(mol_path, "w", encoding="utf-8") as f:
            f.write(Chem.MolToMolBlock(parsed))
    path = os.path.join(WORKSPACE, name + ".xyz")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xyz)
    return jsonify({"ok": True, "path": path, "mol_path": mol_path})


@app.route("/api/draw", methods=["POST"])
def api_draw():
    """Avogadro 실행 (3D로 구조 그리기). 저장은 워크스페이스에 하도록 안내."""
    if not os.path.exists(AVOGADRO):
        return jsonify({"ok": False, "error": "Avogadro를 찾을 수 없습니다."}), 400
    try:
        subprocess.Popen([AVOGADRO], cwd=WORKSPACE)
        return jsonify({"ok": True, "msg": f"Avogadro 실행됨. 구조를 그린 뒤 '{WORKSPACE}' 에 .xyz/.mol 로 저장하세요."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    data = request.get_json(force=True)
    mol = data.get("mol")
    calc_keys = data.get("calc_keys", [])
    charge = int(data.get("charge", 0))
    mult = int(data.get("mult", 1))
    eps = data.get("eps")
    if not mol or not calc_keys:
        return jsonify({"ok": False, "error": "분자 또는 계산 종류가 없습니다."}), 400

    run_dir = _safe_run_dir(data.get("run_dir"))
    os.makedirs(run_dir, exist_ok=True)
    results = []
    for key in calc_keys:
        res, run_dir = _run_single_calculation(mol, key, charge, mult, eps, run_dir)
        results.append(res)
    return jsonify({"ok": True, "results": results, "run_dir": run_dir})


@app.route("/api/calculate_one", methods=["POST"])
def api_calculate_one():
    data = request.get_json(force=True)
    mol = data.get("mol")
    key = data.get("calc_key")
    charge = int(data.get("charge", 0))
    mult = int(data.get("mult", 1))
    eps = data.get("eps")
    if not mol or not key:
        return jsonify({"ok": False, "error": "분자 또는 계산 종류가 없습니다."}), 400
    try:
        res, run_dir = _run_single_calculation(
            mol, key, charge=charge, mult=mult, eps=eps, run_dir=data.get("run_dir"))
        return jsonify({"ok": True, "result": res, "run_dir": run_dir})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/cube", methods=["POST"])
def api_cube():
    """선택한 분자 오비탈의 cube 데이터를 생성해 반환."""
    data = request.get_json(force=True)
    mgf_path = data.get("mgf_path", "")
    orb = int(data.get("orbital_index", 0))
    spacing = float(data.get("spacing", 0.16))
    if not os.path.isfile(mgf_path):
        return jsonify({"ok": False, "error": ".mgf 파일을 찾을 수 없습니다."}), 400
    try:
        with open(mgf_path, "r", encoding="utf-8", errors="ignore") as f:
            mgf = mo_cube.parse_mgf(f.read())
        cube, maxabs = mo_cube.generate_cube(mgf, orb, spacing=spacing)
        # The MGF coordinates are the exact coordinates used for the MO basis.
        # A separately parsed .out geometry might be centered/rotated differently.
        from rdkit import Chem
        pt = Chem.GetPeriodicTable()
        atoms = [
            {"symbol": pt.GetElementSymbol(int(atomic_number)),
             "x": float(x), "y": float(y), "z": float(z)}
            for atomic_number, x, y, z in mgf["atoms"]
        ]
        return jsonify({"ok": True, "cube": cube, "maxabs": maxabs,
                        "atoms": atoms, "unit": "angstrom"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


def select_available_port(start=5005, end=5030):
    """Do not accidentally open a stale Studio at the same listening port."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("5005~5029 포트가 모두 사용 중입니다. 이전 서버를 종료하세요.")


if __name__ == "__main__":
    import webbrowser
    import threading
    port = select_available_port()
    start_idle_shutdown_monitor(timeout_s=90)
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"\n  MOPAC Studio  ->  http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
