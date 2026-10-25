# -*- coding: utf-8 -*-
"""구조 생성/변환 모듈.

- SMILES -> 3D 좌표 (RDKit, MMFF/UFF 최적화)
- PubChem 이름/CID -> 3D 구조 (PubChemPy)
- 로컬 파일 로드 (.mop .xyz .mol .sdf .pdb)
- 어떤 입력이든 공통 분자 표현(dict)으로 변환
"""
import os
import re
import json
import urllib.error
import urllib.parse
import urllib.request

from rdkit import Chem
from rdkit.Chem import AllChem

# 원자번호 -> 기호 (MOPAC/XYZ 파싱용 보조)
PERIODIC = [
    "X", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg",
    "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn",
    "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb",
    "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In",
    "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm",
    "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta",
    "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At",
    "Rn",
]


class StructureError(Exception):
    pass


def _mol_to_dict(mol, name="molecule"):
    """RDKit Mol(3D 컨포머 보유) -> 표준 dict."""
    if mol is None:
        raise StructureError("분자를 해석할 수 없습니다.")
    if mol.GetNumConformers() == 0:
        raise StructureError("3D 좌표가 없습니다.")
    conf = mol.GetConformer()
    atoms = []
    for atom in mol.GetAtoms():
        p = conf.GetAtomPosition(atom.GetIdx())
        atoms.append({
            "symbol": atom.GetSymbol(),
            "x": round(p.x, 6),
            "y": round(p.y, 6),
            "z": round(p.z, 6),
            "formal_charge": atom.GetFormalCharge(),
        })
    # Emit Kekule single/double bonds for aromatic molecules so the browser
    # 3D editor can modify them without turning every aromatic bond into double.
    bond_mol = Chem.Mol(mol)
    if any(b.GetIsAromatic() for b in bond_mol.GetBonds()):
        try:
            Chem.Kekulize(bond_mol, clearAromaticFlags=True)
        except Exception:
            pass
    bonds = []
    for b in bond_mol.GetBonds():
        bonds.append({
            "a": b.GetBeginAtomIdx(),
            "b": b.GetEndAtomIdx(),
            "order": b.GetBondTypeAsDouble(),
        })
    charge = Chem.GetFormalCharge(mol)
    return {
        "name": name,
        "atoms": atoms,
        "bonds": bonds,
        "charge": charge,
        "formula": Chem.rdMolDescriptors.CalcMolFormula(mol),
    }


def _embed3d(mol):
    """수소 추가 + 3D 임베딩 + 힘장 최적화."""
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = 0xf00d
    if AllChem.EmbedMolecule(mol, params) != 0:
        # 임베딩 실패시 랜덤 좌표 시도
        if AllChem.EmbedMolecule(mol, useRandomCoords=True) != 0:
            raise StructureError("3D 좌표 생성에 실패했습니다.")
    try:
        if AllChem.MMFFHasAllMoleculeParams(mol):
            AllChem.MMFFOptimizeMolecule(mol, maxIters=2000)
        else:
            AllChem.UFFOptimizeMolecule(mol, maxIters=2000)
    except Exception:
        pass
    return mol


def from_smiles(smiles, name=None):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise StructureError(f"잘못된 SMILES: {smiles}")
    mol = _embed3d(mol)
    return _mol_to_dict(mol, name or smiles)


def _pubchem_rest_record(query):
    """PubChem PUG-REST에서 SMILES와 이름을 직접 가져온다."""
    if query.isdigit():
        path = f"cid/{int(query)}"
    else:
        path = "name/" + urllib.parse.quote(query, safe="")

    prop_sets = [
        "CanonicalSMILES,IsomericSMILES,IUPACName,MolecularFormula",
        "ConnectivitySMILES,IsomericSMILES,IUPACName,MolecularFormula",
    ]
    last_error = None
    for props in prop_sets:
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/{path}/property/{props}/JSON"
        req = urllib.request.Request(url, headers={"User-Agent": "MOPACStudio/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            last_error = f"HTTP {e.code} {body[:200]}"
            continue
        except Exception as e:
            last_error = str(e)
            continue

        rows = payload.get("PropertyTable", {}).get("Properties", [])
        if not rows:
            last_error = "PubChem property 결과가 비어 있습니다."
            continue
        row = rows[0]
        smiles = (row.get("IsomericSMILES") or row.get("CanonicalSMILES") or
                  row.get("ConnectivitySMILES") or row.get("SMILES"))
        if smiles:
            return {
                "smiles": smiles,
                "name": row.get("IUPACName") or query,
                "formula": row.get("MolecularFormula"),
                "cid": row.get("CID"),
            }
        last_error = "PubChem property 결과에 SMILES가 없습니다."
    raise StructureError(f"PubChem REST 조회 실패: {last_error}")


def _pubchempy_smiles(compound):
    for attr in ("isomeric_smiles", "canonical_smiles", "connectivity_smiles", "smiles"):
        val = getattr(compound, attr, None)
        if val:
            return val
    try:
        d = compound.to_dict()
    except Exception:
        d = {}
    for key in ("isomeric_smiles", "canonical_smiles", "connectivity_smiles", "smiles",
                "IsomericSMILES", "CanonicalSMILES", "ConnectivitySMILES", "SMILES"):
        val = d.get(key)
        if val:
            return val
    return None


def from_pubchem(query):
    """이름 또는 CID로 PubChem에서 가져온다."""
    query = query.strip()
    if not query:
        raise StructureError("PubChem 검색어를 입력하세요.")

    rest_error = None
    try:
        record = _pubchem_rest_record(query)
        return from_smiles(record["smiles"], record["name"])
    except Exception as e:
        rest_error = e

    try:
        import pubchempy as pcp
    except ImportError:
        raise StructureError(f"PubChem 조회 실패: {rest_error}")

    compounds = []
    try:
        if query.isdigit():
            compounds = [pcp.Compound.from_cid(int(query))]
        else:
            compounds = pcp.get_compounds(query, "name")
    except Exception as e:
        raise StructureError(f"PubChem 조회 실패: {e}")
    if not compounds:
        raise StructureError(f"PubChem에서 '{query}' 를 찾지 못했습니다.")
    smiles = _pubchempy_smiles(compounds[0])
    if not smiles:
        raise StructureError(f"PubChem 결과에 SMILES가 없습니다. ({rest_error})")
    nm = query
    try:
        if compounds[0].iupac_name:
            nm = compounds[0].iupac_name
    except Exception:
        pass
    return from_smiles(smiles, nm)


def parse_xyz(text, name="molecule"):
    lines = text.splitlines()
    if len(lines) < 3:
        raise StructureError("XYZ 형식이 올바르지 않습니다.")
    try:
        n = int(lines[0].strip())
    except ValueError:
        raise StructureError("XYZ 첫 줄(원자 수)을 읽을 수 없습니다.")
    atoms = []
    for ln in lines[2:2 + n]:
        parts = ln.split()
        if len(parts) < 4:
            continue
        sym = parts[0]
        if sym.isdigit():
            sym = PERIODIC[int(sym)]
        atoms.append({"symbol": sym, "x": float(parts[1]),
                      "y": float(parts[2]), "z": float(parts[3])})
    if not atoms:
        raise StructureError("XYZ에서 원자를 찾지 못했습니다.")
    return {"name": name, "atoms": atoms, "bonds": [], "charge": 0,
            "formula": _formula(atoms)}


def parse_mop(text, name="molecule"):
    """MOPAC 입력(.mop)에서 좌표를 읽는다 (Cartesian 우선)."""
    lines = text.splitlines()
    # 키워드(최대 3줄) 이후 좌표. 단순히 'Symbol x flag y flag z flag' 패턴을 찾는다.
    atoms = []
    # 데이터 시작: 보통 키워드 1줄 + 코멘트 2줄
    body = lines[3:] if len(lines) > 3 else lines
    cart_re = re.compile(
        r"^\s*([A-Za-z]{1,2})\s+(-?\d+\.?\d*)\s+[-+]?\d\s+(-?\d+\.?\d*)\s+[-+]?\d\s+(-?\d+\.?\d*)\s+[-+]?\d")
    for ln in body:
        m = cart_re.match(ln)
        if m:
            sym = m.group(1)
            if sym.upper() in ("AB", "TV"):
                continue
            atoms.append({"symbol": sym.capitalize(),
                          "x": float(m.group(2)), "y": float(m.group(3)),
                          "z": float(m.group(4))})
    if not atoms:
        raise StructureError(".mop에서 Cartesian 좌표를 찾지 못했습니다. (Z-matrix는 미지원)")
    return {"name": name, "atoms": atoms, "bonds": [], "charge": 0,
            "formula": _formula(atoms)}


def _formula(atoms):
    from collections import Counter
    c = Counter(a["symbol"] for a in atoms)
    order = ["C", "H"] + [e for e in PERIODIC if e not in ("C", "H", "X")]
    out = ""
    for el in order:
        if c.get(el):
            out += el + (str(c[el]) if c[el] > 1 else "")
    return out


def from_file(path):
    name = os.path.splitext(os.path.basename(path))[0]
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    if ext == ".xyz":
        return parse_xyz(text, name)
    if ext in (".mop", ".dat", ".arc"):
        return parse_mop(text, name)
    if ext in (".mol", ".sdf"):
        mol = Chem.MolFromMolBlock(text, removeHs=False)
        if mol is None:
            raise StructureError("MOL/SDF 파싱 실패")
        if mol.GetNumConformers() == 0:
            mol = _embed3d(mol)
        return _mol_to_dict(mol, name)
    if ext == ".pdb":
        mol = Chem.MolFromPDBBlock(text, removeHs=False)
        if mol is None:
            raise StructureError("PDB 파싱 실패")
        return _mol_to_dict(mol, name)
    raise StructureError(f"지원하지 않는 형식: {ext}")


def to_xyz(mol_dict):
    lines = [str(len(mol_dict["atoms"])), mol_dict.get("name", "")]
    for a in mol_dict["atoms"]:
        lines.append(f"{a['symbol']:<2} {a['x']:>14.6f} {a['y']:>14.6f} {a['z']:>14.6f}")
    return "\n".join(lines) + "\n"
