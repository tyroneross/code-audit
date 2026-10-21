"""Compiled-runtime regressions for defects exposed by full-module source review."""
import json
from pathlib import Path
import unittest
import test_retrieval as retrieval_tests
ROOT=retrieval_tests.ROOT

class RuntimeContracts(unittest.TestCase):
    def probe(self,body):
        imports=f"const s=require({json.dumps(str(ROOT/'runtime/debugger/dist/src/storage.js'))}); const r=require({json.dumps(str(ROOT/'runtime/debugger/dist/src/retrieval.js'))});\n"
        pattern="const pattern={pattern_id:'PTN_EXAMPLE',name:'Example',description:'alpha beta gamma',detection_signature:['alpha beta gamma'],solution_template:'Fixture fix',tags:[],success_rate:1};\n"
        return retrieval_tests.Retrieval.probe(self,imports+pattern+body)

    def test_store_ids_cannot_escape_incident_or_pattern_directory(self):
        row=self.probe("""
const errors=[];
for(const id of ['../../escaped','INC_/../../escaped','',null]){try{await s.storeIncident(incident(id,10),{config:memoryConfig});}catch(e){errors.push(String(e))}}
try{await s.storePattern({...pattern,pattern_id:'../../escaped-pattern'},memoryConfig)}catch(e){errors.push(String(e))}
const files=await fs.readdir(memoryPath);process.stdout.write(JSON.stringify({errors,files}));
""")
        self.assertEqual(len(row['errors']),5);self.assertEqual(row['files'],[])

    def test_reserved_dictionary_keys_survive_incremental_and_reloaded_indexes(self):
        row=self.probe("""
for(let i=0;i<2;i++){const value=incident('INC_RESERVED_'+i,10);value.symptom='constructor alpha';value.root_cause.category='constructor';value.tags=['__proto__'];value.files_changed=['constructor'];await s.storeIncident(value,{config:memoryConfig})}
const kw=await s.loadKeywordIndex(memoryConfig);const index=await s.loadIndex(memoryConfig);
process.stdout.write(JSON.stringify({ids:s.findCandidatesByKeyword(['constructor'],kw),category:index.by_category.constructor,tags:index.by_tag.__proto__}));
""")
        self.assertEqual(len(row['ids']),2);self.assertEqual(len(row['category']),2);self.assertEqual(len(row['tags']),2)

    def test_absent_validation_gates_cannot_bypass_either_path(self):
        rows=self.probe("""
for(let i=0;i<10;i++){const value=incident('INC_PROBE_'+i,10);if(i===0)delete value.quality_gates;else value.quality_gates.guardian_validated=i===1;await s.storeIncident(value,{config:memoryConfig})}
const cfg={memoryConfig,include_unvalidated:false,similarity_threshold:0,max_results:20};process.stdout.write(JSON.stringify([await checkMemory('alpha beta gamma',cfg),await checkMemoryScaled('alpha beta gamma',cfg)]));
""")
        for row in rows:self.assertEqual([x['incident_id'] for x in row['incidents']],['INC_PROBE_1'])

    def test_explicit_tag_and_agent_filters_cover_incidents_and_pattern_applicability(self):
        rows=self.probe("""
for(let i=0;i<10;i++){const value=incident('INC_PROBE_'+i,10);value.tags=[i%2?'blue':'red'];value.agent_used=i%2?'coder':'tester';await s.storeIncident(value,{config:memoryConfig})}
await s.storePattern({...pattern,tags:['red'],applicable_to:['tester']},memoryConfig);
const cfg={memoryConfig,tags_filter:['blue'],agent_filter:'coder',max_results:20};process.stdout.write(JSON.stringify([await checkMemory('alpha beta gamma',cfg),await checkMemoryScaled('alpha beta gamma',cfg)]));
""")
        for row in rows:self.assertEqual({x['incident_id'] for x in row['incidents']},{f'INC_PROBE_{i}' for i in [1,3,5,7,9]});self.assertEqual(row['patterns'],[])

    def test_scaled_pattern_precedence_and_stopword_query_at_zero_threshold(self):
        rows=self.probe("""
for(let i=0;i<10;i++)await s.storeIncident(incident('INC_PROBE_'+i,10),{config:memoryConfig});await s.storePattern(pattern,memoryConfig);
process.stdout.write(JSON.stringify([await checkMemoryScaled('alpha beta gamma',{memoryConfig,max_results:1}),await checkMemoryScaled('the and of',{memoryConfig,max_results:1,similarity_threshold:0})]));
""")
        for row in rows:self.assertEqual(row['incidents'],[]);self.assertEqual([p['pattern_id'] for p in row['patterns']],['PTN_EXAMPLE']);self.assertEqual(row['retrieval_method'],'pattern')

    def test_full_tier_returns_records_and_honors_serialized_budget(self):
        rows=self.probe("""
await s.storeIncident(incident('INC_FULL',10),{config:memoryConfig});
process.stdout.write(JSON.stringify([await r.checkMemoryTiered('alpha beta gamma',{memoryConfig,tier:'full'}),await r.checkMemoryTiered('alpha beta gamma',{memoryConfig,tier:'full',token_budget:1})]));
""")
        self.assertEqual(rows[0]['full_incidents'][0]['incident_id'],'INC_FULL');self.assertIn('root_cause',rows[0]['full_incidents'][0]);self.assertIn('coverage',rows[0])
        self.assertEqual(rows[1]['full_incidents'],[]);self.assertTrue(rows[1]['has_more_details']);self.assertLessEqual(rows[1]['tokens_used'],1)

    def test_quick_pattern_match_and_explicit_zero_limit(self):
        rows=self.probe("""
await s.storePattern(pattern,memoryConfig);process.stdout.write(JSON.stringify([await r.quickMemoryCheck('alpha beta gamma',{memoryConfig}),await r.quickMemoryCheck('alpha beta gamma',{memoryConfig,maxResults:0})]));
""")
        self.assertTrue(rows[0]['hasMatches']);self.assertEqual(rows[0]['topMatch']['id'],'PTN_EXAMPLE');self.assertEqual(rows[0]['matchCount'],1)
        self.assertFalse(rows[1]['hasMatches']);self.assertEqual(rows[1]['matchCount'],0)

    def test_partial_coverage_survives_all_wrappers(self):
        rows=self.probe("""
await write('INC_BAD.json','{bad');process.stdout.write(JSON.stringify([await r.checkMemoryTiered('alpha beta gamma',{memoryConfig,tier:'summary'}),await r.checkMemoryTiered('alpha beta gamma',{memoryConfig,tier:'compact'}),await r.checkMemoryTiered('alpha beta gamma',{memoryConfig,tier:'full'}),await r.checkMemoryProgressive('alpha beta gamma',{memoryConfig}),await r.quickMemoryCheck('alpha beta gamma',{memoryConfig})]));
""")
        for row in rows:self.assertEqual(row['coverage']['incidents']['skipped'],1)
        self.assertIn('inconclusive',rows[3]['action']);self.assertIn('Partial',rows[3]['summary']);self.assertTrue(rows[4]['inconclusive'])

    def test_progressive_keeps_rank_separate_from_zero_historical_confidence(self):
        row=self.probe("""
await s.storeIncident(incident('INC_CONF',10),{config:memoryConfig});process.stdout.write(JSON.stringify(await r.checkMemoryProgressive('alpha beta gamma',{memoryConfig})));
""")
        top=row['matches'][0];self.assertEqual(top['confidence'],0);self.assertEqual(top['confidence_kind'],'historical_diagnosis');self.assertGreater(top['retrieval_score'],0.5);self.assertIn('historical',top['one_liner'])

    def test_bad_nested_fields_are_skipped_and_legacy_omissions_still_work(self):
        rows=self.probe("""
for(let i=0;i<10;i++)await s.storeIncident(incident('INC_PROBE_'+i,10),{config:memoryConfig});
const bad=incident('INC_PROBE_0',10);bad.root_cause.description=42;await write('INC_PROBE_0.json',bad);const bad2=incident('INC_PROBE_1',10);bad2.fix.changes='wrong';await write('INC_PROBE_1.json',bad2);
await fs.mkdir(memoryPath+'/patterns',{recursive:true});await fs.writeFile(memoryPath+'/patterns/PTN_BAD.json',JSON.stringify({...pattern,pattern_id:'PTN_BAD',solution_template:42}));
const standard=await checkMemory('alpha beta gamma',{memoryConfig,max_results:20});const indexed=await checkMemoryScaled('alpha beta gamma',{memoryConfig,max_results:20});
await write('INC_LEGACY.json',{incident_id:'INC_LEGACY',timestamp:now,symptom:'alpha beta gamma'});const legacy=await checkMemory('alpha beta gamma',{memoryConfig,max_results:20});
process.stdout.write(JSON.stringify([standard,indexed,legacy]));
""")
        for row in rows[:2]:self.assertEqual(len(row['incidents']),8);self.assertEqual(row['coverage']['incidents']['skipped'],2);self.assertEqual(row['coverage']['patterns']['skipped'],1)
        self.assertIn('INC_LEGACY',[x['incident_id'] for x in rows[2]['incidents']])

    def test_actual_serialized_size_prevents_oversized_records_bypassing_budgets(self):
        row=self.probe("""
const oversized={id:'X'.repeat(12000),sym:'alpha',rc:{d:'cause',cat:'category',conf:0},fix:{a:'fix',n:0},v:'U',t:[],q:0};const compact=s.enforceTokenBudget([oversized],[],500);
const value=incident('INC_HUGE',10);value.root_cause.category='Y'.repeat(12000);await s.storeIncident(value,{config:memoryConfig});
const tiers=[];for(const tier of ['summary','compact','full'])tiers.push(await r.checkMemoryTiered('alpha beta gamma',{memoryConfig,tier,token_budget:500}));process.stdout.write(JSON.stringify({compact,tiers}));
""")
        self.assertEqual(row['compact']['limitedIncidents'],[])
        for tier in row['tiers']:self.assertTrue(tier['truncated']['incidents']);self.assertLessEqual(tier['tokens_used'],500)

    def test_archival_prunes_keyword_postings_before_candidate_limit(self):
        row=self.probe("""
for(let i=0;i<25;i++)await s.storeIncident(incident('INC_ARCHIVE_'+i,i<22?200:10),{config:memoryConfig});
const archived=await s.archiveOldIncidents({maxActive:100,maxAgeDays:90},memoryConfig);const index=await s.loadKeywordIndex(memoryConfig);const found=await checkMemoryScaled('alpha beta gamma',{memoryConfig});process.stdout.write(JSON.stringify({archived,index,found}));
""")
        self.assertEqual(len(row['archived']['archived']),22);self.assertEqual(row['index']['total_incidents'],3);self.assertEqual(len(row['found']['incidents']),3)

    def test_one_bad_jsonl_record_does_not_erase_valid_log_matches(self):
        row=self.probe("""
for(let i=0;i<3;i++)await s.storeIncident(incident('INC_LOG_'+i,10),{config:memoryConfig});await fs.appendFile(memoryPath+'/incidents.jsonl','{}\\n{secret fixture\\n'+JSON.stringify({incident_id:'INC_BAD',symptom:'alpha',category:'test',tags:42})+'\\n');const coverage=s.emptyCorpusCoverage();const matches=await s.searchIncidentLog('alpha',memoryConfig,coverage);process.stdout.write(JSON.stringify({matches,coverage}));
""")
        self.assertEqual(len(row['matches']),3);self.assertEqual(row['coverage']['checked'],6);self.assertEqual(row['coverage']['loaded'],3);self.assertEqual(row['coverage']['skipped'],3);self.assertNotIn('secret fixture',json.dumps(row))

    def test_throwing_coercion_in_malformed_verification_is_skipped(self):
        rows=self.probe("""
for(let i=0;i<10;i++)await s.storeIncident(incident('INC_PROBE_'+i,10),{config:memoryConfig});const bad=incident('INC_PROBE_0',10);bad.verification.status={toString:null};await write('INC_PROBE_0.json',bad);
process.stdout.write(JSON.stringify([await checkMemory('alpha beta gamma',{memoryConfig,max_results:20}),await checkMemoryScaled('alpha beta gamma',{memoryConfig,max_results:20})]));
""")
        for row in rows:self.assertEqual(len(row['incidents']),9);self.assertEqual(row['coverage']['incidents']['skipped'],1)

    def test_filtered_candidates_do_not_consume_the_eligible_candidate_allowance(self):
        rows=self.probe("""
for(let i=0;i<21;i++){const value=incident('INC_FILTER_'+i,10);value.tags=[i===20?'blue':'red'];value.agent_used=i===20?'coder':'tester';value.quality_gates.guardian_validated=i===20;await s.storeIncident(value,{config:memoryConfig})}
const results=[];for(const flags of [{tags_filter:['blue']},{agent_filter:'coder'},{include_unvalidated:false}])results.push(await checkMemoryScaled('alpha beta gamma',{memoryConfig,...flags}));process.stdout.write(JSON.stringify(results));
""")
        for row in rows:self.assertEqual([x['incident_id'] for x in row['incidents']],['INC_FILTER_20']);self.assertEqual(row['coverage']['incidents']['checked'],21)

    def test_replacing_an_incident_removes_old_index_contributions_without_overcount(self):
        row=self.probe("""
const first=incident('INC_REPLACE',10);first.symptom='obsolete telescope';first.root_cause.description='obsolete telescope';first.root_cause.category='old';first.tags=['old-tag'];await s.storeIncident(first,{config:memoryConfig});
const second=incident('INC_REPLACE',10);second.symptom='newer orchid';second.root_cause.description='newer orchid';second.root_cause.category='new';second.tags=['new-tag'];await s.storeIncident(second,{config:memoryConfig});const index=await s.loadIndex(memoryConfig);const keywords=await s.loadKeywordIndex(memoryConfig);process.stdout.write(JSON.stringify({index,keywords}));
""")
        self.assertEqual(row['index']['stats']['total_incidents'],1);self.assertEqual(row['keywords']['total_incidents'],1);self.assertNotIn('old',row['index']['by_category']);self.assertNotIn('old-tag',row['index']['by_tag']);self.assertNotIn('obsolete',row['keywords']['keywords'])

if __name__=='__main__':unittest.main()
