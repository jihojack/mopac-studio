# -*- coding: utf-8 -*-
"""MOPAC GRAPHF(.mgf) -> Gaussian cube 변환 (분자 오비탈 3D 등가면용).

MOPAC의 .mgf 그래픽 파일에는 원자좌표, 각 원자의 Slater 지수(zs,zp,zd),
각 분자오비탈의 LCAO 계수(직교화 기저), 그리고 역행렬이 들어있다.
Jmol과 동일하게 역행렬로 계수를 비직교(실제 Slater) 기저로 되돌린 뒤
격자에서 파동함수를 평가하여 cube 파일을 만든다.
"""
import math
import re
import numpy as np

BOHR = 0.529177210903  # Å per Bohr

# 주기(행) -> 주양자수 n (s,p 용)
def _n_for_Z(Z):
    if Z <= 2:
        return 1
    if Z <= 10:
        return 2
    if Z <= 18:
        return 3
    if Z <= 36:
        return 4
    if Z <= 54:
        return 5
    return 6


def parse_mgf(text):
    lines = text.splitlines()
    natoms = int(lines[0].split()[0])
    atoms = []          # (Z, x, y, z) Å
    idx = 1
    for i in range(natoms):
        p = lines[idx].split(); idx += 1
        atoms.append((int(p[0]), float(p[1]), float(p[2]), float(p[3])))
    exps = []           # (zs, zp, zd)
    for i in range(natoms):
        p = lines[idx].split(); idx += 1
        exps.append((float(p[0]), float(p[1]), float(p[2])))

    # 기저함수 목록 구성: (atom_index, kind)  kind in s,px,py,pz,dz2,dxz,dyz,dx2y2,dxy
    basis = []
    for ai, (zs, zp, zd) in enumerate(exps):
        basis.append((ai, "s", zs))
        if abs(zp) > 1e-9:
            for k in ("px", "py", "pz"):
                basis.append((ai, k, zp))
        if abs(zd) > 1e-9:
            for k in ("dx2y2", "dxz", "dz2", "dyz", "dxy"):
                basis.append((ai, k, zd))
    nbf = len(basis)

    # ORBITAL 블록 파싱
    orbitals = []   # dict(occ,label,energy,coef[list])
    i = idx
    inv_start = None
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("ORBITAL"):
            m = re.match(r"\s*ORBITAL\s+(\d+)\s+(\S+)\s+(-?\d+\.\d+)", ln)
            occ = int(m.group(1)); label = m.group(2); energy = float(m.group(3))
            coefs = []
            i += 1
            while len(coefs) < nbf and i < len(lines):
                nums = re.findall(r"-?\d\.\d+D[+-]\d+", lines[i])
                if not nums:
                    break
                coefs.extend(float(x.replace("D", "E")) for x in nums)
                i += 1
            orbitals.append({"occ": occ, "label": label, "energy": energy,
                             "coef": np.array(coefs[:nbf])})
            continue
        if "INVERSE_MATRIX" in ln:
            inv_start = i
            break
        i += 1

    # 역행렬 (하삼각, 대칭)
    inv = np.eye(nbf)
    if inv_start is not None:
        vals = []
        for ln in lines[inv_start + 1:]:
            if ln.strip().startswith("Keywords") or not ln.strip():
                break
            nums = re.findall(r"-?\d\.\d+D[+-]\d+", ln)
            if not nums:
                break
            vals.extend(float(x.replace("D", "E")) for x in nums)
        # 하삼각 채우기
        M = np.eye(nbf)
        k = 0
        ok = True
        for r in range(nbf):
            for c in range(r + 1):
                if k >= len(vals):
                    ok = False; break
                M[r, c] = vals[k]; M[c, r] = vals[k]; k += 1
            if not ok:
                break
        if ok:
            inv = M

    return {"atoms": atoms, "exps": exps, "basis": basis, "nbf": nbf,
            "orbitals": orbitals, "inv": inv}


def orbital_list(mgf):
    """오비탈 메타데이터(인덱스/라벨/에너지/HOMO·LUMO 표시)."""
    occs = [o["occ"] for o in mgf["orbitals"]]
    homo = max((i for i, o in enumerate(occs) if o > 0), default=-1)
    lumo = homo + 1 if homo + 1 < len(occs) else -1
    out = []
    for i, o in enumerate(mgf["orbitals"]):
        tag = ""
        if i == homo:
            tag = "HOMO"
        elif i == lumo:
            tag = "LUMO"
        elif homo >= 0 and i < homo:
            tag = f"HOMO-{homo - i}"
        elif lumo >= 0 and i > lumo:
            tag = f"LUMO+{i - lumo}"
        out.append({"index": i, "label": o["label"], "energy": round(o["energy"], 4),
                    "occ": o["occ"], "tag": tag})
    return out, homo, lumo


# 실수형 각도 인자 (정규화 상수는 _norm 에서 처리)
def _angular(kind, dx, dy, dz, r):
    if kind == "s":
        return np.ones_like(r)
    if kind == "px":
        return dx
    if kind == "py":
        return dy
    if kind == "pz":
        return dz
    # d (cartesian, 상대 스케일)
    if kind == "dz2":
        return (3 * dz * dz - r * r)
    if kind == "dxz":
        return dx * dz
    if kind == "dyz":
        return dy * dz
    if kind == "dx2y2":
        return (dx * dx - dy * dy)
    if kind == "dxy":
        return dx * dy
    return np.ones_like(r)


def _l_of(kind):
    return {"s": 0}.get(kind, 1 if kind.startswith("p") else 2)


def generate_cube(mgf, orb_index, spacing=0.12, margin=3.0, max_pts=120, comment="MO"):
    """선택 오비탈의 cube 텍스트 생성.

    중요: 원자/격자 좌표는 XYZ 모델과 동일한 Å 단위를 사용한다.
    Gaussian Cube의 *음수 축 격자수*는 Å 단위임을 나타낸다.
    (양수 축 격자수는 Bohr로 해석되어 3Dmol.js가 0.529177을 곱하므로
    기존 코드에서는 분자만 실제 크기로 남고 오비탈 격자가 원점 쪽으로 축소되었다.)
    Slater 오비탈 계산의 변위는 별도로 Bohr로 환산한다.
    spacing(Å) 목표 간격으로 축별 격자점 수를 적응적으로 정해 해상도를 높인다.
    """
    atoms = mgf["atoms"]; basis = mgf["basis"]
    coef_orth = mgf["orbitals"][orb_index]["coef"]
    coef = mgf["inv"].dot(coef_orth)         # 비직교(실제 Slater) 기저로 변환

    axA = np.array([(a[1], a[2], a[3]) for a in atoms])  # Å
    lo = axA.min(axis=0) - margin
    hi = axA.max(axis=0) + margin
    span = hi - lo
    n = np.clip((span / spacing).astype(int) + 1, 24, max_pts)
    nx, ny, nz = int(n[0]), int(n[1]), int(n[2])

    xs = np.linspace(lo[0], hi[0], nx)
    ys = np.linspace(lo[1], hi[1], ny)
    zs = np.linspace(lo[2], hi[2], nz)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")     # Å (cube 헤더용)
    psi = np.zeros_like(X)

    for bi, (ai, kind, zeta) in enumerate(basis):
        c = coef[bi]
        if abs(c) < 1e-6:
            continue
        cx, cy, cz = axA[ai]
        # STO 평가는 원자단위(Bohr) 변위로
        ddx = (X - cx) / BOHR; ddy = (Y - cy) / BOHR; ddz = (Z - cz) / BOHR
        r = np.sqrt(ddx * ddx + ddy * ddy + ddz * ddz) + 1e-10
        n_pq = _n_for_Z(atoms[ai][0])
        l = _l_of(kind)
        rad = r ** (n_pq - 1 - l) * np.exp(-zeta * r)
        ang = _angular(kind, ddx, ddy, ddz, r)
        Nrad = (2 * zeta) ** (n_pq + 0.5) / math.sqrt(math.factorial(2 * n_pq))
        Nang = {0: 0.2820948, 1: 0.4886025, 2: 0.6307831}[l]
        psi += c * Nrad * Nang * rad * ang

    dx = (hi[0] - lo[0]) / (nx - 1)
    dy = (hi[1] - lo[1]) / (ny - 1)
    dz = (hi[2] - lo[2]) / (nz - 1)
    return _cube_text(atoms, lo, (nx, ny, nz), (dx, dy, dz), psi, comment), float(np.abs(psi).max())


def _cube_text(atoms, origin, n, d, psi, comment):
    """Å 단위 Gaussian Cube. 음수 격자수로 단위를 명시한다.

    3Dmol.js CUBE parser는 첫 격자수가 양수면 원점/축 벡터를 Bohr로
    가정하고 0.529177배 한다. 음수는 Å로 해석하며, 데이터 크기에는
    절댓값을 사용한다. 양수로 Å 수치를 기록하면 등가면이 축소·이동된다.
    """
    nx, ny, nz = n; dx, dy, dz = d
    out = [f"{comment}", "MOPAC Studio molecular orbital (Angstrom)"]
    out.append(f"{len(atoms):5d} {origin[0]:12.6f} {origin[1]:12.6f} {origin[2]:12.6f}")
    # Negative axis counts = Å in Gaussian Cube convention/3Dmol.js.
    out.append(f"{-nx:5d} {dx:12.6f} {0.0:12.6f} {0.0:12.6f}")
    out.append(f"{-ny:5d} {0.0:12.6f} {dy:12.6f} {0.0:12.6f}")
    out.append(f"{-nz:5d} {0.0:12.6f} {0.0:12.6f} {dz:12.6f}")
    for Z, x, y, z in atoms:
        out.append(f"{Z:5d} {float(Z):12.6f} {x:12.6f} {y:12.6f} {z:12.6f}")
    flat = psi.reshape(-1)   # C-order: x 바깥, z 안쪽 (cube 규약)
    buf = []; line = []
    for v in flat:
        line.append(f"{v:13.5e}")
        if len(line) == 6:
            buf.append(" ".join(line)); line = []
    if line:
        buf.append(" ".join(line))
    out.extend(buf)
    return "\n".join(out) + "\n"
