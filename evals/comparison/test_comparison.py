"""Offline checks for the comparison harness; no model calls."""
import json, unittest
from common import ARMS, assert_launch, guidance, MODEL
import memory_arms

class Launch(unittest.TestCase):
    def test_refuses_unpinned_or_wrong_model_and_effort(self):
        ok=['codex','exec','-m',MODEL,'-c','model_reasoning_effort="medium"','-']
        self.assertEqual(assert_launch(ok)['asserted_model'],MODEL)
        for bad in [['codex','exec','-c','model_reasoning_effort="medium"'],['codex','exec','-m','gpt-6.1-terra','-c','model_reasoning_effort="medium"'],['codex','exec','-m',MODEL],['claude','-p','-m',MODEL,'-c','model_reasoning_effort="medium"']]:
            with self.assertRaises(RuntimeError):assert_launch(bad)

    def test_every_arm_has_a_frozen_bundle_and_control_is_empty(self):
        self.assertEqual(ARMS[-1],'none');self.assertEqual(guidance('none'),'')
        for arm in ARMS[:-1]:self.assertIn('Frozen '+arm+' guidance bundle',guidance(arm))

class Memory(unittest.TestCase):
    def test_metrics_and_baseline(self):
        corpus={'INC_A':{'incident_id':'INC_A','symptom':'checkout receipt duplicated after timeout','root_cause':{'description':'retry without idempotency key'}},
                'INC_B':{'incident_id':'INC_B','symptom':'avatar image blurry','root_cause':{'description':'wrong scale'}}}
        self.assertEqual(memory_arms.keyword_baseline(corpus,'duplicated receipt on checkout'),['INC_A'])
        self.assertEqual(memory_arms.keyword_baseline(corpus,'orchid telescope'),[])
        queries=[{'id':'T01-exact','text':'x','relevant':['INC_A']},{'id':'T01-partial','text':'x','relevant':['INC_A']},{'id':'T01-cause','text':'x','relevant':['INC_A']},{'id':'N01','text':'y','relevant':[]}]
        rows=[{'query_id':'T01-exact','ids':['INC_B','INC_A']},{'query_id':'T01-partial','ids':[]},{'query_id':'T01-cause','ids':['INC_A']},{'query_id':'N01','ids':['INC_B']}]
        m=memory_arms.metrics(rows,queries)
        self.assertEqual((m['recall_at_5'],m['mrr'],m['negative_false_return_rate']),(round(2/3,3),round((0.5+1)/3,3),1.0))

if __name__=='__main__':unittest.main()
