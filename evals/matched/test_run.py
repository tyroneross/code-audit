import importlib.util,json,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('matched_run',Path(__file__).with_name('run.py'));runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
class Receipts(unittest.TestCase):
    def test_rejects_tools_even_with_valid_final_answer(self):
        rows=[{'type':'item.completed','item':{'type':'command_execution'}},{'type':'item.completed','item':{'type':'agent_message','text':'{}'}},{'type':'turn.completed'}]
        with self.assertRaises(ValueError):runner.extract('codex','\n'.join(map(json.dumps,rows)))
    def test_rejects_failure_and_missing_turn(self):
        for rows in [[{'type':'turn.failed'}],[{'type':'item.completed','item':{'type':'agent_message','text':'{}'}}]]:
            with self.assertRaises(ValueError):runner.extract('codex','\n'.join(map(json.dumps,rows)))
    def test_claude_error_is_not_success(self):
        with self.assertRaises(ValueError):runner.extract('claude',json.dumps({'is_error':True,'result':'{}'}))
    def test_clean_host_receipts_and_fences(self):
        text,meta=runner.extract('claude',json.dumps({'is_error':False,'num_turns':1,'result':'```json\n{"cases":[]}\n```','modelUsage':{'example':{}},'total_cost_usd':.1}))
        self.assertEqual(runner.json_object(text),{'cases':[]});self.assertEqual(meta['served_models'],['example'])

class RepairIsolation(unittest.TestCase):
    def test_protected_files_are_checked_independently(self):
        import tempfile,shutil
        spec=importlib.util.spec_from_file_location('repair_run',Path(__file__).with_name('repair.py'));repair=importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'candidate';shutil.copytree(repair.BASELINE,target)
            self.assertEqual(repair.protected_changes(target),[])
            (target/'case/simulator.py').write_text('# tampered')
            self.assertEqual(repair.protected_changes(target),['case/simulator.py'])
            (target/'extra.py').write_text('# unauthorized added source')
            self.assertEqual(repair.protected_changes(target),['case/simulator.py','extra.py'])

class FailureReceipts(unittest.TestCase):
    def test_bad_fences_and_event_shapes_fail_as_value_errors(self):
        self.assertEqual(runner.json_object('```{"cases":[]}```'),{'cases':[]})
        for value in ['[]', '{"type":"item.completed","item":null}']:
            with self.assertRaises(ValueError):runner.extract('codex',value)

    def test_invalid_model_output_still_records_trial(self):
        from unittest.mock import patch
        import tempfile,subprocess
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(runner.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'[]','')):
                meta=runner.run_trial('claude','none',1,Path(folder))
            self.assertEqual(meta['status'],'unavailable')
            self.assertTrue((Path(folder)/'claude-none-1/meta.json').exists())

if __name__=='__main__':unittest.main()
