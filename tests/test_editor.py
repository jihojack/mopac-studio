"""Quick chemistry regression tests: python -m unittest discover -s tests"""
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor_3d import from_editor
from structure import StructureError, from_smiles
import mopac_runner


def atom(symbol,x=0.,y=0.,z=0.,formal_charge=0):
    return dict(symbol=symbol,x=x,y=y,z=z,formal_charge=formal_charge)

class EditorTests(unittest.TestCase):
    def test_methane_and_fixed_xyz(self):
        m=from_editor(dict(name='Methane',atoms=[atom('C',3,2,1)],bonds=[]))
        self.assertEqual(m['formula'],'CH4')
        self.assertEqual((m['atoms'][0]['x'],m['atoms'][0]['y'],m['atoms'][0]['z']),(3,2,1))

    def test_ethanol_and_mopac_input(self):
        m=from_editor(dict(name='ethanol', atoms=[atom('C'),atom('C',1.5),atom('O',2.6,1)],
                    bonds=[dict(a=0,b=1,order=1),dict(a=1,b=2,order=1)]))
        self.assertEqual(m['formula'],'C2H6O')
        text=mopac_runner.build_input(m,'geometry')
        self.assertIn('PM7',text)
        self.assertIn('H ',text)

    def test_double_bond(self):
        m=from_editor(dict(atoms=[atom('C'),atom('C',1.34)],bonds=[dict(a=0,b=1,order=2)]))
        self.assertEqual(m['formula'],'C2H4')

    def test_charged_atom(self):
        m=from_editor(dict(atoms=[atom('N',formal_charge=1)],bonds=[]))
        self.assertEqual(m['charge'],1)
        self.assertEqual(m['formula'],'H4N+')

    def test_aromatic_import_can_roundtrip(self):
        mol=from_smiles('c1ccccc1')
        heavy=[a for a in mol['atoms'] if a['symbol']!='H']
        bonds=[b for b in mol['bonds'] if b['a']<6 and b['b']<6]
        m=from_editor(dict(atoms=heavy,bonds=bonds))
        self.assertEqual(m['formula'],'C6H6')

    def test_invalid_carbon_valence(self):
        payload=dict(atoms=[atom('C',float(i)) for i in range(6)],
                    bonds=[dict(a=0,b=i,order=1) for i in range(1,6)])
        with self.assertRaises(StructureError):
            from_editor(payload)

    def test_duplicate_bonds_rejected(self):
        with self.assertRaises(StructureError):
            from_editor(dict(atoms=[atom('C'),atom('C',1.5)],bonds=[dict(a=0,b=1,order=1)]*2))

    def test_two_disconnected_molecules(self):
        # Two separate methane components in a single MOPAC input.
        inp=dict(name='methane pair', atoms=[atom('C',0,0,0),atom('C',6,0,0)],bonds=[])
        res=from_editor(inp)
        self.assertEqual(res['formula'],'C2H8')
        self.assertEqual(res['heavy_atom_count'],2)
        self.assertEqual(res['atoms'][0]['x'],0)
        self.assertEqual(res['atoms'][1]['x'],6)
        text=mopac_runner.build_input(res,'geometry')
        self.assertEqual(text.count(' C '),0)  # MOPAC uses 'C ' at line beginnings.
        self.assertEqual(sum(line.startswith('C ') for line in text.splitlines()),2)

    def test_relax_disconnected_components(self):
        res=from_editor(dict(atoms=[atom('O',0,0,0),atom('O',5,0,0)],bonds=[]),relax_heavy=True)
        self.assertEqual(res['formula'],'H4O2')

    def test_relax_option_changes_bad_geometry(self):
        d=dict(atoms=[atom('C'),atom('C',1.5),atom('O',2.6,1)],bonds=[dict(a=0,b=1,order=1),dict(a=1,b=2,order=1)])
        fixed=from_editor(d)
        relaxed=from_editor(d,relax_heavy=True)
        self.assertEqual(fixed['atoms'][0]['x'],0)
        self.assertNotEqual(relaxed['atoms'][0]['x'],0)

if __name__=='__main__':unittest.main()
