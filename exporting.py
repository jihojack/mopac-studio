"""Export displayed coordinates and completed results without re-optimizing."""
import base64
import binascii
import copy
import csv
from datetime import datetime
import io
import json
import math
from pathlib import Path
import re
import tempfile
import uuid
import zipfile

from rdkit import Chem
from rdkit.Geometry import Point3D

SCHEMA = 'mopac-studio-export-v1'
FORMATS = {'zip', 'xyz', 'mol', 'sdf', 'json', 'csv', 'png'}


def validate_structure(value):
    if not isinstance(value, dict) or not isinstance(value.get('atoms'), list) or not 1 <= len(value['atoms']) <= 10000:
        raise ValueError('내보낼 원자가 없습니다. 먼저 분자를 만들거나 불러오세요.')
    mol = copy.deepcopy(value)
    pt = Chem.GetPeriodicTable()
    for atom in mol['atoms']:
        if not isinstance(atom, dict) or not re.fullmatch(r'[A-Z][a-z]?', str(atom.get('symbol', ''))):
            raise ValueError('원소 기호가 올바르지 않습니다.')
        try:
            if pt.GetAtomicNumber(atom['symbol']) < 1:
                raise ValueError('지원하지 않는 원소입니다.')
            for axis in 'xyz':
                number = float(atom[axis])
                if not math.isfinite(number) or abs(number) > 10000:
                    raise ValueError('유효하지 않은 좌표입니다.')
                atom[axis] = number
        except (KeyError, TypeError, RuntimeError, OverflowError) as error:
            raise ValueError('원소 또는 좌표를 확인하세요.') from error
        charge = atom.get('formal_charge', 0)
        if type(charge) is not int or abs(charge) > 100:
            raise ValueError('형식전하가 올바르지 않습니다.')
    bonds = mol.setdefault('bonds', [])
    if not isinstance(bonds, list) or len(bonds) > 50000:
        raise ValueError('결합 데이터가 올바르지 않습니다.')
    seen = set()
    for bond in bonds:
        if not isinstance(bond, dict):
            raise ValueError('결합 데이터가 올바르지 않습니다.')
        a, b = bond.get('a'), bond.get('b')
        if type(a) is not int or type(b) is not int or a == b or not (0 <= a < len(mol['atoms']) and 0 <= b < len(mol['atoms'])):
            raise ValueError('결합 원자 번호가 올바르지 않습니다.')
        if bond.get('order') not in (1, 1.5, 2, 3):
            raise ValueError('결합 차수가 올바르지 않습니다.')
        pair = tuple(sorted((a, b)))
        if pair in seen:
            raise ValueError('중복 결합이 있습니다.')
        seen.add(pair)
    return mol


def xyz_text(mol):
    name = str(mol.get('name', 'molecule')).replace('\n', ' ').replace('\r', ' ')
    return '\n'.join([str(len(mol['atoms'])), name] + [
        f"{a['symbol']} {a['x']!r} {a['y']!r} {a['z']!r}" for a in mol['atoms']]) + '\n'


def mol_text(mol):
    rw = Chem.RWMol()
    for value in mol['atoms']:
        atom = Chem.Atom(value['symbol'])
        atom.SetFormalCharge(value.get('formal_charge', 0))
        rw.AddAtom(atom)
    types = {1: Chem.BondType.SINGLE, 1.5: Chem.BondType.AROMATIC,
             2: Chem.BondType.DOUBLE, 3: Chem.BondType.TRIPLE}
    for bond in mol['bonds']:
        rw.AddBond(bond['a'], bond['b'], types[bond['order']])
    result = rw.GetMol()
    result.SetProp('_Name', str(mol.get('name', 'molecule')).replace('\n', ' ')[:160])
    result.UpdatePropertyCache(strict=False)
    conf = Chem.Conformer(len(mol['atoms']))
    conf.Set3D(True)
    for i, atom in enumerate(mol['atoms']):
        conf.SetAtomPosition(i, Point3D(atom['x'], atom['y'], atom['z']))
    result.AddConformer(conf)
    # No sanitization, embedding, AddHs or force field: drafts stay drafts.
    return Chem.MolToMolBlock(result)


def png_bytes(value):
    if not isinstance(value, str) or not value.startswith('data:image/png;base64,') or len(value) > 24_000_000:
        raise ValueError('현재 3D 화면의 PNG 이미지가 없습니다.')
    try:
        data = base64.b64decode(value.split(',', 1)[1], validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError('PNG 이미지 형식 오류입니다.') from error
    if len(data) < 24 or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('PNG 이미지 형식 오류입니다.')
    return data


def _properties(value, prefix=''):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _properties(item, f'{prefix}.{key}' if prefix else str(key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _properties(item, f'{prefix}[{i}]')
    else:
        yield prefix, value


def csv_bytes(results):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(['계산', '상태', '항목', '값'])
    for result in results:
        for key, value in _properties({'data': result.get('data', {}), 'errors': result.get('errors', [])}):
            cells = [result.get('label', result.get('calc_key', '')), result.get('status', ''), key, value]
            writer.writerow(["'" + c if isinstance(c, str) and c.lstrip().startswith(('=', '+', '-', '@')) else c for c in cells])
    return out.getvalue().encode('utf-8-sig')


def _raw_files(results, workspace):
    root = (workspace / 'runs').resolve()
    found = set()
    for result in results:
        folder = result.get('run_dir')
        if not isinstance(folder, str):
            continue
        folder = Path(folder).resolve()
        if not folder.is_relative_to(root) or not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            resolved = path.resolve()
            if (resolved.is_relative_to(root) and resolved.is_file() and resolved not in found
                    and resolved.suffix.lower() in {'.mop', '.out', '.arc', '.aux', '.mgf', '.xyz', '.json'}):
                found.add(resolved)
                yield resolved, 'runs/' + path.relative_to(root).as_posix()


def export_project(payload, workspace):
    if not isinstance(payload, dict) or payload.get('format') not in FORMATS:
        raise ValueError('지원하지 않는 내보내기 형식입니다.')
    kind = payload['format']
    mol = validate_structure(payload.get('structure'))
    results = payload.get('results', [])
    if not isinstance(results, list) or len(results) > 1000 or any(not isinstance(r, dict) for r in results):
        raise ValueError('계산 결과 목록이 올바르지 않습니다.')
    if kind == 'csv' and not results:
        raise ValueError('아직 내보낼 계산 결과가 없습니다.')
    record = {'schema': SCHEMA, 'created_at': datetime.now().astimezone().isoformat(),
              'coordinate_unit': 'angstrom', 'structure': mol, 'results': results,
              'visualization': payload.get('visualization', {}),
              'draft': bool(mol.get('editor_draft'))}
    encoded = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    workspace = Path(workspace).resolve()
    exports = workspace / 'exports'
    exports.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(mol.get('name', 'molecule'))).strip(' .')[:70] or 'molecule'
    path = exports / f'{datetime.now():%Y%m%d_%H%M%S}_{name}_{uuid.uuid4().hex[:6]}.{kind}'
    # Construct every payload before exposing the final file. Failed exports
    # leave existing exports and the editor's state unchanged.
    with tempfile.TemporaryDirectory(prefix='.export-', dir=exports) as temporary:
        stage = Path(temporary) / path.name
        if kind == 'zip':
            with zipfile.ZipFile(stage, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('structure.xyz', xyz_text(mol))
                block = mol_text(mol)
                zf.writestr('structure.mol', block)
                zf.writestr('structure.sdf', block + '\n$$$$\n')
                zf.writestr('session.json', encoded)
                zf.writestr('results.csv', csv_bytes(results))
                if payload.get('image'):
                    zf.writestr('view.png', png_bytes(payload['image']))
                if payload.get('include_raw', True):
                    for file, relative in _raw_files(results, workspace):
                        zf.write(file, relative)
                zf.writestr('README.txt', 'MOPAC Studio export\nCoordinates: Angstrom\n'
                    'session.json preserves full coordinates, explicit bonds and displayed results.\n'
                    'MOL/SDF coordinates may be rounded by their file format.\n'
                    f"Unvalidated editor draft: {record['draft']}\n"
                    'The view image is a visualization, not an electron-density measurement.\n')
        else:
            data = {'xyz': lambda: xyz_text(mol).encode('utf-8'),
                    'mol': lambda: mol_text(mol).encode('utf-8'),
                    'sdf': lambda: (mol_text(mol) + '\n$$$$\n').encode('utf-8'),
                    'json': lambda: encoded, 'csv': lambda: csv_bytes(results),
                    'png': lambda: png_bytes(payload.get('image'))}[kind]()
            stage.write_bytes(data)
        stage.replace(path)
    return path


def load_export(path):
    record = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(record, dict) or record.get('schema') != SCHEMA:
        raise ValueError('MOPAC Studio 내보내기 JSON 파일이 아닙니다.')
    results = record.get('results', [])
    if not isinstance(results, list) or any(not isinstance(r, dict) for r in results):
        raise ValueError('저장된 계산 결과 목록이 올바르지 않습니다.')
    return validate_structure(record.get('structure')), results
