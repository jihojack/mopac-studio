# -*- coding: utf-8 -*-
"""MOPAC 입력 생성 / 실행 / 결과 파싱 모듈.

22가지 계산 종류를 MOPAC 키워드로 매핑하고, 각각을 실행한 뒤
출력(.out / .aux)을 파싱한다. 실패한 계산은 결과에 error 플래그를 단다.
"""
import os
import re
import subprocess
import shutil
import threading
import time
from engine_setup import managed_executable
from element_data import unsupported_elements

HERE = os.path.dirname(os.path.abspath(__file__))


def find_mopac():
    """Explicit configuration, existing portable layout, then system PATH."""
    configured = os.environ.get("MOPAC_EXE", "").strip().strip('"')
    if configured:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(configured)))
    managed = managed_executable(HERE)
    if managed is not None and os.path.isfile(managed):
        return str(managed)
    portable = [os.path.join(HERE, "..", "mopac2016", "MOPAC2016.exe"),
                os.path.join(HERE, "mopac2016", "MOPAC2016.exe")]
    for candidate in portable:
        if os.path.isfile(candidate):
            return os.path.normpath(candidate)
    for command in ("MOPAC2016.exe", "mopac.exe", "mopac"):
        found = shutil.which(command)
        if found:
            return found
    return os.path.normpath(portable[0])


MOPAC_EXE = find_mopac()
MOPAC_DIR = os.path.dirname(MOPAC_EXE)

DEFAULT_HAMILTONIAN = "PM7"

# ---------------------------------------------------------------------------
# 계산 종류 정의
#   key       : 내부 식별자
#   label     : UI 표시명(한글)
#   keywords  : MOPAC 키워드 (해밀토니안 제외, 앞에 자동 추가됨)
#   optimize  : True면 좌표 최적화(flag=1), False면 고정(flag=0)
#   needs_aux : MO 계수 등 AUX 출력 필요 여부
#   note      : 제약/주의 (없으면 None)
# ---------------------------------------------------------------------------
CALC_TYPES = {
    "heat_of_formation": dict(
        label="생성엔탈피 ΔHf", keywords="PRECISE", optimize=True),
    "zpe_entropy": dict(
        label="영점에너지 · 엔트로피", keywords="PRECISE FORCE LET THERMO", optimize=True),
    "heat_capacity": dict(
        label="열용량 Cp", keywords="PRECISE FORCE LET THERMO", optimize=True),
    "ionization": dict(
        label="이온화 에너지 (IP)", keywords="PRECISE", optimize=True),
    "electron_affinity": dict(
        label="전자친화도 (EA, −LUMO 근사)", keywords="PRECISE", optimize=True),
    "geometry": dict(
        label="평형 분자 구조 (결합길이/각)", keywords="PRECISE", optimize=True),
    "bond_orders": dict(
        label="화학 결합 차수 (BOND ORDERS)", keywords="PRECISE BONDS", optimize=True),
    "transition_state": dict(
        label="전이상태 (TS) 구조", keywords="TS BONDS", optimize=False,
        note="전이상태에 가까운 초기 구조가 필요합니다."),
    "irc": dict(
        label="내부 반응 좌표 (IRC)", keywords="IRC=1 LARGE LET", optimize=False,
        note="IRC는 전이상태 구조에서 반응 경로를 추적하는 계산입니다."),
    "molecular_orbitals": dict(
        label="분자 오비탈 (HOMO/LUMO 3D)", keywords="PRECISE VECTORS GRAPHF AUX",
        optimize=True, needs_aux=True),
    "atomic_charges": dict(
        label="원자 전하 (ESP · Mulliken)", keywords="PRECISE ESP MULLIK", optimize=True),
    "dipole": dict(
        label="쌍극자 모멘트", keywords="PRECISE", optimize=True),
    "magnetic": dict(
        label="자기 특성 (스핀밀도 · 초미세결합)", keywords="UHF HYPERFINE", optimize=True,
        open_shell=True, note="라디칼/열린껍질 분자에서 의미가 있습니다."),
    "localized_orbitals": dict(
        label="국소화 오비탈 (Localize)", keywords="PRECISE LOCALIZE", optimize=True),
    "vibrations": dict(
        label="진동 주파수 · IR 스펙트럼", keywords="PRECISE FORCE LET", optimize=True),
    "force_constants": dict(
        label="힘 상수", keywords="PRECISE FORCE LET", optimize=True),
    "isotope": dict(
        label="동위원소 치환 효과", keywords="PRECISE FORCE LET THERMO", optimize=True),
    "nlo": dict(
        label="비선형 광학 (분극성 α,β,γ)", keywords="PRECISE POLAR", optimize=True),
    "solvation": dict(
        label="용매화 자유에너지 (COSMO)", keywords="PRECISE EPS=78.4 RSOLV=1.3", optimize=True),
    "pka": dict(
        label="pKa 예측 (PM6)", keywords="PRECISE PKA", optimize=True, hamiltonian="PM6",
        note="MOPAC PKA는 주로 O-H 산성 수소가 있는 분자에서 의미가 있습니다."),
    "superdeloc": dict(
        label="초비편재화도 (반응성 지수)", keywords="PRECISE SUPER", optimize=True),
    "thermochemistry": dict(
        label="열화학 전체 (ΔH·S·Cp·G)", keywords="PRECISE FORCE LET THERMO", optimize=True),
}


def list_calc_types():
    out = []
    for k, v in CALC_TYPES.items():
        out.append({"key": k, "label": v["label"], "note": v.get("note")})
    return out


# ---------------------------------------------------------------------------
# 입력 생성
# ---------------------------------------------------------------------------
def build_input(mol_dict, calc_key, charge=0, mult=1, eps=None):
    spec = CALC_TYPES[calc_key]
    missing = unsupported_elements(mol_dict)
    if missing:
        raise ValueError('기본 PM6/PM7 계산을 지원하지 않는 원소입니다: ' + ', '.join(missing) +
                         '. 표시·편집·내보내기는 가능합니다. 이 계산 옵션은 SPARKLE/더미 원자를 사용하지 않습니다.')
    kw = [spec.get("hamiltonian", DEFAULT_HAMILTONIAN), spec["keywords"]]
    if charge:
        kw.append(f"CHARGE={charge}")
    # 스핀 다중도
    mult_map = {2: "DOUBLET", 3: "TRIPLET", 4: "QUARTET", 5: "QUINTET"}
    if mult in mult_map:
        kw.append(mult_map[mult])
        if "UHF" not in spec["keywords"]:
            kw.append("UHF")
    if calc_key == "solvation" and eps:
        kw = [w for w in kw if not w.startswith("EPS=")]
        kw.append(f"EPS={eps}")
    keyword_line = " ".join(" ".join(kw).split())
    words = keyword_line.upper().split()
    if ("FORCE" in words or any(w.startswith("IRC") for w in words)) and "LET" not in words:
        keyword_line += " LET"

    flag = 1 if spec.get("optimize", True) else 0
    lines = [keyword_line, mol_dict.get("name", "molecule"), "MOPAC Studio"]
    for a in mol_dict["atoms"]:
        lines.append(
            f"{a['symbol']:<2} {a['x']:>14.8f} {flag} {a['y']:>14.8f} {flag} {a['z']:>14.8f} {flag}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def run_mopac(mop_path, timeout=600):
    """MOPAC 실행. (returncode, stdout) 반환. Legacy Windows GUI도 지원."""
    if not os.path.exists(MOPAC_EXE):
        raise FileNotFoundError(
            f"MOPAC 실행 파일을 찾을 수 없습니다: {MOPAC_EXE}. "
            "Install.bat 또는 python launcher.py --setup-only로 공식 MOPAC을 자동 설치하세요. "
            "설정 방법은 README.md를 확인하세요.")
    env = os.environ.copy()
    env["PATH"] = MOPAC_DIR + os.pathsep + env.get("PATH", "")
    legacy_gui = os.name == "nt" and os.path.basename(MOPAC_EXE).lower() == "mopac2016.exe"
    if legacy_gui:
        try:
            return _run_mopac_hidden_desktop(mop_path, env, timeout)
        except Exception as hidden_error:
            print(f"MOPAC hidden desktop fallback: {hidden_error}")
    popen_opts = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        popen_opts["startupinfo"] = startupinfo
        popen_opts["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        [MOPAC_EXE, mop_path], cwd=os.path.dirname(mop_path), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="ignore",
        **popen_opts)
    hide_stop = None
    hide_thread = None
    if legacy_gui:
        hide_stop = threading.Event()
        hide_thread = threading.Thread(
            target=_hide_windows_while_running,
            args=(proc.pid, hide_stop),
            daemon=True)
        hide_thread.start()
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return -1, "TIMEOUT"
        return proc.returncode, (stdout or "") + (stderr or "")
    finally:
        if hide_stop is not None:
            hide_stop.set()
        if hide_thread is not None:
            hide_thread.join(timeout=0.3)


def _run_mopac_hidden_desktop(mop_path, env, timeout):
    """Run the MOPAC GUI process on an invisible Windows desktop."""
    import ctypes
    from ctypes import wintypes

    class StartupInfo(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class ProcessInformation(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.CreateDesktopW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    ]
    user32.CreateDesktopW.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID,
        wintypes.BOOL, wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR,
        ctypes.POINTER(StartupInfo), ctypes.POINTER(ProcessInformation),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    desktop_name = f"MopacStudioHidden_{os.getpid()}_{int(time.time() * 1000)}"
    desktop_all_access = 0x000F01FF
    desktop = user32.CreateDesktopW(desktop_name, None, None, 0, desktop_all_access, None)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())

    pi = ProcessInformation()
    si = StartupInfo()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = f"WinSta0\\{desktop_name}"
    si.dwFlags = subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    command_line = subprocess.list2cmdline([MOPAC_EXE, mop_path])
    command_buffer = ctypes.create_unicode_buffer(command_line)
    env_block = ctypes.create_unicode_buffer(_make_windows_env_block(env))
    create_unicode_environment = 0x00000400
    wait_timeout = 0x00000102
    infinite = 0xFFFFFFFF
    try:
        ok = kernel32.CreateProcessW(
            MOPAC_EXE,
            command_buffer,
            None,
            None,
            False,
            create_unicode_environment,
            ctypes.cast(env_block, wintypes.LPVOID),
            os.path.dirname(mop_path),
            ctypes.byref(si),
            ctypes.byref(pi),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        wait_ms = infinite if timeout is None else int(timeout * 1000)
        wait_result = kernel32.WaitForSingleObject(pi.hProcess, wait_ms)
        if wait_result == wait_timeout:
            kernel32.TerminateProcess(pi.hProcess, 1)
            return -1, "TIMEOUT"
        exit_code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(exit_code))
        return int(exit_code.value), ""
    finally:
        if pi.hThread:
            kernel32.CloseHandle(pi.hThread)
        if pi.hProcess:
            kernel32.CloseHandle(pi.hProcess)
        user32.CloseDesktop(desktop)


def _make_windows_env_block(env):
    return "\0".join(f"{k}={v}" for k, v in sorted(env.items(), key=lambda x: x[0].upper())) + "\0\0"


def _hide_windows_while_running(pid, stop_event):
    """Hide MOPAC-owned windows, including child GUI windows that ignore STARTUPINFO."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    enum_windows = user32.EnumWindows
    enum_windows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
                             wintypes.LPARAM]
    enum_windows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    query_full_process_image_name = kernel32.QueryFullProcessImageNameW
    query_full_process_image_name.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                              wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]

    process_query_limited = 0x1000
    sw_hide = 0

    def process_name(window_pid):
        handle = open_process(process_query_limited, False, window_pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(len(buf))
            if query_full_process_image_name(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
            return ""
        finally:
            close_handle(handle)

    def window_title(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def is_mopac_window(name, title, window_pid):
        if window_pid == pid or name.startswith("MOPAC"):
            return True
        title = title.upper().strip()
        if title.startswith(("MOPAC20", "MOPAC2016")):
            return "MOPAC STUDIO" not in title
        return False

    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def hide_once():
        def callback(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            name = process_name(window_pid.value).upper()
            title = window_title(hwnd)
            if is_mopac_window(name, title, window_pid.value):
                user32.ShowWindowAsync(hwnd, sw_hide)
                user32.ShowWindow(hwnd, sw_hide)
            return True
        enum_windows(callback_type(callback), 0)

    while not stop_event.is_set():
        hide_once()
        time.sleep(0.05)


# ---------------------------------------------------------------------------
# 파서 헬퍼
# ---------------------------------------------------------------------------
ERROR_PATTERNS = [
    r"SCF CALCULATION FAILED",
    r"UNABLE TO ACHIEVE SELF-CONSISTENCE",
    r"GEOMETRY OPTIMIZATION FAILED",
    r"EXCESS NUMBER OF OPTIMIZATION CYCLES",
    r"NOT ENOUGH TIME",
    r"FOR SOME REASON THE \w+ METHOD WAS UNABLE",
    r"JOB WAS STOPPED",
    r"FATAL",
    r"\*\s*ERROR\s*\*",
    r"IS AN UNRECOGNIZED",
    r"UNRECOGNIZED KEY-WORDS?",
    r"TS\b.*FAILED",
    r"GRADIENT IS TOO LARGE",
]


def detect_errors(out_text):
    errs = []
    for pat in ERROR_PATTERNS:
        for m in re.finditer(pat, out_text, re.IGNORECASE):
            line = out_text[max(0, m.start() - 0):m.end() + 80].splitlines()[0].strip()
            errs.append(line)
    # 정상 종료 여부
    finished = "JOB ENDED NORMALLY" in out_text or "== MOPAC DONE ==" in out_text
    return list(dict.fromkeys(errs)), finished


def _f(pattern, text, group=1, flags=0):
    m = re.search(pattern, text, flags)
    if m:
        try:
            return float(m.group(group))
        except (ValueError, IndexError):
            return m.group(group)
    return None


def parse_common(text):
    """모든 계산에 공통인 기본 물성."""
    d = {}
    num = r"[-+]?\d+(?:\.\d+)?"
    hof = re.search(
        rf"(?:FINAL\s+)?HEAT OF FORMATION\s*=\s*({num})\s*KCAL\S*(?:\s*=\s*({num})\s*KJ)?",
        text, re.IGNORECASE)
    if hof:
        d["heat_of_formation_kcal"] = float(hof.group(1))
        if hof.group(2) is not None:
            d["heat_of_formation_kj"] = float(hof.group(2))
    d["ionization_ev"] = _f(r"IONIZATION POTENTIAL\s*=\s*(-?\d+\.\d+)", text)
    hl = re.search(r"HOMO LUMO ENERGIES \(EV\)\s*=\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)", text)
    if hl:
        d["homo_ev"] = float(hl.group(1))
        d["lumo_ev"] = float(hl.group(2))
    d["total_energy_ev"] = _f(r"TOTAL ENERGY\s*=\s*(-?\d+\.\d+)\s*EV", text)
    d["point_group"] = _f(r"MOLECULAR POINT GROUP\s*:\s*(\S+)", text)
    d["cpu_time_s"] = _f(r"TOTAL JOB TIME:\s*(\d+\.\d+)", text)
    # 쌍극자: DIPOLE 표의 'SUM' 행 마지막 값
    dip = re.search(r"DIPOLE\s+X\s+Y\s+Z\s+TOTAL.*?SUM\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)",
                    text, re.DOTALL)
    if dip:
        d["dipole"] = {"x": float(dip.group(1)), "y": float(dip.group(2)),
                       "z": float(dip.group(3)), "total": float(dip.group(4))}
    return {k: v for k, v in d.items() if v is not None}


def parse_optimized_geometry(text):
    """최적화된 Cartesian 좌표 추출 (CARTESIAN COORDINATES 블록)."""
    atoms = []
    # 'CARTESIAN COORDINATES' 마지막 블록
    blocks = list(re.finditer(
        r"CARTESIAN COORDINATES\s*\n(?:\s*NO\.\s+ATOM\s+X\s+Y\s+Z\s*\n)?((?:\s+\d+\s+[A-Za-z]{1,2}\s+-?\d+\.\d+\s+-?\d+\.\d+\s+-?\d+\.\d+\s*\n)+)",
        text))
    if blocks:
        body = blocks[-1].group(1)
        for ln in body.strip().splitlines():
            p = ln.split()
            if len(p) >= 5:
                atoms.append({"symbol": p[1], "x": float(p[2]),
                              "y": float(p[3]), "z": float(p[4])})
    return atoms


def parse_charges(text):
    charges = []
    m = re.search(r"NET ATOMIC CHARGES.*?\n(.*?)(?:\n\s*\n|\Z)", text, re.DOTALL)
    if m:
        for ln in m.group(1).splitlines():
            p = ln.split()
            # 형식: ATOM_NO  ELEMENT  CHARGE  ...
            if len(p) >= 3 and p[0].isdigit():
                try:
                    charges.append({"idx": int(p[0]), "symbol": p[1],
                                    "charge": float(p[2])})
                except ValueError:
                    pass
    return charges


def parse_frequencies(text):
    """모든 진동수(축퇴 포함)를 'NORMAL COORDINATE ANALYSIS' 의 Root No. 표에서 추출."""
    freqs = []
    # MASS-WEIGHTED 섹션은 동일 진동수 중복이므로 첫 NORMAL COORDINATE 섹션만 사용
    start = text.find("NORMAL COORDINATE ANALYSIS")
    end = text.find("MASS-WEIGHTED COORDINATE ANALYSIS")
    section = text[start:end] if start >= 0 and end > start else text[start:] if start >= 0 else text
    lines = section.splitlines()
    for i, ln in enumerate(lines):
        if "Root No." in ln:
            n_roots = len(re.findall(r"\d+", ln.split("Root No.")[1]))
            # 헤더 아래에서 '숫자만으로 이루어진' 첫 줄 = 진동수 행
            for j in range(i + 1, min(i + 6, len(lines))):
                toks = lines[j].split()
                if toks and all(re.fullmatch(r"-?\d+\.\d+", t) for t in toks):
                    freqs.extend(float(t) for t in toks)
                    break
    if not freqs:  # 폴백: FREQUENCY 설명 라인
        for m in re.finditer(r"FREQUENCY\s+(-?\d+\.\d+)", text):
            freqs.append(float(m.group(1)))
    return freqs


def parse_thermo(text):
    """THERMO 표에서 ZPE / 엔트로피 / 열용량 추출."""
    d = {}
    d["zero_point_energy_kcal"] = _f(r"ZERO POINT ENERGY\s+(\d+\.\d+)\s*KCAL", text) \
        or _f(r"ZERO POINT ENERGY\s*=?\s*(\d+\.\d+)", text)
    # THERMODYNAMIC 표: 'TEMP. (K)  PARTITION FUNCTION  H.O.F.  ENTHALPY  HEAT CAPACITY  ENTROPY'
    rows = []
    for m in re.finditer(
            r"^\s*(\d+\.\d+)\s+([\d.E+-]+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)",
            text, re.MULTILINE):
        rows.append({"T": float(m.group(1)), "Cp": float(m.group(5)),
                     "S": float(m.group(6))})
    # 298.15 K 근처 값
    if rows:
        target = min(rows, key=lambda r: abs(r["T"] - 298.15))
        d["heat_capacity_298"] = target["Cp"]
        d["entropy_298"] = target["S"]
        d["thermo_table"] = rows[:50]
    return {k: v for k, v in d.items() if v is not None}


def parse_bond_orders(text):
    bonds = []
    m = re.search(r"\(VALENCIES\)\s+BOND ORDERS(.*?)(?:\n\s*\*{5,}|\Z)", text, re.DOTALL)
    if m:
        atom_line = re.compile(r"^\s*(\d+)\s+([A-Za-z]{1,2})\s+\(([-+]?\d+\.\d+)\)\s+(.*)$")
        partner = re.compile(r"(\d+)\s+([A-Za-z]{1,2})\s+([-+]?\d+\.\d+)")
        seen = set()
        for ln in m.group(1).splitlines():
            lm = atom_line.match(ln)
            if not lm:
                continue
            i = int(lm.group(1))
            sym_i = lm.group(2)
            valence = float(lm.group(3))
            for pm in partner.finditer(lm.group(4)):
                j = int(pm.group(1))
                sym_j = pm.group(2)
                pair = tuple(sorted((i, j)))
                if pair in seen:
                    continue
                seen.add(pair)
                bonds.append({"a": f"{sym_i}{i}", "b": f"{sym_j}{j}",
                              "order": float(pm.group(3)), "valence_a": valence})
    return bonds


def parse_polar(text):
    d = {}
    d["polarizability_alpha"] = _f(r"ISOTROPIC AVERAGE ALPHA\s*=?\s*(-?\d+\.\d+)", text) \
        or _f(r"AVERAGE POLARIZABILITY\s*=?\s*(-?\d+\.\d+)", text)
    d["beta"] = _f(r"BETA\s+TOTAL\s*=?\s*(-?\d+\.\d+)", text)
    d["gamma"] = _f(r"GAMMA\s+TOTAL\s*=?\s*(-?\d+\.\d+)", text)
    return {k: v for k, v in d.items() if v is not None}


def parse_cosmo(text):
    d = {}
    d["dielectric_energy_ev"] = _f(r"DIELECTRIC ENERGY\s*=\s*(-?\d+\.\d+)", text)
    d["cosmo_area_a2"] = _f(r"COSMO AREA\s*=?\s*(-?\d+\.\d+)", text)
    d["cosmo_volume_a3"] = _f(r"COSMO VOLUME\s*=?\s*(-?\d+\.\d+)", text)
    return {k: v for k, v in d.items() if v is not None}


def parse_pka(text):
    """PM6 PKA 표( 'Atom  pKa' )에서 (원자번호, pKa) 추출."""
    m = re.search(r"Sorted by atom(.*?)(?:\n\s*\n|\Z)", text, re.DOTALL | re.IGNORECASE)
    rows = []
    block = m.group(1) if m else text
    for rm in re.finditer(r"^\s*(\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(-?\d+\.\d+)\s*$",
                          block, re.MULTILINE):
        rows.append({"atom": int(rm.group(1)), "pKa": float(rm.group(2))})
    if not rows:
        # 단순 'pKa = x' 형태 대비
        v = _f(r"pKa\s*=\s*(-?\d+\.\d+)", text)
        if v is not None:
            rows.append({"atom": None, "pKa": v})
    return rows or None


def parse_spin(text):
    spins = []
    m = re.search(r"ATOMIC ORBITAL SPIN POPULATIONS(.*?)(?:\n\s*\n|\Z)", text, re.DOTALL)
    if m:
        for sm in re.finditer(r"^\s*(\d+)\s+([A-Za-z]{1,2})\s+(-?\d+\.\d+)", m.group(1), re.MULTILINE):
            spins.append({"idx": int(sm.group(1)), "symbol": sm.group(2),
                          "spin": float(sm.group(3))})
    return spins


def parse_mo_aux(aux_text):
    """AUX 파일에서 MO 에너지와 계수를 추출."""
    d = {}
    # MO 에너지
    m = re.search(r"EIGENVALUES\[\d+\]=\s*\n?(.*?)(?:\n\s*[A-Z_]+\[|\Z)", aux_text, re.DOTALL)
    if m:
        nums = re.findall(r"-?\d+\.\d+E?[+-]?\d*", m.group(1))
        d["mo_energies"] = [float(x) for x in nums]
    # 점유 전자 수로 HOMO 인덱스 추정
    occ = re.search(r"MOLECULAR_ORBITAL_OCCUPANCIES\[\d+\]=\s*\n?(.*?)(?:\n\s*[A-Z_]+\[|\Z)",
                    aux_text, re.DOTALL)
    if occ:
        occs = [float(x) for x in re.findall(r"\d+\.\d+", occ.group(1))]
        n_occ = sum(1 for o in occs if o > 0.5)
        d["homo_index"] = n_occ - 1
        d["lumo_index"] = n_occ
    return d


# ---------------------------------------------------------------------------
# 종류별 결과 조립
# ---------------------------------------------------------------------------
def assemble_result(calc_key, out_text, aux_text=""):
    spec = CALC_TYPES[calc_key]
    errs, finished = detect_errors(out_text)
    result = {"calc_key": calc_key, "label": spec["label"],
              "note": spec.get("note"), "errors": errs,
              "finished": finished, "data": {}}

    common = parse_common(out_text)
    data = result["data"]

    if calc_key == "heat_of_formation":
        data["생성엔탈피_kcal_mol"] = common.get("heat_of_formation_kcal")
        data["생성엔탈피_kj_mol"] = common.get("heat_of_formation_kj")
    elif calc_key in ("zpe_entropy", "heat_capacity", "isotope"):
        data.update(parse_thermo(out_text))
        data["생성엔탈피_kcal_mol"] = common.get("heat_of_formation_kcal")
    elif calc_key == "ionization":
        data["이온화에너지_eV"] = common.get("ionization_ev")
        data["HOMO_eV"] = common.get("homo_ev")
    elif calc_key == "electron_affinity":
        # EA ≈ -E(LUMO) (Koopmans 근사)
        if "lumo_ev" in common:
            data["전자친화도_eV_Koopmans근사"] = -common["lumo_ev"]
        data["LUMO_eV"] = common.get("lumo_ev")
    elif calc_key == "geometry":
        atoms = parse_optimized_geometry(out_text)
        data["optimized_atoms"] = atoms
        data["internal"] = compute_internal_coords(atoms)
    elif calc_key == "bond_orders":
        bonds = parse_bond_orders(out_text)
        data["bond_orders"] = bonds
        data["mulliken_bond_orders"] = bonds
    elif calc_key in ("transition_state", "irc"):
        data["생성엔탈피_kcal_mol"] = common.get("heat_of_formation_kcal")
        data["optimized_atoms"] = parse_optimized_geometry(out_text)
        # 활성화 에너지/경로는 출력 가용시
        data["gradient_norm"] = _f(r"GRADIENT NORM\s*=\s*(-?\d+\.\d+)", out_text)
    elif calc_key == "molecular_orbitals":
        data.update({k: common.get(k) for k in ("homo_ev", "lumo_ev") if k in common})
        data["optimized_atoms"] = parse_optimized_geometry(out_text)
        if aux_text:
            data.update(parse_mo_aux(aux_text))
        if "homo_ev" in common and "lumo_ev" in common:
            data["gap_eV"] = round(common["lumo_ev"] - common["homo_ev"], 4)
    elif calc_key == "atomic_charges":
        data["charges"] = parse_charges(out_text)
        data["dipole"] = common.get("dipole")
    elif calc_key == "dipole":
        data["dipole"] = common.get("dipole")
    elif calc_key == "magnetic":
        spins = parse_spin(out_text)
        if spins:
            data["spin_density"] = spins
        else:
            data["스핀밀도"] = "해당 없음 또는 0에 가까움 (닫힌껍질 분자는 보통 미출력)"
    elif calc_key == "localized_orbitals":
        data["localized_found"] = "LOCALIZED" in out_text.upper()
        n = len(re.findall(r"LOCALIZED ORBITAL", out_text, re.IGNORECASE))
        data["localized_orbital_count"] = n or None
    elif calc_key in ("vibrations", "force_constants"):
        freqs = parse_frequencies(out_text)
        data["frequencies_cm1"] = freqs
        data["imaginary_modes"] = [f for f in freqs if f < 0]
        data["n_modes"] = len(freqs)
    elif calc_key == "nlo":
        data.update(parse_polar(out_text))
    elif calc_key == "solvation":
        data.update(parse_cosmo(out_text))
        data["생성엔탈피_용매중_kcal_mol"] = common.get("heat_of_formation_kcal")
    elif calc_key == "pka":
        rows = parse_pka(out_text)
        if rows:
            data["최소_pKa"] = min(r["pKa"] for r in rows)
            data["pKa_per_atom"] = rows
        else:
            up = out_text.upper()
            if "NO '-O-H' GROUPS FOUND" in up or "PKA CANNOT BE CALCULATED" in up:
                data["pKa"] = "해당 없음 (-O-H 산성 수소 없음)"
            else:
                data["pKa"] = "출력 없음"
    elif calc_key == "superdeloc":
        nuc = _f(r"NUCLEOPHILIC.*?(-?\d+\.\d+)", out_text)
        elec = _f(r"ELECTROPHILIC.*?(-?\d+\.\d+)", out_text)
        if nuc is not None:
            data["nucleophilic_superdeloc"] = nuc
        if elec is not None:
            data["electrophilic_superdeloc"] = elec
        has_super = "SUPERDELOCALIZABILIT" in out_text.upper()
        data["has_superdeloc"] = has_super
        if has_super and nuc is None and elec is None:
            data["superdeloc_status"] = "SUPER 출력은 있으나 요약 수치가 없습니다."
    elif calc_key == "thermochemistry":
        data.update(parse_thermo(out_text))
        data["생성엔탈피_kcal_mol"] = common.get("heat_of_formation_kcal")
        data["entropy_298_cal_molK"] = data.get("entropy_298")

    # 항상 공통 물성도 첨부
    result["common"] = common

    # 결과 검증: 핵심 값이 없으면 에러로 마킹
    if not finished and not errs:
        errs.append("계산이 정상 종료되지 않았습니다 (JOB ENDED NORMALLY 누락).")
    has_real = any(v not in (None, [], {}, "") for v in data.values())
    if not has_real and not errs:
        errs.append("요청한 물성을 출력에서 찾지 못했습니다.")
    result["errors"] = errs
    result["status"] = "error" if errs else "ok"
    return result


def compute_internal_coords(atoms):
    """결합길이/각/이면각 일부를 계산 (가까운 원자쌍 기준)."""
    import math
    n = len(atoms)
    if n < 2:
        return {}
    def d(i, j):
        a, b = atoms[i], atoms[j]
        return math.sqrt((a["x"]-b["x"])**2 + (a["y"]-b["y"])**2 + (a["z"]-b["z"])**2)
    # 결합: 거리 < 1.8 Å (대략) 인 쌍
    bonds = []
    for i in range(n):
        for j in range(i+1, n):
            dist = d(i, j)
            if dist < 1.9:
                bonds.append({"pair": f"{atoms[i]['symbol']}{i+1}-{atoms[j]['symbol']}{j+1}",
                              "length_A": round(dist, 4)})
    return {"bond_lengths": bonds[:60]}


def cleanup_aux(base):
    """부수 파일 경로 모음."""
    return {ext: base + ext for ext in (".out", ".arc", ".aux", ".mgf")
            if os.path.exists(base + ext)}
