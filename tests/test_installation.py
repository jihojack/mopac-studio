"""Installation failure handling and external-engine discovery regressions."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launcher
import mopac_runner


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'app with spaces'
        self.root.mkdir()
        engine = patch.object(launcher, 'ensure_engine', return_value=self.root / 'mopac.exe')
        self.engine = engine.start()
        self.addCleanup(engine.stop)
        self.env = self.root / '.venv'
        self.requirements = self.root / 'requirements.txt'
        self.requirements.write_text('dependency==1.0\n', encoding='utf-8')
        for name, value in [('ROOT', self.root), ('ENV', self.env), ('REQUIREMENTS', self.requirements)]:
            p = patch.object(launcher, name, value)
            p.start()
            self.addCleanup(p.stop)
        interpreter = launcher.environment_python()
        interpreter.parent.mkdir(parents=True)
        interpreter.touch()

    def stamp(self):
        stamp = self.env / '.mopac-studio-requirements.sha256'
        stamp.write_text(hashlib.sha256(self.requirements.read_bytes()).hexdigest(), encoding='ascii')
        return stamp

    def test_installed_environment_does_not_reinstall(self):
        self.stamp()
        with patch.object(launcher.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            launcher.ensure_environment()
        self.assertEqual(run.call_count, 1)
        self.assertNotIn('pip', run.call_args.args[0])

    def test_missing_modules_trigger_repair(self):
        self.stamp()
        with patch.object(launcher.subprocess, 'run', side_effect=[
                subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)]) as run:
            launcher.ensure_environment()
        self.assertEqual(run.call_count, 2)
        self.assertIn('pip', run.call_args.args[0])

    def test_changed_requirements_install_and_update_stamp(self):
        stamp = self.stamp()
        self.requirements.write_text('dependency==2.0\n', encoding='utf-8')
        with patch.object(launcher.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            launcher.ensure_environment()
        self.assertIn('pip', run.call_args.args[0])
        self.assertEqual(stamp.read_text().strip(), hashlib.sha256(self.requirements.read_bytes()).hexdigest())

    def test_failed_install_is_not_marked_complete(self):
        with patch.object(launcher.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['pip'])):
            with self.assertRaises(subprocess.CalledProcessError):
                launcher.ensure_environment()
        self.assertFalse((self.env / '.mopac-studio-requirements.sha256').exists())

    def test_setup_only_never_starts_server(self):
        with patch.object(launcher, 'ensure_environment', return_value=launcher.environment_python()), \
             patch.object(launcher.subprocess, 'Popen') as spawn, \
             patch.object(launcher.subprocess, 'call') as call:
            self.assertEqual(launcher.main(['--setup-only']), 0)
        spawn.assert_not_called()
        call.assert_not_called()

    def test_install_failure_returns_failure_and_does_not_start_app(self):
        with patch.object(launcher, 'ensure_environment', side_effect=RuntimeError('install failed')), \
             patch.object(launcher.subprocess, 'Popen') as spawn:
            self.assertEqual(launcher.main(['--background']), 1)
        spawn.assert_not_called()

    def test_editor_only_explicitly_skips_engine_download(self):
        with patch.object(launcher, 'ensure_environment', return_value=launcher.environment_python()):
            self.assertEqual(launcher.main(['--setup-only', '--no-engine']), 0)
        self.engine.assert_not_called()

    def test_engine_install_failure_does_not_start_app(self):
        self.engine.side_effect = RuntimeError('engine download failed')
        with patch.object(launcher, 'ensure_environment', return_value=launcher.environment_python()), \
             patch.object(launcher.subprocess, 'Popen') as spawn:
            self.assertEqual(launcher.main(['--background']), 1)
        spawn.assert_not_called()

    def test_background_uses_private_environment_and_hides_windows_console(self):
        interpreter = launcher.environment_python()
        with patch.object(launcher, 'ensure_environment', return_value=interpreter), \
             patch.object(launcher.subprocess, 'Popen') as spawn:
            self.assertEqual(launcher.main(['--background']), 0)
        command = spawn.call_args.args[0]
        self.assertEqual(Path(command[0]).parent, interpreter.parent)
        self.assertEqual(command[1], str(self.root / 'background_server.py'))
        if os.name == 'nt':
            self.assertEqual(spawn.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
        else:
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])


class MopacDiscoveryTests(unittest.TestCase):
    def test_explicit_path_overrides_other_installations(self):
        configured = str(Path(tempfile.gettempdir()) / 'engine with spaces' / 'MOPAC2016.exe')
        with patch.dict(os.environ, {'MOPAC_EXE': '"' + configured + '"'}, clear=True), \
             patch.object(mopac_runner.shutil, 'which') as which:
            self.assertEqual(mopac_runner.find_mopac(), os.path.abspath(configured))
        which.assert_not_called()

    def test_existing_sibling_portable_install_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / 'studio'
            project.mkdir()
            engine = Path(folder) / 'mopac2016' / 'MOPAC2016.exe'
            engine.parent.mkdir()
            engine.touch()
            with patch.dict(os.environ, {}, clear=True), patch.object(mopac_runner, 'HERE', str(project)):
                self.assertEqual(Path(mopac_runner.find_mopac()), engine)

    def test_system_path_used_when_no_config_or_portable_engine(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(mopac_runner.os.path, 'isfile', return_value=False), \
             patch.object(mopac_runner.shutil, 'which', side_effect=[None, '/opt/mopac/mopac.exe']):
            self.assertEqual(mopac_runner.find_mopac(), '/opt/mopac/mopac.exe')

    def test_managed_engine_precedes_legacy_portable_engine(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(mopac_runner, 'managed_executable', return_value=Path('/managed/bin/mopac')), \
             patch.object(mopac_runner.os.path, 'isfile', return_value=True):
            self.assertEqual(mopac_runner.find_mopac(), str(Path('/managed/bin/mopac')))


if __name__ == '__main__':
    unittest.main()
