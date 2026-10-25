"""Cube API regression: atomic number is independent of spatial Z coordinate."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
import mo_cube


class CubeApiTests(unittest.TestCase):
    def test_negative_zero_positive_and_large_z_do_not_change_element(self):
        for z in (-2.25, -1.5, 0., .9, 7.9, 119.5):
            with self.subTest(z=z), tempfile.TemporaryDirectory() as folder:
                mgf_path = Path(folder) / 'coordinate-test.mgf'
                mgf_path.write_text('placeholder', encoding='utf-8')
                atoms = [(6, 4.75, -2.5, z), (1, 5.65, -2.4, z + .2),
                         (8, 4.75, -1.1, z - .5)]
                with patch.object(mo_cube, 'parse_mgf', return_value={'atoms': atoms}), \
                     patch.object(mo_cube, 'generate_cube', return_value=('cube fixture', .15)):
                    response = app.test_client().post('/api/cube', json={
                        'mgf_path': str(mgf_path), 'orbital_index': 0})
                self.assertEqual(response.status_code, 200)
                result = response.get_json()
                self.assertTrue(result['ok'])
                self.assertEqual([a['symbol'] for a in result['atoms']], ['C', 'H', 'O'])
                self.assertEqual(result['unit'], 'angstrom')
                for source, returned in zip(atoms, result['atoms']):
                    self.assertEqual(tuple(returned[k] for k in 'xyz'), source[1:])

    def test_real_mgf_homo_lumo_cube_and_atoms_share_coordinates(self):
        # Small valid MOPAC GRAPHF fixture, shifted away from the origin with
        # negative Z. No force field or MOPAC executable is required.
        text = ('2 MOPAC-Graphical data Version 2016\n'
                '1 4.75 -2.5 -1.25\n1 5.49 -2.5 -1.25\n'
                '1.0 0.0 0.0\n1.0 0.0 0.0\n'
                ' ORBITAL 2 1a1 -10.0000\n'
                ' 0.70710678D+00 0.70710678D+00\n'
                ' ORBITAL 0 1b1 1.0000\n'
                ' 0.70710678D+00-0.70710678D+00\n')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'translated-hydrogen.mgf'
            path.write_text(text, encoding='utf-8')
            client = app.test_client()
            for index in (0, 1):
                with self.subTest(orbital=index):
                    response = client.post('/api/cube', json={
                        'mgf_path': str(path), 'orbital_index': index, 'spacing': .3})
                    self.assertEqual(response.status_code, 200)
                    data = response.get_json()
                    self.assertEqual([a['symbol'] for a in data['atoms']], ['H', 'H'])
                    lines = data['cube'].splitlines()
                    self.assertTrue(all(int(lines[i].split()[0]) < 0 for i in (3, 4, 5)))
                    for i, atom in enumerate(data['atoms']):
                        self.assertEqual(tuple(map(float, lines[6+i].split()[2:])),
                                         tuple(atom[k] for k in 'xyz'))
                    self.assertGreater(data['maxabs'], 0)


if __name__ == '__main__':
    unittest.main()
