import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import trial

class TrialBoundary(unittest.TestCase):
    def test_missing_file_auth_never_starts_any_process(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(trial,'run_bounded') as execute:
                meta=trial.call('{}',Path(folder)/'row',auth_file=Path(folder)/'absent')
            execute.assert_not_called();self.assertEqual(meta['status'],'unavailable');self.assertTrue((Path(folder)/'row/meta.json').exists())

    def test_existing_file_auth_is_only_symlinked_and_raw_tool_events_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);auth=root/'existing';auth.write_text('opaque-existing-fixture')
            def execute(command,**kwargs):
                self.assertIn('cli_auth_credentials_store="file"',command);home=Path(kwargs['env']['CODEX_HOME']);self.assertTrue((home/'auth.json').is_symlink());self.assertEqual((home/'auth.json').resolve(),auth.resolve())
                policy=Path(command[2]).read_text();self.assertIn('/usr/bin/security',policy);self.assertIn('Library/Keychains',policy)
                rows=[{'type':'item.completed','item':{'type':'command_execution'}},{'type':'turn.completed'}]
                return subprocess.CompletedProcess(command,0,'\n'.join(map(json.dumps,rows)).encode(),b'')
            with patch.object(trial,'run_bounded',side_effect=execute),patch('shutil.which',return_value='/usr/bin/sandbox-exec'):
                meta=trial.call('review',root/'row',auth_file=auth)
            self.assertEqual(meta['status'],'invalid_response');self.assertIn('prohibited tool',meta['error']);self.assertEqual(auth.read_text(),'opaque-existing-fixture')
            self.assertNotIn('opaque-existing-fixture',(root/'row/meta.json').read_text())

    def test_timeout_retains_exact_bytes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);auth=root/'auth';auth.write_text('fixture')
            with patch.object(trial,'run_bounded',side_effect=subprocess.TimeoutExpired([],1,output=b'\xffpartial',stderr=b'error')),patch('shutil.which',return_value='/usr/bin/sandbox-exec'):
                meta=trial.call('{}',root/'row',auth_file=auth)
            self.assertEqual(meta['status'],'timeout');self.assertEqual((root/'row/host-output.jsonl').read_bytes(),b'\xffpartial')
            with self.assertRaises(FileExistsError):trial.call('{}',root/'row',auth_file=auth)

if __name__=='__main__':unittest.main()
