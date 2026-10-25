# -*- coding: utf-8 -*-
"""3D editor graph -> RDKit molecule -> explicit-H MOPAC geometry.

The editor owns the heavy-atom coordinates: by default only the newly added
hydrogens are optimized. Optional 'relax' does an all-atom MMFF/UFF refinement.
"""
import math
import logging
from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Geometry import Point3D

from structure import StructureError, _mol_to_dict
from element_data import AUTO_H_ELEMENTS, ELEMENT_SYMBOLS, unsupported_elements

# All real elements can be drawn/exported; calculation coverage is narrower.
EDITOR_ELEMENTS = ELEMENT_SYMBOLS
MAX_ATOMS = 300


def _finite(v, what):
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        raise StructureError(f'{what}: 유효한 숫자가 아닙니다.')
    if not math.isfinite(f) or abs(f) > 10000:
        raise StructureError(f'{what}: 유효한 좌표 범위를 벗어났습니다.')
    return f


log = logging.getLogger(__name__)


class OptimizationError(StructureError):
    """Recoverable: no proposed coordinates may be committed."""


def _forcefield(mol, method):
    if method == 'MMFF' and AllChem.MMFFHasAllMoleculeParams(mol):
        props = AllChem.MMFFGetMoleculeProperties(mol)
        if props is not None:
            ff = AllChem.MMFFGetMoleculeForceField(mol, props)
            if ff is not None:
                return ff
    if method == 'UFF' and AllChem.UFFHasAllMoleculeParams(mol):
        return AllChem.UFFGetMoleculeForceField(mol)
    return None


def _valid_coordinates(mol):
    conf = mol.GetConformer()
    return all(math.isfinite(v) and abs(v) <= 10000
               for i in range(mol.GetNumAtoms())
               for v in conf.GetAtomPosition(i))


def _refine(mol, n_original, relax_heavy):
    """Each force field works on a fresh copy, including after partial failure."""
    if not relax_heavy and n_original == mol.GetNumAtoms():
        return mol, {'status': 'not_required', 'method': None, 'attempts': []}
    attempts = []
    for method in ('MMFF', 'UFF'):
        candidate = Chem.Mol(mol)
        try:
            ff = _forcefield(candidate, method)
            if ff is None:
                attempts.append({'method': method, 'status': 'unavailable'})
                continue
            if not relax_heavy:
                for i in range(n_original):
                    ff.AddFixedPoint(i)
            ff.Initialize()
            status = ff.Minimize(maxIts=600 if relax_heavy else 250)
            if status != 0:
                attempts.append({'method': method, 'status': 'not_converged'})
                continue
            if not _valid_coordinates(candidate) or not math.isfinite(ff.CalcEnergy()):
                raise ValueError('Non-finite force-field result')
            if not relax_heavy:
                # Explicitly restore *all* user-supplied atoms, including H.
                for i in range(n_original):
                    candidate.GetConformer().SetAtomPosition(i, mol.GetConformer().GetAtomPosition(i))
            attempts.append({'method': method, 'status': 'converged'})
            return candidate, {'status': 'converged', 'method': method, 'attempts': attempts}
        except Exception:
            log.warning('%s editor refinement failed; discarding trial coordinates', method, exc_info=True)
            attempts.append({'method': method, 'status': 'failed'})
    if relax_heavy:
        raise OptimizationError('구조 정리가 수렴하지 않았거나 힘장을 적용할 수 없습니다. '
                                '현재 원자·결합·좌표는 유지됩니다. 겹친 원자와 결합 거리를 조정한 뒤 다시 시도하세요.')
    # Adding H is allowed without optional FF refinement, with an explicit warning.
    return mol, {'status': 'skipped', 'method': None, 'attempts': attempts}


def from_editor(payload, relax_heavy=False):
    """Validate editable atoms/bonds; fill valences with explicit hydrogens.

    Preserves the original 3D heavy-atom positions unless relax_heavy=True.
    Fails transparently for invalid valence; no silent bond inference.
    """
    if not isinstance(payload, dict):
        raise StructureError('분자 데이터가 없습니다.')
    atoms = payload.get('atoms')
    bonds = payload.get('bonds', [])
    if not isinstance(atoms, list) or not 1 <= len(atoms) <= MAX_ATOMS:
        raise StructureError(f'원자 수는 1~{MAX_ATOMS}개여야 합니다.')
    if not isinstance(bonds, list) or len(bonds) > MAX_ATOMS * 5:
        raise StructureError('결합 목록이 올바르지 않습니다.')

    rw = Chem.RWMol()
    coords = []
    for i, a in enumerate(atoms):
        if not isinstance(a, dict):
            raise StructureError(f'원자 {i + 1}: 데이터 형식 오류')
        sym = a.get('symbol')
        if sym not in EDITOR_ELEMENTS:
            raise StructureError(f'지원하지 않는 원소: {sym}')
        atom = Chem.Atom(sym)
        if sym not in AUTO_H_ELEMENTS:
            # Do not invent hydrides or oxidation states for metals / newly
            # exposed elements. Explicit user-supplied H atoms remain intact.
            atom.SetNoImplicit(True)
        charge = a.get('formal_charge', 0)
        if type(charge) is not int or abs(charge) > 4:
            raise StructureError(f'원자 {i + 1}: 형식전하는 -4~+4의 정수여야 합니다.')
        atom.SetFormalCharge(charge)
        rw.AddAtom(atom)
        coords.append((_finite(a.get('x'), 'x'), _finite(a.get('y'), 'y'),
                       _finite(a.get('z'), 'z')))

    types = {1: Chem.BondType.SINGLE, 2: Chem.BondType.DOUBLE, 3: Chem.BondType.TRIPLE}
    seen = set()
    for bond in bonds:
        if not isinstance(bond, dict):
            raise StructureError('결합 데이터 형식 오류')
        a, b, order = bond.get('a'), bond.get('b'), bond.get('order')
        if (type(a) is not int or type(b) is not int or not
                0 <= a < len(atoms) or not 0 <= b < len(atoms) or a == b):
            raise StructureError('잘못된 원자 인덱스의 결합이 있습니다.')
        if order not in types:
            raise StructureError('결합 차수는 단일(1), 이중(2), 삼중(3) 중 하나여야 합니다.')
        pair = tuple(sorted((a, b)))
        if pair in seen:
            raise StructureError('중복된 결합이 있습니다.')
        seen.add(pair)
        rw.AddBond(a, b, types[order])

    mol = rw.GetMol()
    try:
        Chem.SanitizeMol(mol)
    except Exception as e:
        raise StructureError('결합 차수 또는 형식전하가 유효하지 않습니다: ' + str(e))

    conformer = Chem.Conformer(len(atoms))
    conformer.Set3D(True)
    for i, xyz in enumerate(coords):
        conformer.SetAtomPosition(i, Point3D(*xyz))
    mol.AddConformer(conformer)
    n_original = len(atoms)
    try:
        mol = Chem.AddHs(mol, addCoords=True)
        if not _valid_coordinates(mol):
            raise ValueError('Invalid hydrogen coordinates')
    except Exception as e:
        raise StructureError('수소 좌표를 생성하지 못했습니다. 현재 편집 구조는 유지됩니다.') from e
    mol, optimization = _refine(mol, n_original, relax_heavy)

    name = str(payload.get('name', '직접 그린 분자'))[:160]
    result = _mol_to_dict(mol, name)
    result['editor_source'] = True
    result['heavy_atom_count'] = n_original
    if not relax_heavy:
        # _mol_to_dict rounds generated coordinates; retain input precision exactly.
        for i, xyz in enumerate(coords):
            result['atoms'][i].update(zip('xyz', xyz))
    result['relaxed_heavy_atoms'] = bool(relax_heavy and optimization['status'] == 'converged')
    result['optimization'] = optimization
    result['warnings'] = (['수소는 추가했지만 MMFF/UFF 보정은 완료되지 않았습니다. '
                           '입력한 원자 좌표는 유지되며, 수소 배치를 확인한 뒤 계산하세요.']
                          if optimization['status'] == 'skipped' else [])
    if any(a['symbol'] not in AUTO_H_ELEMENTS for a in atoms):
        result['warnings'].append('금속 등 확장 원소에는 수소를 자동 추가하지 않습니다. '
                                  '배위결합·형식전하·스핀다중도를 확인하세요.')
    unsupported = unsupported_elements(result)
    if unsupported:
        result['warnings'].append('기본 PM6/PM7 계산 미지원 원소: ' + ', '.join(unsupported) +
                                  '. 구조 표시·편집·저장은 가능합니다.')
    return result
