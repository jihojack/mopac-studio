"""Offline tests for verified downloads, safe installation and repair."""
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine_setup as setup


class EngineSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'studio with spaces'
        self.root.mkdir()
        self.archive = Path(self.temp.name) / 'official-fixture.zip'
        self.spec = dict(setup.ASSETS['Windows'])
        with zipfile.ZipFile(self.archive, 'w') as zf:
            for name, data in [('bin/mopac.exe', 'test executable'), ('bin/mopac.dll', 'test library'),
                               ('LICENSE', 'Apache License fixture')]:
                zf.writestr(self.spec['folder'] + '/' + name, data)
        self.spec['sha256'] = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        for mock in (patch.dict(os.environ, {}, clear=True),
                     patch.object(setup, 'asset_for_platform', return_value=self.spec)):
            mock.start()
            self.addCleanup(mock.stop)
        download = patch.object(setup, '_download', side_effect=lambda url, dst: shutil.copyfile(self.archive, dst))
        self.download = download.start()
        self.addCleanup(download.stop)

    def test_install_keeps_runtime_and_license_and_receipt(self):
        executable = setup.ensure_engine(self.root)
        self.assertTrue(executable.is_file())
        destination = executable.parent.parent
        self.assertTrue((destination / 'LICENSE').is_file())
        self.assertTrue((destination / 'bin' / 'mopac.dll').is_file())
        self.assertTrue(setup._installed(destination, self.spec))

    def test_second_install_is_offline_and_does_not_download(self):
        first = setup.ensure_engine(self.root)
        self.download.reset_mock()
        self.assertEqual(setup.ensure_engine(self.root), first)
        self.download.assert_not_called()

    def test_checksum_failure_never_installs_executable(self):
        self.spec['sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, '체크섬'):
            setup.ensure_engine(self.root)
        self.assertFalse((self.root / '_engines' / self.spec['folder']).exists())
        self.assertEqual(list((self.root / '_engines').glob('install-*')), [])

    def test_corrupted_runtime_is_repaired_and_old_copy_preserved(self):
        executable = setup.ensure_engine(self.root)
        executable.with_name('mopac.dll').write_text('damaged', encoding='utf-8')
        setup.ensure_engine(self.root)
        self.assertEqual(executable.with_name('mopac.dll').read_text(), 'test library')
        backups = list((self.root / '_engines').glob('*.previous-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'bin' / 'mopac.dll').read_text(), 'damaged')

    def test_failed_redownload_does_not_move_existing_install(self):
        executable = setup.ensure_engine(self.root)
        executable.write_text('preserve this damaged file', encoding='utf-8')
        self.download.side_effect = OSError('offline')
        with self.assertRaises(RuntimeError):
            setup.ensure_engine(self.root)
        self.assertEqual(executable.read_text(), 'preserve this damaged file')

    def test_invalid_receipt_triggers_safe_repair(self):
        executable = setup.ensure_engine(self.root)
        (executable.parent.parent / 'installation.json').write_text('[]', encoding='utf-8')
        setup.ensure_engine(self.root)
        self.assertTrue(setup._installed(executable.parent.parent, self.spec))

    def test_explicit_engine_is_preserved_without_download(self):
        configured = self.root / 'custom engine.exe'
        configured.touch()
        with patch.dict(os.environ, {'MOPAC_EXE': str(configured)}):
            self.assertEqual(setup.ensure_engine(self.root), configured.resolve())
        self.download.assert_not_called()

    def test_invalid_explicit_engine_is_not_silently_replaced(self):
        with patch.dict(os.environ, {'MOPAC_EXE': str(self.root / 'missing.exe')}):
            with self.assertRaises(RuntimeError):
                setup.ensure_engine(self.root)
        self.download.assert_not_called()

    def test_archive_cannot_escape_install_directory(self):
        with zipfile.ZipFile(self.archive, 'w') as zf:
            zf.writestr('../../../outside.exe', 'escape')
        self.spec['sha256'] = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        with self.assertRaises(RuntimeError):
            setup.ensure_engine(self.root)
        self.assertFalse((self.root / 'outside.exe').exists())


if __name__ == '__main__':
    unittest.main()
