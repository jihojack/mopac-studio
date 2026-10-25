"""Sequential file batches, isolated from the viewer and its current draft."""
import copy
import csv
from datetime import datetime
import io
import json
import math
from pathlib import Path
import re
import shutil
import threading
import uuid
import zipfile

from rdkit import Chem
import structure
from exporting import SCHEMA, csv_bytes, load_export, validate_structure, xyz_text

EXTENSIONS = {'.xyz', '.mol', '.sdf', '.pdb', '.mop', '.dat', '.arc', '.json'}
MAX_FILES = 200
MAX_FILE_BYTES = 10_000_000
MAX_TOTAL_BYTES = 100_000_000
MAX_STRUCTURES = 500
TERMINAL = {'completed', 'cancelled', 'error', 'interrupted'}


def _json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def _filename(value):
    # Browsers and test clients may send either Windows or POSIX paths.
    value = str(value or 'structure').replace('\\', '/').split('/')[-1]
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', value).strip(' .')[:140] or 'structure'


def _structures(path):
    try:
        for record, mol, error in _read_structures(path):
            if mol and (type(mol.get('charge', 0)) is not int or abs(mol.get('charge', 0)) > 100):
                yield record, None, '파일에 저장된 전하가 올바르지 않습니다.'
            else:
                yield record, mol, error
    except Exception as error:
        yield 1, None, str(error)


def _read_structures(path):
    """Yield each SDF record; never silently use only the first structure."""
    if path.suffix.lower() == '.sdf':
        # A malformed record must not consume the next valid molecule during
        # supplier recovery. Parse each delimited block independently.
        records = re.split(r'(?m)^\$\$\$\$[ \t]*\r?\n?', path.read_text(encoding='utf-8-sig'))
        for index, block in enumerate(records, 1):
            if index == len(records) and not block.strip():
                continue
            try:
                mol = Chem.MolFromMolBlock(block, removeHs=False)
                value = structure._mol_to_dict(mol, f'{path.stem} #{index}')
                yield index, validate_structure(value), None
            except Exception as error:
                yield index, None, str(error)
    else:
        try:
            if path.suffix.lower() == '.json':
                mol, _ = load_export(path)
                if mol.get('editor_draft'):
                    raise ValueError('편집 초안입니다. 수소 추가 → 계산에 적용 후 저장하세요.')
            else:
                mol = structure.from_file(str(path))
            if path.suffix.lower() == '.xyz':
                lines = path.read_text(encoding='utf-8-sig').splitlines()
                count = int(lines[0].strip())
                if count != len(mol['atoms']) or any(line.strip() for line in lines[2 + count:]):
                    raise ValueError('XYZ 원자 수를 확인하세요. 여러 프레임은 파일을 나누어 주세요.')
            yield 1, validate_structure(mol), None
        except Exception as error:
            yield 1, None, str(error)


def options(value, calc_types):
    if not isinstance(value, dict):
        raise ValueError('계산 옵션이 올바르지 않습니다.')
    keys = value.get('calc_keys')
    if not isinstance(keys, list) or not keys or any(not isinstance(k, str) or k not in calc_types for k in keys):
        raise ValueError('계산을 1개 이상 선택하세요.')
    keys = list(dict.fromkeys(keys))
    charge = value.get('charge')
    mult = value.get('mult', 1)
    eps = value.get('eps', 78.4)
    if charge is not None and (type(charge) is not int or abs(charge) > 100):
        raise ValueError('전하는 -100~100 범위의 정수여야 합니다.')
    if type(mult) is not int or not 1 <= mult <= 5:
        raise ValueError('스핀다중도는 1~5 범위의 정수여야 합니다.')
    if isinstance(eps, bool) or not isinstance(eps, (float, int)) or not math.isfinite(eps) or eps < 1:
        raise ValueError('용매 유전율은 1 이상의 유한한 수여야 합니다.')
    return {'calc_keys': keys, 'charge': charge, 'mult': mult, 'eps': eps}


class BatchManager:
    def __init__(self, workspace, calculate, begin, end):
        self.workspace = workspace
        self.calculate = calculate
        self.begin, self.end = begin, end
        self.lock = threading.RLock()
        self.jobs = {}
        self.active = None

    def _save(self, job):
        _json(Path(job['directory']) / 'job.json', {k: v for k, v in job.items() if k != 'cancel'})

    def _update(self, job, **values):
        with self.lock:
            job.update(values)
            self._save(job)

    def submit(self, uploads, settings):
        if not 1 <= len(uploads) <= MAX_FILES:
            raise ValueError(f'한 번에 파일 1~{MAX_FILES}개를 선택하세요.')
        with self.lock:
            if self.active is not None:
                raise ValueError('일괄 계산이 이미 진행 중입니다. 완료 후 다시 실행하세요.')
            identifier = uuid.uuid4().hex
            root = Path(self.workspace()).resolve() / 'batches' / identifier
            source = root / 'inputs'
            source.mkdir(parents=True)
            counted = False
            try:
                saved = []
                total = 0
                for index, upload in enumerate(uploads, 1):
                    name = _filename(upload.filename)
                    folder = source / f'{index:04d}'
                    folder.mkdir()
                    path = folder / name
                    data = upload.stream.read(MAX_FILE_BYTES + 1)
                    total += len(data)
                    if len(data) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                        raise ValueError('파일당 10 MB, 전체 100 MB까지 지원합니다.')
                    path.write_bytes(data)
                    saved.append({'filename': name, 'path': str(path)})
                job = {'id': identifier, 'directory': str(root), 'status': 'preparing',
                       'created_at': datetime.now().astimezone().isoformat(), 'options': settings,
                       'files': saved, 'entries': [], 'completed': 0, 'total': 0,
                       'current': '구조 파일 읽는 중', 'cancel': threading.Event(), 'export': None}
                self._save(job)
                self.jobs[identifier] = job
                self.active = identifier
                # Count the entire job, including preparation and ZIP creation,
                # so native window close / idle shutdown cannot interrupt it.
                self.begin()
                counted = True
                threading.Thread(target=self._run, args=(job,), daemon=True).start()
            except Exception:
                if counted:
                    self.end()
                self.jobs.pop(identifier, None)
                self.active = None
                shutil.rmtree(root)
                raise
            return self.snapshot(identifier)

    def snapshot(self, identifier):
        if not re.fullmatch(r'[0-9a-f]{32}', identifier):
            raise ValueError('일괄 계산을 찾을 수 없습니다.')
        with self.lock:
            job = self.jobs.get(identifier)
            if job is None:
                path = Path(self.workspace()) / 'batches' / identifier / 'job.json'
                if not path.is_file():
                    raise ValueError('일괄 계산을 찾을 수 없습니다.')
                job = json.loads(path.read_text(encoding='utf-8'))
                if job['status'] not in TERMINAL:
                    job.update(status='interrupted', current='서버가 종료되어 중단됐습니다. 계산 파일은 폴더에 보존되어 있습니다.')
            return copy.deepcopy({k: v for k, v in job.items() if k not in {'cancel', 'files'}})

    def cancel(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if job and job['status'] not in TERMINAL:
                job['cancel'].set()
                self._update(job, current='현재 계산이 끝나면 중단하고 완료된 결과를 내보냅니다.')
            return self.snapshot(identifier)

    def _run(self, job):
        root = Path(job['directory'])
        molecules = {}
        try:
            entries = []
            for file in job['files']:
                path = Path(file['path'])
                self._update(job, current=f'{file["filename"]} · 구조 파일 읽는 중')
                records = _structures(path) if path.suffix.lower() in EXTENSIONS else [(1, None, '지원하지 않는 구조 파일 형식입니다.')]
                found = False
                for record, mol, error in records:
                    found = True
                    if len(entries) >= MAX_STRUCTURES:
                        raise ValueError(f'한 번에 최대 {MAX_STRUCTURES}개 구조까지 계산합니다. 파일을 나누어 주세요.')
                    key = f'{len(entries) + 1:04d}'
                    entries.append({'id': key, 'filename': file['filename'], 'record': record,
                                    'input': path.relative_to(root).as_posix(), 'status': 'error' if error else 'queued',
                                    'error': error, 'results': [], 'done': 0})
                    if mol:
                        molecules[key] = mol
                if not found:
                    entries.append({'id': f'{len(entries) + 1:04d}', 'filename': file['filename'],
                                    'record': 1, 'input': path.relative_to(root).as_posix(), 'status': 'error',
                                    'error': '구조가 없는 파일입니다.', 'results': [], 'done': 0})
            keys = job['options']['calc_keys']
            total = len(entries) * len(keys)
            self._update(job, entries=entries, total=total, status='running')
            for entry in entries:
                if entry['status'] == 'error':
                    self._update(job, completed=job['completed'] + len(keys))
                    continue
                if job['cancel'].is_set():
                    with self.lock:
                        entry['status'] = 'cancelled'
                        self._update(job)
                    continue
                try:
                    self._run_entry(job, entry, molecules[entry['id']])
                except Exception as error:
                    with self.lock:
                        entry.update(status='error', error=f'구조 처리/저장 실패: {error}')
                        job['completed'] += len(keys) - entry['done']
                self._update(job)
            self._update(job, status='exporting', current='결과 ZIP 저장 중')
            artifact = self._export(job)
            cancelled = job['cancel'].is_set()
            self._update(job, status='cancelled' if cancelled else 'completed', export=str(artifact),
                         finished_at=datetime.now().astimezone().isoformat(),
                         current='중단 완료 · 완료된 결과 저장됨' if cancelled else '계산 완료 · ZIP 저장됨')
        except Exception as error:
            self._update(job, status='error', current=str(error), error=str(error))
        finally:
            with self.lock:
                self.active = None
                self.end()
                # Keep only the most recent in-memory jobs; all receipts remain on disk.
                for old in list(self.jobs)[:-20]:
                    self.jobs.pop(old, None)

    def _run_entry(self, job, entry, mol):
        directory = Path(job['directory']) / 'structures' / entry['id']
        directory.mkdir(parents=True)
        with self.lock:
            entry.update(directory=directory.relative_to(job['directory']).as_posix(), status='running')
        (directory / 'input.xyz').write_text(xyz_text(mol), encoding='utf-8')
        charge = job['options']['charge']
        if charge is None:
            charge = mol.get('charge', 0)
        run_dir = Path(self.workspace()).resolve() / 'runs' / f'batch_{job["id"]}' / entry['id']
        settings = {**job['options'], 'charge': charge}
        results = []
        for key in settings['calc_keys']:
            if job['cancel'].is_set():
                break
            self._update(job, current=f'{entry["filename"]} · 구조 {entry["record"]} · {key}')
            try:
                result, _ = self.calculate(copy.deepcopy(mol), key, charge=charge,
                                          mult=settings['mult'], eps=settings['eps'], run_dir=str(run_dir))
                # Treat invalid numeric output as a failed calculation, retaining
                # the original engine files rather than writing nonstandard JSON.
                json.dumps(result, allow_nan=False)
            except Exception as error:
                result = {'calc_key': key, 'label': key, 'status': 'error', 'errors': [str(error)], 'data': {}}
            results.append(result)
            with self.lock:
                entry['results'].append({'calc_key': key, 'status': result.get('status'), 'errors': result.get('errors', [])})
                entry['done'] += 1
                self._update(job, completed=job['completed'] + 1)
        with self.lock:
            if entry['done'] < len(settings['calc_keys']):
                entry['status'] = 'cancelled'
            elif any(r.get('status') == 'error' for r in results):
                entry['status'] = 'error'
            else:
                entry['status'] = 'ok'
        session = {'schema': SCHEMA, 'created_at': job['created_at'], 'coordinate_unit': 'angstrom',
                   'structure': mol, 'results': results, 'draft': False,
                   'batch': {'filename': entry['filename'], 'record': entry['record'], 'options': settings}}
        _json(directory / 'session.json', session)
        (directory / 'results.csv').write_bytes(csv_bytes(results))
        if run_dir.is_dir():
            shutil.copytree(run_dir, directory / 'calculations')

    def _export(self, job):
        root = Path(job['directory'])
        exports = Path(self.workspace()).resolve() / 'exports'
        exports.mkdir(parents=True, exist_ok=True)
        destination = exports / f'batch_{datetime.now():%Y%m%d_%H%M%S}_{job["id"][:8]}.zip'
        stage = destination.with_suffix('.tmp')
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['파일', 'SDF 구조 번호', '상태', '계산', '계산 상태', '오류'])
        combined = io.StringIO(newline='')
        combined_writer = csv.writer(combined)
        combined_writer.writerow(['파일', 'SDF 구조 번호', '계산', '상태', '항목', '값'])
        for entry in job['entries']:
            for result in entry['results'] or [{}]:
                cells = [entry['filename'], entry['record'], entry['status'], result.get('calc_key', ''),
                         result.get('status', ''), entry.get('error') or '; '.join(result.get('errors', []))]
                writer.writerow(["'" + c if isinstance(c, str) and c.lstrip().startswith(('=', '+', '-', '@')) else c for c in cells])
            detail = root / 'structures' / entry['id'] / 'results.csv'
            if detail.is_file():
                rows = csv.reader(io.StringIO(detail.read_text(encoding='utf-8-sig')))
                next(rows, None)
                filename = entry['filename']
                if filename.lstrip().startswith(('=', '+', '-', '@')):
                    filename = "'" + filename
                for row in rows:
                    combined_writer.writerow([filename, entry['record'], *row])
        try:
            with zipfile.ZipFile(stage, 'w', zipfile.ZIP_DEFLATED) as archive:
                manifest = self.snapshot(job['id'])
                manifest.update(status='cancelled' if job['cancel'].is_set() else 'completed', export=destination.name)
                manifest.update(finished_at=datetime.now().astimezone().isoformat(), current='결과 ZIP 저장 완료')
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False))
                archive.writestr('summary.csv', output.getvalue().encode('utf-8-sig'))
                archive.writestr('results.csv', combined.getvalue().encode('utf-8-sig'))
                archive.writestr('README.txt', 'MOPAC Studio batch export\n'
                    'summary.csv: per-file and per-calculation status; UTF-8 BOM for Excel.\n'
                    'results.csv: combined per-file calculation properties and values.\n'
                    'inputs/: original uploaded files (unchanged).\n'
                    'structures/NNNN/session.json: input coordinates, options and full results; reopen in Studio.\n'
                    'structures/NNNN/calculations/: MOPAC input, output and orbital data.\n'
                    'Input and optimized coordinates are distinct; see optimized_atoms in results.\n'
                    'No viewer image or cube is generated automatically.\n')
                for folder in ('inputs', 'structures'):
                    for path in sorted((root / folder).rglob('*')):
                        if path.is_file() and not path.is_symlink():
                            archive.write(path, path.relative_to(root).as_posix())
            stage.replace(destination)
        finally:
            stage.unlink(missing_ok=True)
        return destination
