"""Shared palette, metal atom preservation and computation boundaries."""
import copy
from html.parser import HTMLParser
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rdkit import Chem
import editor_3d as editor
import mopac_runner
import app as studio
from element_data import ELEMENTS, AUTO_H_ELEMENTS, STANDARD_MOPAC_ELEMENTS
from exporting import export_project, load_export
from structure import StructureError, parse_xyz


def atom(symbol, x=3.123456789, **extra):
    return dict(symbol=symbol, x=x, y=-2.123456789, z=1.123456789, **extra)


class PaletteParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.current = None; self.values = {}
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'select':
            self.current = attrs.get('id')
        elif tag == 'option' and self.current in ('editorElement', 'editorAtomElement'):
            self.values.setdefault(self.current, []).append(attrs['value'])
    def handle_endtag(self, tag):
        if tag == 'select':
            self.current = None


class ElementTests(unittest.TestCase):
    def test_both_selectors_use_all_118_unique_real_elements(self):
        parser = PaletteParser()
        parser.feed(studio.app.test_client().get('/').get_data(as_text=True))
        expected = {e['symbol'] for e in ELEMENTS}
        self.assertEqual(len(ELEMENTS), 118)
        self.assertEqual(len(STANDARD_MOPAC_ELEMENTS),70)
        for symbols in parser.values.values():
            self.assertEqual(len(symbols),118)
            self.assertEqual(set(symbols),expected)
        self.assertEqual(set(parser.values),{'editorElement','editorAtomElement'})
        self.assertEqual(ELEMENTS[25]['name'],'철')
        self.assertEqual(ELEMENTS[-1]['symbol'],'Og')

    def test_every_element_applies_with_exact_original_coordinates(self):
        for entry in ELEMENTS:
            with self.subTest(symbol=entry['symbol']):
                original = atom(entry['symbol'])
                result = editor.from_editor(dict(atoms=[original],bonds=[]))
                for key in ('symbol','x','y','z'):
                    self.assertEqual(result['atoms'][0][key],original[key])
                if entry['symbol'] not in AUTO_H_ELEMENTS:
                    self.assertEqual(len(result['atoms']),1,'Do not invent hydrides')

    def test_fe_charge_and_explicit_hydrogen_remain_intact(self):
        payload = dict(name='FeH', atoms=[atom('Fe',formal_charge=2),atom('H',x=4.7)],
                       bonds=[dict(a=0,b=1,order=1)])
        before = copy.deepcopy(payload)
        result = editor.from_editor(payload)
        self.assertEqual(payload,before)
        self.assertEqual(len(result['atoms']),2)
        self.assertEqual(result['charge'],2)
        self.assertEqual(result['atoms'][0]['formal_charge'],2)
        for actual, original in zip(result['atoms'],payload['atoms']):
            self.assertEqual(tuple(actual[k] for k in 'xyz'),tuple(original[k] for k in 'xyz'))

    def test_organic_ligand_hydrogens_still_added_but_not_to_fe(self):
        result = editor.from_editor(dict(atoms=[atom('Fe'),atom('C',x=5.1)],
                                         bonds=[dict(a=0,b=1,order=1)]))
        self.assertEqual(sum(a['symbol']=='H' for a in result['atoms']),3)
        self.assertFalse(any(b['a']==0 and result['atoms'][b['b']]['symbol']=='H' or
                             b['b']==0 and result['atoms'][b['a']]['symbol']=='H' for b in result['bonds']))

    def test_unsupported_forcefield_is_recoverable_and_keeps_metal_structure(self):
        payload = dict(atoms=[atom('Fe')],bonds=[])
        before = copy.deepcopy(payload)
        with patch.object(editor,'_forcefield',return_value=None):
            response = studio.app.test_client().post('/api/structure/editor',json={'mol':payload,'relax':True})
        self.assertEqual(response.status_code,422)
        self.assertTrue(response.json['recoverable'])
        self.assertEqual(payload,before)
        self.assertNotIn('mol',response.json)

    def test_invalid_symbols_and_overvalent_carbon_still_rejected(self):
        for symbol in ('X','XX','Du','fe','Q','Fe2+'):
            with self.subTest(symbol=symbol), self.assertRaises(StructureError):
                editor.from_editor(dict(atoms=[atom(symbol)],bonds=[]))
        with self.assertRaises(StructureError):
            editor.from_editor(dict(atoms=[atom('C')]+[atom('C',x=i+5) for i in range(5)],
                                    bonds=[dict(a=0,b=i,order=1) for i in range(1,6)]))

    def test_fe_input_allowed_but_special_sparkle_dummy_symbols_never_sent_as_atoms(self):
        result = editor.from_editor(dict(atoms=[atom('Fe',formal_charge=2)],bonds=[]))
        text = mopac_runner.build_input(result,'dipole',charge=2,mult=5)
        self.assertIn('CHARGE=2',text)
        self.assertIn('QUINTET',text)
        self.assertIn('\nFe ',text)
        for symbol in ('Ce','At','Fr','Es','Og'):
            with self.subTest(symbol=symbol):
                mol = editor.from_editor(dict(atoms=[atom(symbol)],bonds=[]))
                self.assertTrue(any('미지원' in w for w in mol['warnings']))
                with self.assertRaisesRegex(ValueError,'PM6/PM7'):
                    mopac_runner.build_input(mol,'dipole')

    def test_all_extended_elements_can_export_and_restore(self):
        mol = dict(name='Fe and Og',atoms=[atom('Fe',formal_charge=2),atom('Og',x=8)],bonds=[],editor_draft=True)
        with tempfile.TemporaryDirectory() as temporary:
            for kind in ('json','xyz','mol','sdf'):
                path = export_project({'format':kind,'structure':mol},temporary)
                if kind == 'json':
                    self.assertEqual(load_export(path)[0]['atoms'],mol['atoms'])
                elif kind == 'xyz':
                    self.assertEqual(parse_xyz(path.read_text(encoding='utf-8'))['formula'],'FeOg')
                else:
                    parsed = Chem.MolFromMolBlock(path.read_text(encoding='utf-8'),removeHs=False)
                    self.assertEqual([a.GetSymbol() for a in parsed.GetAtoms()],['Fe','Og'])
        self.assertEqual(parse_xyz('1\nOg\n118 0 0 0\n')['atoms'][0]['symbol'],'Og')


if __name__ == '__main__':
    unittest.main()
