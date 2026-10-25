"""Coordinate-preserving export, ZIP contents, restore and file-opening API."""
import base64
import copy
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rdkit import Chem
import app as studio
from exporting import export_project, load_export

PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZFEAAAAASUVORK5CYII='


def molecule():
    return {'name': '물 : draft/structure', 'editor_draft': True, 'charge': 0,
            'atoms': [dict(symbol='O', x=1.123456789, y=-2.2, z=-1.1),
                      dict(symbol='H', x=2.08, y=-2.2, z=-1.1),
                      dict(symbol='H', x=.88, y=-1.28, z=-1.1)],
            'bonds': [dict(a=0, b=1, order=1), dict(a=0, b=2, order=1)]}


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'workspace'
        self.root.mkdir()
        self.payload = {'format': 'zip', 'structure': molecule(), 'image': PNG,
                        'results': [{'calc_key': 'dipole', 'label': '쌍극자', 'status': 'ok',
                                     'data': {'dipole': {'x': -1.25, 'total': 1.25}}}]}

    def test_json_keeps_exact_coordinates_graph_results_and_draft(self):
        self.payload['format'] = 'json'
        before = copy.deepcopy(self.payload)
        path = export_project(self.payload, self.root)
        restored, results = load_export(path)
        self.assertEqual(restored, before['structure'])
        self.assertEqual(results, before['results'])
        self.assertEqual(self.payload, before)
        self.assertTrue(json.loads(path.read_text(encoding='utf-8'))['draft'])

    def test_xyz_keeps_input_precision_and_does_not_add_hydrogens(self):
        self.payload['format'] = 'xyz'
        text = export_project(self.payload, self.root).read_text(encoding='utf-8')
        self.assertEqual(text.splitlines()[0], '3')
        self.assertEqual(float(text.splitlines()[2].split()[1]), 1.123456789)

    def test_mol_and_sdf_keep_coordinates_and_explicit_bonds(self):
        for kind in ('mol', 'sdf'):
            with self.subTest(kind=kind):
                self.payload['format'] = kind
                text = export_project(self.payload, self.root).read_text(encoding='utf-8')
                mol = Chem.MolFromMolBlock(text, sanitize=False, removeHs=False)
                self.assertEqual(mol.GetNumAtoms(), 3)
                self.assertEqual(mol.GetNumBonds(), 2)
                self.assertAlmostEqual(mol.GetConformer().GetAtomPosition(0).x, 1.123456789, places=4)
                if kind == 'sdf':
                    self.assertIn('$$$$', text)

    def test_unbonded_atoms_stay_unbonded(self):
        self.payload.update(format='mol', structure={'name': 'unbonded', 'atoms': [
            dict(symbol='C', x=0, y=0, z=0), dict(symbol='C', x=1.5, y=0, z=0)], 'bonds': []})
        text = export_project(self.payload, self.root).read_text(encoding='utf-8')
        self.assertEqual(Chem.MolFromMolBlock(text, sanitize=False).GetNumBonds(), 0)

    def test_invalid_valence_draft_can_be_archived_without_optimization(self):
        atoms = [dict(symbol='C', x=i, y=0, z=0) for i in range(6)]
        self.payload['structure'] = {'editor_draft': True, 'atoms': atoms,
                                     'bonds': [dict(a=0, b=i, order=1) for i in range(1, 6)]}
        path = export_project(self.payload, self.root)
        with zipfile.ZipFile(path) as zf:
            record = json.loads(zf.read('session.json'))
            self.assertEqual(record['structure']['atoms'], atoms)
            self.assertTrue(record['draft'])

    def test_zip_contains_displayed_image_summary_and_raw_files(self):
        run = self.root / 'runs' / 'sample'
        run.mkdir(parents=True)
        (run / 'dipole.out').write_text('raw result', encoding='utf-8')
        (run / 'dipole.mop').write_text('original coordinates', encoding='utf-8')
        self.payload['results'][0]['run_dir'] = str(run)
        path = export_project(self.payload, self.root)
        with zipfile.ZipFile(path) as zf:
            self.assertIsNone(zf.testzip())
            self.assertTrue({'structure.xyz', 'structure.mol', 'structure.sdf', 'session.json',
                             'results.csv', 'view.png', 'README.txt', 'runs/sample/dipole.out'}.issubset(zf.namelist()))
            self.assertEqual(zf.read('runs/sample/dipole.out'), b'raw result')
            self.assertEqual(zf.read('view.png'), base64.b64decode(PNG.split(',')[1]))

    def test_raw_file_opt_out_and_outside_workspace_are_respected(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'private.out').write_text('not part of workspace', encoding='utf-8')
        self.payload['results'][0]['run_dir'] = str(outside)
        for include in (True, False):
            self.payload['include_raw'] = include
            with zipfile.ZipFile(export_project(self.payload, self.root)) as zf:
                self.assertFalse(any(n.startswith('runs/') for n in zf.namelist()))

    def test_csv_has_excel_bom_and_keeps_negative_numeric_values(self):
        self.payload['format'] = 'csv'
        data = export_project(self.payload, self.root).read_bytes()
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
        self.assertTrue(any(row[-1] == '-1.25' for row in rows))

    def test_png_is_saved_verbatim(self):
        self.payload['format'] = 'png'
        self.assertEqual(export_project(self.payload, self.root).read_bytes(), base64.b64decode(PNG.split(',')[1]))

    def test_failed_export_does_not_remove_previous_files_or_leave_temp_file(self):
        existing = export_project(self.payload, self.root)
        original = existing.read_bytes()
        self.payload.update(format='png', image='bad image')
        with self.assertRaises(ValueError):
            export_project(self.payload, self.root)
        self.assertEqual(existing.read_bytes(), original)
        self.assertEqual(list((self.root / 'exports').glob('.export-*')), [])

    def test_invalid_graph_and_nonfinite_coordinates_are_rejected(self):
        for bad in ({'atoms': []}, {'atoms': [dict(symbol='C', x=float('nan'), y=0, z=0)]},
                    {'atoms': [dict(symbol='C', x=0, y=0, z=0)], 'bonds': [dict(a=0, b=4, order=1)]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                export_project({'format': 'json', 'structure': bad}, self.root)

    def test_unique_safe_filenames_do_not_overwrite(self):
        first = export_project(self.payload, self.root)
        second = export_project(self.payload, self.root)
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, self.root / 'exports')
        self.assertNotIn(':', first.name)


class ExportApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.object(studio, 'WORKSPACE', str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = studio.app.test_client()

    def test_export_download_and_json_restore(self):
        response = self.client.post('/api/export', json={'format': 'json', 'structure': molecule()})
        self.assertEqual(response.status_code, 200)
        saved = response.get_json()
        download = self.client.get('/api/files/download', query_string={'path': saved['path']})
        self.assertEqual(download.status_code, 200)
        self.assertIn('attachment', download.headers['Content-Disposition'])
        self.assertEqual(json.loads(download.data)['structure'], molecule())
        download.close()
        loaded = self.client.post('/api/files/load', json={'path': saved['path']}).get_json()
        self.assertEqual(loaded['mol'], molecule())

    def test_open_folder_uses_containing_folder_and_never_executes_file(self):
        file = self.root / 'test.xyz'
        file.touch()
        with patch.object(studio, '_open_folder') as opened:
            response = self.client.post('/api/files/open-folder', json={'path': str(file)})
        self.assertEqual(response.status_code, 200)
        opened.assert_called_once_with(self.root.resolve())

    def test_outside_download_and_open_folder_are_rejected(self):
        with tempfile.TemporaryDirectory() as outside, patch.object(studio, '_open_folder') as opened:
            self.assertEqual(self.client.post('/api/files/open-folder', json={'path': outside}).status_code, 400)
            self.assertEqual(self.client.get('/api/files/download', query_string={'path': outside}).status_code, 400)
        opened.assert_not_called()

    def test_empty_csv_and_invalid_json_restore_return_clear_errors(self):
        response = self.client.post('/api/export', json={'format': 'csv', 'structure': molecule()})
        self.assertEqual(response.status_code, 400)
        invalid = self.root / 'not-a-session.json'
        invalid.write_text('{}', encoding='utf-8')
        self.assertEqual(self.client.post('/api/files/load', json={'path': str(invalid)}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
