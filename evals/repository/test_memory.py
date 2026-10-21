import json
from pathlib import Path
import tempfile
import unittest
import memory

class HistoricalMemory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.result=memory.run()

    def test_all_observations_and_paths_are_retained(self):
        rows=self.result['rows'];self.assertEqual(len(rows),54)
        self.assertEqual({r['path'] for r in rows},{'standard','indexed'});self.assertEqual({r['scenario'] for r in rows},{'relevant-only','mixed','partial'})
        self.assertTrue(all(r['coverage'] is not None for r in rows))

    def test_partial_fixture_cannot_be_reported_as_full_empty_corpus(self):
        rows=[r for r in self.result['rows'] if r['scenario']=='partial' and r['path']=='standard']
        self.assertTrue(all(r['coverage']['incidents']['skipped']==2 for r in rows))
        self.assertTrue(all(r['coverage']['incidents']['checked']==14 for r in rows))

    def test_provenance_and_unverified_distractor_not_relabelled(self):
        self.assertEqual(len(self.result['source_provenance']),3)
        distractors=[x for r in self.result['rows'] for x in r['incidents'] if x['id']=='INC_MISLEADING']
        self.assertTrue(distractors);self.assertTrue(all(x['verification']=='unverified' for x in distractors))
        self.assertTrue(all(len(row['sha256'])==64 for row in self.result['source_provenance']))

if __name__=='__main__':unittest.main()
