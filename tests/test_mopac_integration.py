"""Real official-engine integration tests. Enable with RUN_MOPAC_INTEGRATION=1."""
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as studio
import mopac_runner as runner
from engine_setup import managed_executable
from structure import from_smiles
from editor_3d import from_editor


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


if __name__ == '__main__':
    unittest.main()
