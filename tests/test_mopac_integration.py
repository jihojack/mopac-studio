"""Real official-engine integration tests. Enable with RUN_MOPAC_INTEGRATION=1."""
import math
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as studio
import mopac_runner as runner
from engine_setup import managed_executable
from structure import from_smiles
from editor_3d import from_editor
from batch_calculations import BatchManager, TERMINAL
from exporting import xyz_text


@unittest.skipUnless(os.environ.get('RUN_MOPAC_INTEGRATION') == '1', 'requires installed official engine')
class OfficialMopacTests(unittest.TestCase):
    def setUp(self):
        executable = managed_executable()
        self.assertTrue(executable and executable.is_file(), 'Run python engine_setup.py first')
        self.temp = tempfile.TemporaryDirectory(prefix='MOPAC integration ')
        self.addCleanup(self.temp.cleanup)
        for mock in (patch.object(studio, 'WORKSPACE', self.temp.name),
                     patch.object(runner, 'MOPAC_EXE', str(executable)),
                     patch.object(runner, 'MOPAC_DIR', str(executable.parent))):
            mock.start()
            self.addCleanup(mock.stop)
        self.client = studio.app.test_client()
        self.water = from_smiles('O', 'Water integration')

    def calculate(self, mol, key):
        response = self.client.post('/api/calculate_one', json={'mol': mol, 'calc_key': key,
                                                               'charge': 0, 'mult': 1})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['ok'])
        result = data['result']
        self.assertEqual(result['status'], 'ok', result.get('errors'))
        self.assertTrue(result['finished'])
        return result

    def test_geometry_energy_charges_and_dipole_through_api(self):
        geometry = self.calculate(self.water, 'geometry')['data']['optimized_atoms']
        self.assertEqual(len(geometry), 3)
        self.assertTrue(all(math.isfinite(a[k]) for a in geometry for k in 'xyz'))
        heat = self.calculate(self.water, 'heat_of_formation')['data']['생성엔탈피_kcal_mol']
        self.assertTrue(math.isfinite(heat))
        dipole = self.calculate(self.water, 'dipole')['data']['dipole']
        self.assertGreater(dipole['total'], 0)
        charges = self.calculate(self.water, 'atomic_charges')['data']['charges']
        self.assertEqual(len(charges), 3)

    def test_vibrations_with_preoptimization_through_api(self):
        result = self.calculate(self.water, 'vibrations')
        self.assertGreaterEqual(result['data']['n_modes'], 3)
        self.assertTrue(all(math.isfinite(f) for f in result['data']['frequencies_cm1']))
        self.assertNotEqual(result['preoptimization']['source'], 'input_geometry')

    def test_editor_fe_ion_reaches_real_pm7_engine_with_charge_and_spin(self):
        response = self.client.post('/api/structure/editor',json={'mol':{'name':'Fe ion',
            'atoms':[dict(symbol='Fe',formal_charge=2,x=3.123456789,y=-2.5,z=1.5)],'bonds':[]}})
        self.assertEqual(response.status_code,200,response.json)
        mol = response.json['mol']
        self.assertEqual(len(mol['atoms']),1)
        self.assertEqual(mol['atoms'][0]['x'],3.123456789)
        result = self.client.post('/api/calculate_one',json={'mol':mol,'calc_key':'dipole','charge':2,'mult':5}).json['result']
        self.assertEqual(result['status'],'ok',result)
        self.assertTrue(result['finished'])
        self.assertIn('QUINTET',result['input'])
        self.assertIn('CHARGE=2',result['input'])
        self.assertIn('\nFe ',result['input'])

    def test_homo_lumo_api_keeps_all_disconnected_atoms(self):
        pair = from_editor({'name': 'Two methane molecules', 'atoms': [
            dict(symbol='C', x=-4, y=0, z=-1), dict(symbol='C', x=4, y=0, z=-1)], 'bonds': []})
        result = self.calculate(pair, 'molecular_orbitals')
        self.assertEqual(len(result['data']['optimized_atoms']), 10)
        self.assertTrue(result['data']['orbitals'])
        for key in ('homo_index', 'lumo_index'):
            response = self.client.post('/api/cube', json={'mgf_path': result['mgf_path'],
                'orbital_index': result['data'][key], 'spacing': .3})
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(len(data['atoms']), 10)
            self.assertEqual(sum(a['symbol'] == 'C' for a in data['atoms']), 2)
            self.assertGreater(data['maxabs'], 0)
            self.assertLess(int(data['cube'].splitlines()[3].split()[0]), 0)

    def test_batch_real_engine_exports_all_results_and_retains_failed_file(self):
        manager = BatchManager(lambda: studio.WORKSPACE, studio._run_single_calculation,
                               studio._begin_calculation, studio._end_calculation)
        settings = {'calc_keys':['geometry', 'dipole', 'molecular_orbitals'], 'charge':0, 'mult':1, 'eps':78.4}
        with patch.object(studio, 'BATCH', manager):
            response = self.client.post('/api/batch', data={'options':json.dumps(settings), 'files':[
                (io.BytesIO(xyz_text(self.water).encode()), 'water.xyz'),
                (io.BytesIO(xyz_text(from_smiles('C')).encode()), 'water.xyz'),
                (io.BytesIO(b'not a structure'), 'bad.xyz')]})
            self.assertEqual(response.status_code,202,response.json)
            identifier = response.json['job']['id']
            deadline = time.monotonic()+120
            while time.monotonic()<deadline:
                job = manager.snapshot(identifier)
                if job['status'] in TERMINAL and manager.active is None:
                    break
                time.sleep(.05)
            self.assertEqual(job['status'],'completed',job)
            self.assertEqual([e['status'] for e in job['entries']],['ok','ok','error'],job)
            with zipfile.ZipFile(job['export']) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn('results.csv',archive.namelist())
                for index, count in [('0001',3),('0002',5)]:
                    session = json.loads(archive.read(f'structures/{index}/session.json'))
                    self.assertEqual(len(session['structure']['atoms']),count)
                    results = session['results']
                    self.assertTrue(all(r['status']=='ok' and r['finished'] for r in results))
                    self.assertEqual(len(results[0]['data']['optimized_atoms']),count)
                    self.assertTrue(math.isfinite(results[1]['data']['dipole']['total']))
                    self.assertTrue(results[2]['data']['orbitals'])
                    self.assertIn(f'structures/{index}/calculations/molecular_orbitals.mgf',archive.namelist())


if __name__ == '__main__':
    unittest.main()
