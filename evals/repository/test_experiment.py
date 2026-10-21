import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import experiment

class RepositoryPackets(unittest.TestCase):
    def test_packet_hashes_checked_and_paired_repair_not_disclosed(self):
        manifest=json.loads((experiment.ROOT/'cases.json').read_text());case=manifest['cases'][0]
        value=experiment.packet(case,manifest,experiment.ROOT.parents[1])
        self.assertEqual(value['id'],'P01');self.assertNotIn('revision',value);self.assertNotIn('P02',json.dumps(value));self.assertGreater(sum(len(x.splitlines()) for x in value['sources'].values()),2800)
        with patch.object(experiment.subprocess,'check_output',return_value=b'changed'):
            with self.assertRaises(ValueError):experiment.packet(case,manifest,'.')

    def test_missing_or_duplicate_case_and_finding_are_not_complete(self):
        for value in [{}, {'cases':[]},{'cases':[{'case_id':'wrong'}]}]:
            with self.assertRaises(ValueError):experiment.validate_review(value,'P01')
        value={'cases':[{'case_id':'P01','coverage':'complete','findings':[]}]}
        self.assertEqual(experiment.validate_review(value,'P01'),value)

    def test_adjudication_uses_blind_labels_and_preserves_oracle_challenges(self):
        text=experiment.judge_prompt({'id':'P01'},[],{'blind-1':{'cases':[]}})
        self.assertIn('blind-1',text);self.assertNotIn('trimmed',text);self.assertIn('challenge',text)

class ComparisonAccounting(unittest.TestCase):
    def test_compound_classes_require_independent_explicit_evidence(self):
        class Scorer:
            def score(self,*args):return {'adjudications':[{'valid':True,'oracle_id':'D1','also_covers':[{'oracle_id':'D3','rationale':'Explicit second cause at source:139'}]}]}
        value=experiment.score_review(Scorer(),{},{},{},{'oracles':{'P01':[{'id':'D1'},{'id':'D3'}]}})
        self.assertEqual(value['named_class_coverage_union'],['D1','D3']);self.assertEqual(value['named_classes_missed'],[])
        with self.assertRaises(ValueError):experiment.score_review(Scorer(),{},{},{},{'oracles':{'P01':[{'id':'D1'}]}})

    def test_unadjudicated_calls_stay_visible_in_all_twelve_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for case in ['P01','P02']:
                for arm in ['none','current','trimmed']:
                    for repeat in [1,2]:
                        dest=root/f'{case}-{arm}-{repeat}';dest.mkdir();(dest/'meta.json').write_text(json.dumps({'status':'unavailable','error':'fixture coverage gap'}))
            rows=experiment.score_all(root);self.assertEqual(len(rows),12);self.assertTrue(all('score' not in row and row['unavailable_reason'] for row in rows))
            revisions=experiment.revision_scores(root);self.assertEqual(len(revisions),12);self.assertTrue(all(row['rounds_to_named_criteria'] is None for row in revisions))

class AuditRegressions(unittest.TestCase):
    def seed(self,root):
        manifest=json.loads((experiment.ROOT/'cases.json').read_text())
        for case in manifest['cases']:
            for arm in ['none','current','trimmed']:
                for repeat in [1,2]:
                    dest=root/f'{case["id"]}-{arm}-{repeat}';dest.mkdir(parents=True)
                    (dest/'meta.json').write_text(json.dumps({'status':'completed','source_revision':case['revision'],'source_files':case['files']}))
                    (dest/'answer.json').write_text(json.dumps({'cases':[{'case_id':case['id'],'coverage':'complete','findings':[]}]}))
                    (dest/'adjudication.json').write_text('{"judgments":[]}')
                    judge=root/f'adjudication-{case["id"]}-{repeat}';judge.mkdir(exist_ok=True);(judge/'challenges.json').write_text('[]')

        oracles=json.loads((experiment.ROOT/'private/oracles.json').read_text())
        for case in manifest['cases']:
            for repeat in [1,2]:
                mapping={arm:f'{case["id"]}-{arm}-{repeat}' for arm in ['none','current','trimmed']}
                dest=root/f'adjudication-{case["id"]}-{repeat}'
                answer={'reviews':{key:{'judgments':[]} for key in mapping},'oracle_challenges':[]}
                (dest/'answer.json').write_text(json.dumps(answer));(dest/'meta.json').write_text('{"status":"completed"}')
                experiment.save_judgments(root,dest,case,mapping,answer,experiment.judge_inputs(root,mapping,manifest,oracles))

    def test_partial_grid_keeps_every_row_without_stale_scores(self):
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.seed(root)
            first=experiment.score_all(root);self.assertEqual(len(first),12)
            valid=root/'P02-none-1';self.assertTrue((valid/'score.json').exists())
            (valid/'adjudication.json').write_text('{bad')
            shutil.rmtree(root/'P01-current-1');(root/'P01-none-1/meta.json').write_text('[]')
            rows=experiment.score_all(root);self.assertEqual(len(rows),12);self.assertFalse((valid/'score.json').exists())
            byid={r['trial']:r for r in rows};self.assertIn('score',byid['P02-current-1']);self.assertIn('unavailable_reason',byid['P02-none-1'])
            revisions=experiment.revision_scores(root);self.assertIsNone(next(r for r in revisions if r['trial']=='P02-none-1')['rounds_to_named_criteria'])

    def test_challenged_named_criteria_never_get_unqualified_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.seed(root)
            p=root/'adjudication-P02-1/challenges.json';p.write_text(json.dumps([{'case_id':'P02','kind':'named_class_ambiguity','oracle_ids':[],'reason':'Control premise disputed'}]))
            rows=experiment.score_all(root);row=next(r for r in rows if r['trial']=='P02-none-1');self.assertTrue(row['named_criteria_blocked']);self.assertEqual(row['oracle_challenges'][0]['status'],'open')
            revisions=experiment.revision_scores(root);self.assertIsNone(next(r for r in revisions if r['trial']=='P02-none-1')['rounds_to_named_criteria'])
            p.unlink();self.assertTrue(next(r for r in experiment.score_all(root) if r['trial']=='P02-none-1')['named_criteria_blocked'])

    def test_changed_review_cannot_reuse_old_judgment_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.seed(root);p=root/'P02-none-1/answer.json'
            data=json.loads(p.read_text());data['cases'][0]['reason']='changed review evidence';p.write_text(json.dumps(data))
            row=next(r for r in experiment.score_all(root) if r['trial']=='P02-none-1')
            self.assertNotIn('score',row);self.assertIn('binding stale',row['unavailable_reason'])

    def test_omitted_challenge_declaration_never_becomes_empty_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);dest=root/'judge';dest.mkdir()
            with self.assertRaises(ValueError):experiment.save_judgments(root,dest,{'id':'P01'},{},{'reviews':{}},{})
            self.assertFalse((dest/'challenges.json').exists())

    def test_bad_revision_metadata_keeps_all_rows_without_false_round_two(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.seed(root);dest=root/'P01-none-1/revision';dest.mkdir()
            (dest/'answer.json').write_text('{"cases":[]}');(dest/'adjudication.json').write_text('{"judgments":[]}')
            for raw in ['{bad','[]','{}','{"status":"unavailable"}']:
                (dest/'meta.json').write_text(raw);rows=experiment.revision_scores(root)
                self.assertEqual(len(rows),12);self.assertIsNone(next(r for r in rows if r['trial']=='P01-none-1')['rounds_to_named_criteria'])
            (dest/'meta.json').unlink();rows=experiment.revision_scores(root);self.assertEqual(len(rows),12);self.assertIsNone(next(r for r in rows if r['trial']=='P01-none-1')['rounds_to_named_criteria'])

    def seed_passing_revision(self,root):
        manifest=json.loads((experiment.ROOT/'cases.json').read_text());oracles=json.loads((experiment.ROOT/'private/oracles.json').read_text());case=manifest['cases'][0]
        initial=root/'P01-none-1';dest=initial/'revision';dest.mkdir();findings=[];judgments=[]
        for n,oid in enumerate(['D1','D2','D3','D4']):
            findings.append({'id':f'F{n}','cause':'fixture causal claim','locations':['source:1'],'severity':'medium','origin':'pre_existing','disposition':'open','suggested_change':'fixture correction','verification':'fixture check'})
            judgments.append({'case_id':'P01','finding_id':f'F{n}','valid':True,'harmful':False,'duplicate':False,'oracle_id':oid,'rationale':'fixture source evidence','also_covers':[]})
        (dest/'answer.json').write_text(json.dumps({'cases':[{'case_id':'P01','coverage':'complete','findings':findings}]}));(dest/'prompt.txt').write_text('fixture prompt');(dest/'feedback.json').write_text('{}');(dest/'meta.json').write_text(json.dumps({'status':'completed','prompt_sha256':experiment.sha('fixture prompt')}))
        judge=root/'revision-adjudication-P01';judge.mkdir();answer={'reviews':{'blind-1':{'judgments':judgments}},'oracle_challenges':[]}
        (judge/'answer.json').write_text(json.dumps(answer));(judge/'meta.json').write_text('{"status":"completed"}')
        mapping={'blind-1':str(dest.relative_to(root))};experiment.save_judgments(root,judge,case,mapping,answer,experiment.judge_inputs(root,mapping,manifest,oracles))
        (dest/'lineage.json').write_text(json.dumps(experiment.revision_lineage(initial,{},'fixture prompt')))
        return initial,dest,case,manifest,oracles

    def test_revised_pass_is_bound_to_its_actual_initial_review_and_feedback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.seed(root);initial,dest,case,manifest,oracles=self.seed_passing_revision(root)
            row=next(r for r in experiment.revision_scores(root) if r['trial']=='P01-none-1');self.assertEqual(row['rounds_to_named_criteria'],2)
            data=json.loads((initial/'answer.json').read_text());data['cases'][0]['reason']='new evidence';(initial/'answer.json').write_text(json.dumps(data))
            judge=root/'adjudication-P01-1';answer=json.loads((judge/'answer.json').read_text());mapping={arm:f'P01-{arm}-1' for arm in ['none','current','trimmed']}
            experiment.save_judgments(root,judge,case,mapping,answer,experiment.judge_inputs(root,mapping,manifest,oracles))
            row=next(r for r in experiment.revision_scores(root) if r['trial']=='P01-none-1');self.assertIsNone(row['rounds_to_named_criteria']);self.assertFalse((dest/'score.json').exists())
            (dest/'score.json').write_text('{"passed":true}');(initial/'adjudication.json').write_text('{bad')
            rows=experiment.revision_scores(root);self.assertEqual(len(rows),12);self.assertFalse((dest/'score.json').exists())

if __name__=='__main__':unittest.main()
