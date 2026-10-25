"""Batch failures, cancellation, archival and upload boundaries."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rdkit import Chem
import app as studio
import batch_calculations as batch
from exporting import load_export, mol_text
from structure import from_smiles

WATER = b'3\nwater\nO 0 0 0\nH .9572 0 0\nH -.2399872 .927297 0\n'


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='MOPAC batch ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.begin, self.end = Mock(), Mock()
        self.calls = []
        self.block = None
        self.entered = threading.Event()
        self.failure = False
        def calculate(mol, key, **kwargs):
            self.calls.append((mol, key, kwargs))
            self.entered.set()
            if self.block:
                self.block.wait(10)
            if self.failure and key == 'dipole':
                raise RuntimeError('test calculation failed')
            folder = Path(kwargs['run_dir'])
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (key + '.out')).write_text('test output', encoding='utf-8')
            return {'calc_key': key, 'label': key, 'status': 'ok', 'data': {'value': -1.25},
                    'run_dir': str(folder)}, str(folder)
        self.manager = batch.BatchManager(lambda: self.root, calculate, self.begin, self.end)
        for change in (patch.object(studio, 'WORKSPACE', str(self.root)), patch.object(studio, 'BATCH', self.manager)):
            change.start(); self.addCleanup(change.stop)
        self.client = studio.app.test_client()
        self.identifiers = []
        self.addCleanup(self.finish_workers)

    def finish_workers(self):
        if self.block:
            self.block.set()
        for identifier in self.identifiers:
            self.wait(identifier)

    def submit(self, files=None, settings=None):
        settings = settings or {'calc_keys': ['geometry', 'dipole'], 'charge': None, 'mult': 1, 'eps': 78.4}
        response = self.client.post('/api/batch', data={'options': json.dumps(settings), 'files': [
            (io.BytesIO(data), name) for name, data in (files or [('water.xyz', WATER)])]}, content_type='multipart/form-data')
        if response.status_code == 202:
            self.identifiers.append(response.json['job']['id'])
        return response

    def wait(self, identifier):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = self.manager.snapshot(identifier)
            if job['status'] in batch.TERMINAL and self.manager.active != identifier:
                return job
            time.sleep(.01)
        self.fail('batch did not finish')

    def completed(self, files=None, settings=None):
        response = self.submit(files, settings)
        self.assertEqual(response.status_code, 202, response.json)
        return self.wait(response.json['job']['id'])

    def test_duplicates_failures_and_archive_contents(self):
        job = self.completed([('물.xyz', WATER), ('물.xyz', WATER), ('bad.xyz', b'invalid'), ('no.txt', b'unsupported')])
        self.assertEqual(job['status'], 'completed', job)
        self.assertEqual([e['status'] for e in job['entries']], ['ok', 'ok', 'error', 'error'])
        self.assertEqual((job['completed'], job['total']), (8, 8))
        self.assertEqual(len(self.calls), 4)
        self.assertNotEqual(self.calls[0][2]['run_dir'], self.calls[2][2]['run_dir'])
        self.begin.assert_called_once(); self.end.assert_called_once()
        with zipfile.ZipFile(job['export']) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read('inputs/0001/물.xyz'), WATER)
            self.assertEqual(archive.read('inputs/0002/물.xyz'), WATER)
            self.assertIn('structures/0002/calculations/dipole.out', archive.namelist())
            self.assertTrue(archive.read('summary.csv').startswith(b'\xef\xbb\xbf'))
            self.assertIn('-1.25', archive.read('results.csv').decode('utf-8-sig'))
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['status'], 'completed')
        mol, results = load_export(Path(job['directory']) / 'structures/0001/session.json')
        self.assertEqual(mol['atoms'][2]['x'], -.2399872)
        self.assertEqual(len(results), 2)

    def test_calculation_exception_continues_to_next_option_and_file(self):
        self.failure = True
        job = self.completed([('a.xyz', WATER), ('b.xyz', WATER)])
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(len(self.calls), 4)
        self.assertTrue(all(e['status'] == 'error' for e in job['entries']))
        self.assertIn('test calculation failed', job['entries'][0]['results'][1]['errors'][0])
        self.assertTrue(Path(job['export']).is_file())

    def test_sdf_expands_all_records_and_recovers_after_bad_record(self):
        water = mol_text(from_smiles('O')) + '\n$$$$\n'
        job = self.completed([('pair.sdf', (water + 'invalid\n$$$$\n' + water).encode())])
        self.assertEqual(len(job['entries']), 3, job)
        self.assertEqual([e['status'] for e in job['entries']], ['ok', 'error', 'ok'])
        self.assertEqual(len(self.calls), 4)

    def test_cancel_waits_for_current_calculation_and_exports_partial_results(self):
        self.block = threading.Event()
        response = self.submit([('a.xyz', WATER), ('b.xyz', WATER)])
        identifier = response.json['job']['id']
        self.assertTrue(self.entered.wait(5))
        cancelled = self.client.post('/api/batch/'+identifier+'/cancel')
        self.assertTrue(cancelled.json['ok'])
        self.assertEqual(self.manager.snapshot(identifier)['status'], 'running')
        self.begin.assert_called_once(); self.end.assert_not_called()
        self.block.set()
        job = self.wait(identifier)
        self.assertEqual(job['status'], 'cancelled')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual([e['status'] for e in job['entries']], ['cancelled', 'cancelled'])
        with zipfile.ZipFile(job['export']) as archive:
            self.assertIn('inputs/0002/b.xyz', archive.namelist())
            self.assertIn('structures/0001/calculations/geometry.out', archive.namelist())
            self.assertEqual(json.loads(archive.read('manifest.json'))['status'], 'cancelled')

    def test_duplicate_active_submission_is_rejected(self):
        self.block = threading.Event()
        self.submit()
        self.assertTrue(self.entered.wait(5))
        self.assertEqual(self.submit().status_code, 400)
        self.assertEqual(len(list((self.root / 'batches').iterdir())), 1)

    def test_charge_from_structure_or_override_and_common_spin(self):
        charged = mol_text(from_smiles('[NH4+]')).encode()
        self.completed([('ion.mol', charged)])
        self.assertEqual(self.calls[0][2]['charge'], 1)
        self.completed([('ion.mol', charged)], {'calc_keys':['geometry'], 'charge':-1, 'mult':2, 'eps':2})
        self.assertEqual(self.calls[-1][2]['charge'], -1)
        self.assertEqual(self.calls[-1][2]['mult'], 2)

    def test_invalid_options_do_not_start_or_save_uploads(self):
        for changes in ({'calc_keys':[]}, {'calc_keys':['unknown']}, {'calc_keys':['geometry', {}]},
                        {'charge':.5}, {'charge':True}, {'mult':6}, {'mult':1.5}, {'eps':float('nan')}, {'eps':0}):
            with self.subTest(changes=changes):
                settings = {'calc_keys':['geometry'], 'charge':None, 'mult':1, 'eps':78.4, **changes}
                self.assertEqual(self.submit(settings=settings).status_code, 400)
        self.begin.assert_not_called()
        self.assertFalse((self.root / 'batches').exists())

    def test_upload_size_limit_cleans_staging_and_does_not_block_next_job(self):
        with patch.object(batch, 'MAX_FILE_BYTES', 50):
            response = self.submit([('large.xyz', b'x'*51)])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(any((self.root / 'batches').iterdir()))
        self.assertEqual(self.completed()['status'], 'completed')

    def test_upload_names_cannot_escape_workspace(self):
        job = self.completed([('../../outside.xyz', WATER), ('C:\\files\\outside.xyz', WATER)])
        self.assertTrue(all(e['filename'].endswith('outside.xyz') and '/' not in e['filename'] and '\\' not in e['filename'] for e in job['entries']))
        self.assertEqual(batch._filename('C:\\files\\outside.xyz'), 'outside.xyz')
        self.assertFalse((self.root / 'outside.xyz').exists())

    def test_count_and_total_upload_limits(self):
        with patch.object(batch, 'MAX_FILES', 1):
            self.assertEqual(self.submit([('a.xyz', WATER), ('b.xyz', WATER)]).status_code,400)
        with patch.object(batch, 'MAX_TOTAL_BYTES', 10):
            self.assertEqual(self.submit().status_code,400)
        self.assertIsNone(self.manager.active)
        with patch.object(studio, 'MAX_TOTAL_BYTES', -1_999_999):
            self.assertEqual(self.submit().status_code,413)
        self.begin.assert_not_called()

    def test_draft_json_and_undecodable_sdf_fail_without_stopping_valid_file(self):
        record = {'schema':'mopac-studio-export-v1', 'structure':{
            'name':'draft', 'atoms':[dict(symbol='C',x=0,y=0,z=0)], 'bonds':[], 'editor_draft':True}}
        job = self.completed([('draft.json',json.dumps(record).encode()), ('binary.sdf',b'\xff'), ('good.xyz',WATER)])
        self.assertEqual([e['status'] for e in job['entries']],['error','error','ok'])
        self.assertEqual(len(self.calls),2)

    def test_xyz_truncation_nonfinite_and_extra_frames_fail_without_running(self):
        for contents in (b'4\nwater\nO 0 0 0\n', b'1\nnan\nO nan 0 0\n', WATER+WATER):
            with self.subTest(contents=contents):
                job = self.completed([('bad.xyz', contents)])
                self.assertEqual(job['entries'][0]['status'], 'error')
        self.assertFalse(self.calls)

    def test_all_invalid_files_still_export_failure_summary(self):
        job = self.completed([('bad.xyz', b'no'), ('bad.sdf', b'')])
        self.assertEqual(job['status'], 'completed')
        self.assertTrue(Path(job['export']).is_file())
        self.assertTrue(all(e['status'] == 'error' for e in job['entries']))

    def test_saved_status_is_read_after_restart_and_unfinished_job_is_interrupted(self):
        job = self.completed()
        restarted = batch.BatchManager(lambda: self.root, Mock(), Mock(), Mock())
        self.assertEqual(restarted.snapshot(job['id'])['export'], job['export'])
        path = Path(job['directory'])/'job.json'
        saved = json.loads(path.read_text(encoding='utf8')); saved['status']='running'
        path.write_text(json.dumps(saved),encoding='utf8')
        self.assertEqual(restarted.snapshot(job['id'])['status'],'interrupted')
        for invalid in ('../../anything', 'not-a-job', '0'*32):
            self.assertEqual(self.client.get('/api/batch/'+invalid).status_code,404)

    def test_export_can_be_downloaded_through_existing_api(self):
        job = self.completed()
        response = self.client.get('/api/files/download', query_string={'path':job['export']})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.headers['Content-Disposition'].startswith('attachment'))
        response.close()

    def test_file_tree_skips_staging_and_survives_files_disappearing_during_refresh(self):
        (self.root/'job.tmp').write_text('temporary')
        (self.root/'.export-in-progress').mkdir()
        (self.root/'removed.xyz').write_text('removed during scan')
        (self.root/'keep.xyz').write_bytes(WATER)
        original = studio.os.path.getsize
        def size(path):
            if Path(path).name == 'removed.xyz':
                raise FileNotFoundError(path)
            return original(path)
        with patch.object(studio.os.path, 'getsize', side_effect=size):
            response = self.client.get('/api/files')
        self.assertEqual(response.status_code,200)
        self.assertEqual([item['name'] for item in response.json['tree']],['keep.xyz'])
        self.assertEqual(studio._walk(str(self.root/'missing')),[])


if __name__ == '__main__':
    unittest.main()
