"""Transactional force-field and HTTP regression tests (no MOPAC required)."""
import copy
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rdkit import Chem
from rdkit.Geometry import Point3D
import editor_3d as editor
from app import app


def drawing():
    return {'name': 'preserved', 'atoms': [
        {'symbol': 'C', 'x': 3.123456789, 'y': -2.2, 'z': 1.1},
        {'symbol': 'O', 'x': 4.5, 'y': -2.2, 'z': 1.1}],
        'bonds': [{'a': 0, 'b': 1, 'order': 1}]}


class TrialForceField:
    def __init__(self, mol, outcome):
        self.mol, self.outcome = mol, outcome
        self.fixed = []

    def AddFixedPoint(self, i):
        self.fixed.append(i)

    def Initialize(self):
        pass

    def Minimize(self, **kwargs):
        # Mutate before throwing, as native minimizers can do.
        self.mol.GetConformer().SetAtomPosition(0, Point3D(999, 999, 999))
        if self.outcome == 'bfgs':
            raise RuntimeError('Invariant Violation: bad direction in linearSearch')
        if self.outcome == 'nan':
            self.mol.GetConformer().SetAtomPosition(0, Point3D(float('nan'), 0, 0))
        return 1 if self.outcome == 'not_converged' else 0

    def CalcEnergy(self):
        return 0.


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.payload = drawing()
        self.before = copy.deepcopy(self.payload)
        # Expected failures should not flood test output with native diagnostics.
        self.log_patch = patch.object(editor.log, 'warning')
        self.log_patch.start()
        self.addCleanup(self.log_patch.stop)

    def factory(self, outcomes, starts=None):
        def make(mol, method):
            if starts is not None:
                starts.append(tuple(mol.GetConformer().GetAtomPosition(0)))
            outcome = outcomes[method]
            if outcome == 'unavailable':
                return None
            if outcome == 'construction_failure':
                raise RuntimeError('parameter setup failed')
            return TrialForceField(mol, outcome)
        return make

    def test_bfgs_both_methods_preserves_apply_coordinates_and_warns(self):
        with patch.object(editor, '_forcefield', self.factory(dict(MMFF='bfgs', UFF='bfgs'))):
            result = editor.from_editor(self.payload)
        self.assertEqual(self.payload, self.before)
        self.assertEqual(result['formula'], 'CH4O')
        self.assertEqual(result['optimization']['status'], 'skipped')
        self.assertTrue(result['warnings'])
        for i, a in enumerate(self.payload['atoms']):
            self.assertEqual({k: result['atoms'][i][k] for k in 'xyz'}, {k: a[k] for k in 'xyz'})

    def test_bfgs_relax_raises_without_mutating_input(self):
        with patch.object(editor, '_forcefield', self.factory(dict(MMFF='bfgs', UFF='bfgs'))):
            with self.assertRaises(editor.OptimizationError):
                editor.from_editor(self.payload, relax_heavy=True)
        self.assertEqual(self.payload, self.before)

    def test_uff_retry_starts_at_original_not_failed_mmff_coordinates(self):
        starts = []
        with patch.object(editor, '_forcefield', self.factory(dict(MMFF='bfgs', UFF='ok'), starts)):
            result = editor.from_editor(self.payload, relax_heavy=True)
        self.assertEqual(starts[0], starts[1])
        self.assertEqual(result['optimization']['method'], 'UFF')
        self.assertTrue(result['relaxed_heavy_atoms'])

    def test_nonconvergence_nan_missing_params_and_construction_failure_rejected(self):
        for failure in ('not_converged', 'nan', 'unavailable', 'construction_failure'):
            with self.subTest(failure=failure), patch.object(editor, '_forcefield',
                    self.factory(dict(MMFF=failure, UFF=failure))):
                with self.assertRaises(editor.OptimizationError):
                    editor.from_editor(self.payload, relax_heavy=True)
                result = editor.from_editor(self.payload)
                self.assertEqual(result['optimization']['status'], 'skipped')
                self.assertTrue(all(math.isfinite(a[k]) for a in result['atoms'] for k in 'xyz'))
                self.assertEqual(self.payload, self.before)

    def test_forcefield_cannot_move_original_atoms_on_apply(self):
        with patch.object(editor, '_forcefield', self.factory(dict(MMFF='ok', UFF='ok'))):
            result = editor.from_editor(self.payload)
        self.assertEqual(result['atoms'][0]['x'], self.payload['atoms'][0]['x'])
        self.assertFalse(result['relaxed_heavy_atoms'])

    def test_all_atoms_fixed_with_no_added_h_does_not_minimize(self):
        payload = {'atoms': [dict(symbol='H', x=0, y=0, z=0),
                             dict(symbol='H', x=.74, y=0, z=0)],
                   'bonds': [dict(a=0, b=1, order=1)]}
        with patch.object(editor, '_forcefield', side_effect=AssertionError('all atoms fixed')):
            result = editor.from_editor(payload)
        self.assertEqual(result['optimization']['status'], 'not_required')

    def test_explicit_h_coordinates_preserved(self):
        self.payload['atoms'].append(dict(symbol='H', x=2.2, y=-2.2, z=1.1))
        self.payload['bonds'].append(dict(a=0, b=2, order=1))
        result = editor.from_editor(self.payload)
        self.assertEqual(result['atoms'][2]['x'], 2.2)
        self.assertEqual(result['atoms'][0]['x'], 3.123456789)

    def test_real_sulfur_cluster_and_disconnected_coordinates(self):
        payload = {'atoms': [dict(symbol='C', x=2, y=3, z=4)] + [
            dict(symbol='S', x=2+x, y=3+y, z=4+z)
            for x, y, z in [(1,1,1), (1,-1,-1), (-1,1,-1), (-1,-1,1)]],
            'bonds': [dict(a=0, b=i, order=1) for i in range(1, 5)]}
        result = editor.from_editor(payload)
        for i, atom in enumerate(payload['atoms']):
            self.assertEqual({k: result['atoms'][i][k] for k in 'xyz'}, {k: atom[k] for k in 'xyz'})

    def test_api_returns_recoverable_422_without_partial_molecule(self):
        with patch.object(editor, '_forcefield', self.factory(dict(MMFF='bfgs', UFF='bfgs'))):
            response = app.test_client().post('/api/structure/editor', json={'mol': self.payload, 'relax': True})
        self.assertEqual(response.status_code, 422)
        result = response.get_json()
        self.assertFalse(result['ok'])
        self.assertTrue(result['recoverable'])
        self.assertEqual(result['code'], 'optimization_failed')
        self.assertNotIn('mol', result)

    def test_api_apply_returns_warning_and_original_geometry(self):
        with patch.object(editor, '_forcefield', self.factory(dict(MMFF='bfgs', UFF='bfgs'))):
            response = app.test_client().post('/api/structure/editor', json={'mol': self.payload, 'relax': False})
        self.assertEqual(response.status_code, 200)
        result = response.get_json()['mol']
        self.assertTrue(result['warnings'])
        self.assertEqual(result['atoms'][0]['x'], self.payload['atoms'][0]['x'])

    def test_api_validation_and_hydrogen_generation_failure_are_recoverable(self):
        client = app.test_client()
        for payload in ({}, {'atoms': [], 'bonds': []},
                        {'atoms': [dict(symbol='C', x=float('nan'), y=0, z=0)]}):
            response = client.post('/api/structure/editor', json={'mol': payload})
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.get_json()['recoverable'])
        with patch.object(Chem, 'AddHs', side_effect=RuntimeError('H placement failed')):
            response = client.post('/api/structure/editor', json={'mol': self.payload})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('mol', response.get_json())


if __name__ == '__main__':
    unittest.main()
