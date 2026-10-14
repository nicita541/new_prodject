"""Runner ownership and startup failures; native smoke does not send any model request."""
import os
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import patch

from app.config import TEMP
from app.json_store import atomic_json,read_json
from app.antigravity_runner import ManagedRunner,configure_default


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory=TEMP/('managed-antigravity-'+uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        atomic_json(self.directory/'job.json',{'status':'running','analysis_provider':'antigravity_manual'})
        configure_default(self.directory,'antigravity_manual')
    def tearDown(self):
        self.directory.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.directory)

    def test_default_is_managed_and_explicit_manual_external_settings_are_preserved(self):
        path=self.directory/'antigravity/automation.json'
        self.assertEqual(read_json(path),{'enabled':True,'managed':True})
        for settings in ({'enabled':False},{'enabled':True}):
            atomic_json(path,settings);before=path.read_bytes()
            configure_default(self.directory,'antigravity_manual')
            self.assertEqual(path.read_bytes(),before)
        other=self.directory/'local';other.mkdir()
        configure_default(other,'local')
        self.assertFalse((other/'antigravity').exists())

    def test_manual_mode_never_resolves_or_launches_cli(self):
        atomic_json(self.directory/'antigravity/automation.json',{'enabled':False,'managed':True})
        with patch('app.antigravity_runner.cli_executable',side_effect=AssertionError('manual')), \
             patch('app.antigravity_runner.subprocess.Popen',side_effect=AssertionError('manual')):
            runner=ManagedRunner(self.directory,lambda:False);runner.start();runner.close()

    def test_missing_cli_is_an_immediate_failure(self):
        with patch('app.antigravity_runner.cli_executable',side_effect=RuntimeError('CLI absent')):
            with self.assertRaisesRegex(RuntimeError,'CLI absent'):
                ManagedRunner(self.directory,lambda:False).start()

    def test_start_uses_fixed_owned_paths_and_close_signals_only_its_stop_file(self):
        runner=ManagedRunner(self.directory,lambda:False)
        class Process:
            done=False
            def poll(self):return 0 if self.done else None
            def wait(self,timeout):
                self_test.assertTrue(runner.stop_file.exists());self.done=True;return 0
        self_test=self;process=Process();commands=[]
        def start(command,**options):
            commands.append((command,options))
            atomic_json(runner.root/'runner.json',{'status':'waiting','owner':'worker'})
            return process
        with patch('app.antigravity_runner.cli_executable',return_value=Path('C:/installed/agy.exe')), \
             patch('app.antigravity_runner.subprocess.Popen',side_effect=start):
            runner.start();runner.close()
        command,options=commands[0]
        self.assertEqual(command[command.index('-JobDirectory')+1],str(self.directory.resolve()))
        self.assertEqual(command[command.index('-ManagedStopFile')+1],str(runner.stop_file))
        self.assertFalse(options.get('shell',False))
        self.assertEqual(options['env']['TEMP'],str(TEMP))
        self.assertFalse(runner.stop_file.exists())
        self.assertTrue(process.done)

    def test_startup_exit_is_reported_without_waiting_for_packet_timeout(self):
        class Exited:
            def poll(self):return 7
        with patch('app.antigravity_runner.cli_executable',return_value=Path('C:/installed/agy.exe')), \
             patch('app.antigravity_runner.subprocess.Popen',return_value=Exited()):
            with self.assertRaisesRegex(RuntimeError,'Не удалось запустить'):
                ManagedRunner(self.directory,lambda:False).start()
        self.assertEqual(read_json(self.directory/'antigravity/runner.json')['exit_code'],7)

    def test_cancel_before_start_does_not_launch(self):
        with patch('app.antigravity_runner.subprocess.Popen') as spawn:
            with self.assertRaises(InterruptedError):ManagedRunner(self.directory,lambda:True).start()
        spawn.assert_not_called()

    @unittest.skipUnless(os.name=='nt' and shutil.which('powershell.exe'),'Windows script smoke')
    def test_real_script_ready_and_cooperative_stop_without_any_model_request(self):
        runner=ManagedRunner(self.directory,lambda:False)
        try:
            runner.start()
            self.assertEqual(read_json(runner.root/'runner.json')['owner'],'worker')
            self.assertEqual(read_json(runner.root/'runner.json')['status'],'waiting')
        finally:runner.close()
        self.assertIsNotNone(runner.process.poll())
        self.assertFalse((runner.root/'packets').exists())
        self.assertFalse(runner.stop_file.exists())


if __name__=='__main__':unittest.main()
