"""Cube unit convention regression tests for 3Dmol.js.
Run with: python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mo_cube

class OrbitalAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.atoms = [(6, 4.75, -2.5, 1.25), (1, 5.65, -2.4, 1.2)]
        self.lo = np.array((2.5, -5., -1.), dtype=float)
        self.step = (0.25, 0.5, 0.125)
        self.count = (4, 3, 5)
        self.psi = np.zeros(self.count, dtype=float)
        self.cube = mo_cube._cube_text(self.atoms, self.lo, self.count, self.step, self.psi, 'test')

    def test_negative_grid_counts_mark_angstrom_in_3dmol(self):
        # 3Dmol.js scales positive-count Cube grids by 0.529177; negative grids are Å.
        grid = [self.cube.splitlines()[i].split() for i in (3, 4, 5)]
        self.assertEqual([int(g[0]) for g in grid], [-4, -3, -5])
        self.assertEqual([float(g[i + 1]) for i, g in enumerate(grid)], list(self.step))

    def test_cube_origin_and_atoms_share_coordinate_frame(self):
        lines = self.cube.splitlines()
        np.testing.assert_allclose([float(x) for x in lines[2].split()[1:]], self.lo, atol=1e-6)
        for i, atom in enumerate(self.atoms):
            np.testing.assert_allclose([float(x) for x in lines[6+i].split()[2:]], atom[1:], atol=1e-6)

    def test_grid_data_count_is_unchanged(self):
        entries = self.cube.splitlines()[6+len(self.atoms):]
        self.assertEqual(sum(len(row.split()) for row in entries), int(np.prod(self.count)))

if __name__ == '__main__':
    unittest.main()
