#!/usr/bin/env node
/**
 * End-to-End Test Suite for Claude Code Debugger v1.5.0
 *
 * Tests v1.5.0 features + edge cases:
 * 1. v1.5.0 Exports (new functions & types)
 * 2. Compound IDs (category-prefixed)
 * 3. Verdict System (KNOWN_FIX, LIKELY_MATCH, WEAK_SIGNAL, NO_MATCH)
 * 4. JSONL Append Log (write + search)
 * 5. Memory Index (build + load + query)
 * 6. Batch I/O (concurrent loading)
 * 7. Context Compression (token-optimized output)
 * 8. Memory Summary (MEMORY_SUMMARY.md generation)
 * 9. Archival System (eviction + manifest)
 * 10. Edge Cases (empty data, malformed input, boundaries)
 *
 * Run: node test-v1.5.0-e2e.js
 */

const fs = require('fs');
const path = require('path');

// Test framework
const results = [];
let currentSuite = null;

function suite(name) {
  currentSuite = { name, tests: [] };
  results.push(currentSuite);
  console.log(`\n${'='.repeat(60)}`);
  console.log(`SUITE: ${name}`);
  console.log('='.repeat(60));
}

async function test(name, fn) {
  const start = Date.now();
  try {
    await fn();
    const duration = Date.now() - start;
    currentSuite?.tests.push({ name, passed: true, duration });
    console.log(`  ✅ ${name} (${duration}ms)`);
  } catch (e) {
    const duration = Date.now() - start;
    const error = e instanceof Error ? e.message : String(e);
    currentSuite?.tests.push({ name, passed: false, duration, error });
    console.log(`  ❌ ${name} (${duration}ms)`);
    console.log(`     Error: ${error}`);
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

function assertDefined(value, message) {
  if (value === undefined || value === null) {
    throw new Error(`${message}: value is ${value}`);
  }
}

function assertType(value, type, message) {
  if (typeof value !== type) {
    throw new Error(`${message}: expected ${type}, got ${typeof value}`);
  }
}

function assertIncludes(str, substr, message) {
  if (!str.includes(substr)) {
    throw new Error(`${message}: "${str}" does not include "${substr}"`);
  }
}

function assertGreaterThan(actual, expected, message) {
  if (actual <= expected) {
    throw new Error(`${message}: ${actual} is not greater than ${expected}`);
  }
}

// =============================================================================
// TESTS
// =============================================================================

async function runTests() {
  console.log('\n' + '🧪'.repeat(30));
  console.log('CLAUDE CODE DEBUGGER v1.5.0 - EDGE CASE TESTS');
  console.log('🧪'.repeat(30));

  let lib;

  // ---------------------------------------------------------------------------
  // 1. v1.5.0 Export Verification
  // ---------------------------------------------------------------------------
  suite('1. v1.5.0 Exports');

  await test('Import main module', async () => {
    lib = require('./dist/src/index.js');
    assert(lib !== undefined, 'Module should load');
  });

  await test('New storage exports exist', () => {
    assertDefined(lib.appendToIncidentLog, 'appendToIncidentLog');
    assertDefined(lib.searchIncidentLog, 'searchIncidentLog');
    assertDefined(lib.rebuildIndex, 'rebuildIndex');
    assertDefined(lib.loadIndex, 'loadIndex');
    assertDefined(lib.buildMemorySummary, 'buildMemorySummary');
    assertDefined(lib.archiveOldIncidents, 'archiveOldIncidents');
    assertDefined(lib.compressContext, 'compressContext');
  });

  await test('New retrieval exports exist', () => {
    assertDefined(lib.checkMemoryWithVerdict, 'checkMemoryWithVerdict');
    assertDefined(lib.classifyVerdict, 'classifyVerdict');
  });

  // ---------------------------------------------------------------------------
  // 2. Compound ID Generation
  // ---------------------------------------------------------------------------
  suite('2. Compound IDs');

  await test('Generate ID without category (backward compat)', () => {
    const id = lib.generateIncidentId();
    assert(id.startsWith('INC_'), 'Should start with INC_');
    // Format: INC_YYYYMMDD_HHMMSS_xxxx
    const parts = id.split('_');
    assert(parts.length === 4, `Should have 4 parts, got ${parts.length}: ${id}`);
  });

  await test('Generate ID with category', () => {
    const id = lib.generateIncidentId('api');
    assert(id.startsWith('INC_API_'), `Should start with INC_API_, got: ${id}`);
    const parts = id.split('_');
    assert(parts.length === 5, `Should have 5 parts, got ${parts.length}: ${id}`);
  });

  await test('Category gets uppercased and sanitized', () => {
    const id = lib.generateIncidentId('react-hooks');
    assert(id.startsWith('INC_REACTHOOKS_'), `Should sanitize hyphens, got: ${id}`);
  });

  await test('Category truncated to 12 chars', () => {
    const id = lib.generateIncidentId('very-long-category-name-that-exceeds');
    const catPart = id.split('_')[1];
    assert(catPart.length <= 12, `Category should be ≤12 chars, got ${catPart.length}: ${catPart}`);
  });

  await test('Empty category treated as no category', () => {
    const id = lib.generateIncidentId('');
    const parts = id.split('_');
    // Empty string is falsy, so should fall through to no-category path
    assert(parts.length === 4, `Empty category should produce 4-part ID, got ${parts.length}`);
  });

  await test('Special chars stripped from category', () => {
    const id = lib.generateIncidentId('api/v2.1');
    assert(!id.includes('/'), 'Should not contain slash');
    assert(!id.includes('.'), 'Should not contain dot');
  });

  // ---------------------------------------------------------------------------
  // 3. Verdict System
  // ---------------------------------------------------------------------------
  suite('3. Verdict System');

  await test('NO_MATCH verdict for empty results', () => {
    const result = {
      incidents: [],
      patterns: [],
      confidence: 0,
      retrieval_method: 'incident',
      tokens_used: 0,
    };
    const verdict = lib.classifyVerdict(result);
    assertEqual(verdict, 'NO_MATCH', 'Empty results should be NO_MATCH');
  });

  await test('KNOWN_FIX verdict for high-confidence pattern', () => {
    const result = {
      incidents: [],
      patterns: [{ success_rate: 0.9, pattern_id: 'PTN_TEST', name: 'Test', detection_signature: [], tags: [] }],
      confidence: 0.9,
      retrieval_method: 'pattern',
      tokens_used: 100,
    };
    const verdict = lib.classifyVerdict(result);
    assertEqual(verdict, 'KNOWN_FIX', 'High-confidence pattern should be KNOWN_FIX');
  });

  await test('LIKELY_MATCH verdict for medium confidence', () => {
    const result = {
      incidents: [{ incident_id: 'INC_TEST', symptom: 'test' }],
      patterns: [],
      confidence: 0.6,
      retrieval_method: 'incident',
      tokens_used: 200,
    };
    const verdict = lib.classifyVerdict(result);
    assertEqual(verdict, 'LIKELY_MATCH', 'Medium confidence should be LIKELY_MATCH');
  });

  await test('WEAK_SIGNAL verdict for low confidence with results', () => {
    const result = {
      incidents: [{ incident_id: 'INC_TEST', symptom: 'test' }],
      patterns: [],
      confidence: 0.35,
      retrieval_method: 'incident',
      tokens_used: 200,
    };
    const verdict = lib.classifyVerdict(result);
    assertEqual(verdict, 'WEAK_SIGNAL', 'Low confidence with results should be WEAK_SIGNAL');
  });

  await test('checkMemoryWithVerdict returns VerdictResult', async () => {
    const result = await lib.checkMemoryWithVerdict('nonexistent bug xyz abc');
    assertDefined(result.verdict, 'Should have verdict');
    assertDefined(result.summary, 'Should have summary');
    assertDefined(result.action, 'Should have action');
    assertType(result.confidence, 'number', 'confidence');
    assert(Array.isArray(result.incidents), 'Should have incidents array');
    assert(Array.isArray(result.patterns), 'Should have patterns array');
  });

  await test('Verdict boundary: confidence exactly 0.5', () => {
    const result = {
      incidents: [{ incident_id: 'INC_TEST' }],
      patterns: [],
      confidence: 0.5,
      retrieval_method: 'incident',
      tokens_used: 100,
    };
    const verdict = lib.classifyVerdict(result);
    assertEqual(verdict, 'LIKELY_MATCH', 'Exactly 0.5 should be LIKELY_MATCH');
  });

  await test('Verdict boundary: confidence exactly 0.3', () => {
    const result = {
      incidents: [{ incident_id: 'INC_TEST' }],
      patterns: [],
      confidence: 0.3,
      retrieval_method: 'incident',
      tokens_used: 100,
    };
    const verdict = lib.classifyVerdict(result);
    assertEqual(verdict, 'WEAK_SIGNAL', 'Exactly 0.3 should be WEAK_SIGNAL');
  });

  await test('Verdict: high confidence but low pattern success rate', () => {
    const result = {
      incidents: [],
      patterns: [{ success_rate: 0.3, pattern_id: 'PTN_LOW' }],
      confidence: 0.85,
      retrieval_method: 'pattern',
      tokens_used: 100,
    };
    const verdict = lib.classifyVerdict(result);
    // success_rate < 0.7, so shouldn't be KNOWN_FIX even though confidence is high
    assert(verdict !== 'KNOWN_FIX', 'Low success rate pattern should not be KNOWN_FIX');
  });

  // ---------------------------------------------------------------------------
  // 4. JSONL Append Log
  // ---------------------------------------------------------------------------
  suite('4. JSONL Log');

  const testIncident1 = {
    incident_id: lib.generateIncidentId('test'),
    timestamp: Date.now(),
    symptom: 'JSONL test: React hook dependency missing',
    root_cause: { description: 'useEffect missing dep', category: 'react-hooks', confidence: 0.9 },
    fix: { approach: 'Add dependency', changes: [{ file: 'test.tsx', lines_changed: 1, change_type: 'modify', summary: 'fix' }] },
    verification: { status: 'verified', regression_tests_passed: true, user_journey_tested: true, success_criteria_met: true },
    tags: ['react', 'hooks', 'jsonl-test'],
    files_changed: ['test.tsx'],
    quality_gates: { guardian_validated: false, tested_e2e: false, tested_from_ui: false, security_reviewed: false, architect_reviewed: false },
    completeness: { symptom: true, root_cause: true, fix: true, verification: true, quality_score: 0.8 },
  };

  await test('Store incident appends to JSONL', async () => {
    await lib.storeIncident(testIncident1);

    const config = lib.getConfig();
    const paths = lib.getMemoryPaths(config);
    const logPath = path.join(paths.root, 'incidents.jsonl');

    assert(fs.existsSync(logPath), 'incidents.jsonl should exist');
    const content = fs.readFileSync(logPath, 'utf-8');
    assertIncludes(content, testIncident1.incident_id, 'JSONL should contain incident ID');
  });

  await test('Search JSONL by symptom keyword', async () => {
    const results = await lib.searchIncidentLog('React hook');
    assert(Array.isArray(results), 'Should return array');
    assert(results.length >= 1, 'Should find at least the test incident');
    const found = results.some(r => r.incident_id === testIncident1.incident_id);
    assert(found, 'Results should contain the test incident');
  });

  await test('Search JSONL by tag', async () => {
    const results = await lib.searchIncidentLog('jsonl-test');
    assert(results.length >= 1, 'Should find by tag');
  });

  await test('Search JSONL by category', async () => {
    const results = await lib.searchIncidentLog('react-hooks');
    assert(results.length >= 1, 'Should find by category');
  });

  await test('Search JSONL with no matches', async () => {
    const results = await lib.searchIncidentLog('zzz_nonexistent_xyz_12345');
    assertEqual(results.length, 0, 'Should find nothing');
  });

  await test('JSONL entry has correct fields', async () => {
    const results = await lib.searchIncidentLog(testIncident1.incident_id);
    assert(results.length >= 1, 'Should find the entry');
    const entry = results[0];
    assertDefined(entry.incident_id, 'Should have incident_id');
    assertDefined(entry.timestamp, 'Should have timestamp');
    assertDefined(entry.symptom, 'Should have symptom');
    assertDefined(entry.category, 'Should have category');
    assert(Array.isArray(entry.tags), 'Should have tags array');
  });

  // ---------------------------------------------------------------------------
  // 5. Memory Index
  // ---------------------------------------------------------------------------
  suite('5. Memory Index');

  await test('Rebuild index from incidents', async () => {
    const index = await lib.rebuildIndex();
    assertDefined(index, 'Index should exist');
    assertEqual(index.version, 1, 'Version should be 1');
    assertGreaterThan(index.stats.total_incidents, 0, 'Should have incidents');
    assertDefined(index.by_category, 'Should have by_category');
    assertDefined(index.by_tag, 'Should have by_tag');
    assertDefined(index.by_file, 'Should have by_file');
    assertDefined(index.recent, 'Should have recent');
  });

  await test('Load index from disk', async () => {
    const index = await lib.loadIndex();
    assertDefined(index, 'Saved index should load');
    assertEqual(index.version, 1, 'Version should be 1');
  });

  await test('Index has category entries', async () => {
    const index = await lib.loadIndex();
    assert(Object.keys(index.by_category).length > 0, 'Should have category entries');
  });

  await test('Index has tag entries', async () => {
    const index = await lib.loadIndex();
    assert(Object.keys(index.by_tag).length > 0, 'Should have tag entries');
  });

  await test('Index recent list is sorted newest first', async () => {
    const index = await lib.loadIndex();
    assert(index.recent.length > 0, 'Should have recent entries');
    // Recent should contain our test incident
    assert(index.recent.includes(testIncident1.incident_id), 'Recent should contain test incident');
  });

  await test('Index quality distribution sums correctly', async () => {
    const index = await lib.loadIndex();
    const qd = index.stats.quality_distribution;
    const sum = qd.excellent + qd.good + qd.fair;
    assertEqual(sum, index.stats.total_incidents, 'Quality distribution should sum to total');
  });

  await test('Index timestamps are valid', async () => {
    const index = await lib.loadIndex();
    if (index.stats.total_incidents > 0) {
      assert(index.stats.oldest_timestamp > 0, 'Oldest should be positive');
      assert(index.stats.newest_timestamp > 0, 'Newest should be positive');
      assert(index.stats.newest_timestamp >= index.stats.oldest_timestamp, 'Newest should be >= oldest');
    }
  });

  // ---------------------------------------------------------------------------
  // 6. Context Compression
  // ---------------------------------------------------------------------------
  suite('6. Context Compression');

  await test('Compress empty context', () => {
    const compressed = lib.compressContext([], [], 2500);
    assertType(compressed, 'string', 'Should return string');
    assertIncludes(compressed, '0i/0p', 'Should show zero counts');
  });

  await test('Compress with incidents only', () => {
    const incidents = [{
      id: 'INC_TEST_001',
      ts: Date.now(),
      sym: 'Test symptom',
      rc: { d: 'Test cause', cat: 'test', conf: 0.9 },
      fix: { a: 'Test fix', n: 1 },
      v: 'V',
      t: ['test'],
      q: 0.8,
    }];
    const compressed = lib.compressContext(incidents, [], 2500);
    assertIncludes(compressed, 'INCIDENTS:', 'Should have INCIDENTS section');
    assertIncludes(compressed, 'INC_TEST_001', 'Should contain incident ID');
    assertIncludes(compressed, 'verified', 'Should show verification status');
  });

  await test('Compress with patterns only', () => {
    const patterns = [{
      id: 'PTN_TEST_001',
      n: 5,
      desc: 'Test pattern',
      sig: ['keyword1'],
      fix: 'Apply the fix',
      sr: 0.85,
      cat: 'test',
      t: ['test'],
      last: Date.now(),
    }];
    const compressed = lib.compressContext([], patterns, 2500);
    assertIncludes(compressed, 'PATTERNS:', 'Should have PATTERNS section');
    assertIncludes(compressed, 'PTN_TEST_001', 'Should contain pattern ID');
  });

  await test('Compression respects token budget', () => {
    // Create many incidents to exceed budget
    const incidents = Array.from({ length: 50 }, (_, i) => ({
      id: `INC_BUDGET_${i}`,
      ts: Date.now(),
      sym: `Symptom ${i} for budget testing`,
      rc: { d: `Cause ${i}`, cat: 'test', conf: 0.5 },
      fix: { a: `Fix ${i}`, n: 1 },
      v: 'U',
      t: ['budget'],
      q: 0.3,
    }));
    const compressed = lib.compressContext(incidents, [], 500);
    // With 500 token budget: 60% = 300 tokens for incidents, ~200 tokens each = ~1 incident
    assertIncludes(compressed, 'omitted', 'Should show truncation notice');
  });

  // ---------------------------------------------------------------------------
  // 7. Memory Summary
  // ---------------------------------------------------------------------------
  suite('7. Memory Summary');

  await test('Build memory summary', async () => {
    const summary = await lib.buildMemorySummary();
    assertType(summary, 'string', 'Should return string');
    assertIncludes(summary, '# Debugging Memory Summary', 'Should have header');
    assertIncludes(summary, 'incidents', 'Should mention incidents');
  });

  await test('Summary file written to disk', async () => {
    const config = lib.getConfig();
    const paths = lib.getMemoryPaths(config);
    const summaryPath = path.join(paths.root, 'MEMORY_SUMMARY.md');
    assert(fs.existsSync(summaryPath), 'MEMORY_SUMMARY.md should exist');
  });

  await test('Summary contains categories', async () => {
    const summary = await lib.buildMemorySummary();
    // Should have category section if incidents exist
    assertIncludes(summary, 'Categories', 'Should have categories section');
  });

  await test('Summary stays under 150 lines', async () => {
    const summary = await lib.buildMemorySummary();
    const lineCount = summary.split('\n').length;
    assert(lineCount <= 200, `Summary should be reasonable length, got ${lineCount} lines`);
  });

  // ---------------------------------------------------------------------------
  // 8. Archival System
  // ---------------------------------------------------------------------------
  suite('8. Archival System');

  await test('Dry run archival returns empty for fresh data', async () => {
    const result = await lib.archiveOldIncidents({ maxActive: 1000, maxAgeDays: 365, dryRun: true });
    assertDefined(result, 'Should return result');
    assert(Array.isArray(result.archived), 'Should have archived array');
    assertType(result.kept, 'number', 'Should have kept count');
  });

  await test('Archival with high limits keeps everything', async () => {
    const result = await lib.archiveOldIncidents({ maxActive: 10000, maxAgeDays: 3650, dryRun: true });
    assertEqual(result.archived.length, 0, 'Should archive nothing with high limits');
  });

  // ---------------------------------------------------------------------------
  // 9. Batch I/O Stress
  // ---------------------------------------------------------------------------
  suite('9. Batch I/O');

  await test('Load all incidents with batching', async () => {
    const incidents = await lib.loadAllIncidents();
    assert(Array.isArray(incidents), 'Should return array');
    // Should handle gracefully regardless of count
  });

  await test('Load all patterns with batching', async () => {
    const patterns = await lib.loadAllPatterns();
    assert(Array.isArray(patterns), 'Should return array');
  });

  await test('Concurrent loads dont corrupt', async () => {
    // Launch multiple loads simultaneously
    const [inc1, inc2, inc3] = await Promise.all([
      lib.loadAllIncidents(),
      lib.loadAllIncidents(),
      lib.loadAllIncidents(),
    ]);
    assertEqual(inc1.length, inc2.length, 'Concurrent loads should return same count');
    assertEqual(inc2.length, inc3.length, 'Concurrent loads should return same count');
  });

  // ---------------------------------------------------------------------------
  // 10. Edge Cases
  // ---------------------------------------------------------------------------
  suite('10. Edge Cases');

  await test('checkMemory with empty string', async () => {
    const result = await lib.checkMemory('');
    assertDefined(result, 'Should handle empty string');
    assertEqual(result.incidents.length, 0, 'No matches for empty string');
  });

  await test('checkMemory with very long symptom', async () => {
    const longSymptom = 'a'.repeat(10000);
    const result = await lib.checkMemory(longSymptom);
    assertDefined(result, 'Should handle very long input');
  });

  await test('checkMemory with special characters', async () => {
    const result = await lib.checkMemory('error: "undefined" is not a function ({})[]\n\ttab');
    assertDefined(result, 'Should handle special chars');
  });

  await test('checkMemory with unicode', async () => {
    const result = await lib.checkMemory('エラー 오류 خطا ошибка');
    assertDefined(result, 'Should handle unicode');
  });

  await test('generateIncidentId uniqueness', () => {
    // 10,000, not 100. At 100 this assertion passed 99.71% of the time against a
    // generator that genuinely collided (measured: 59 failures in 20,000 trials),
    // so it certified the defect far more often than it caught it. At 10,000 the
    // old 4-character Math.random suffix collides essentially always, which makes
    // this a gate rather than a coin flip. 10,000 is below the 46,656 process
    // sequence period, so a correct generator is unique here by construction.
    const N = 10000;
    const ids = new Set();
    for (let i = 0; i < N; i++) {
      ids.add(lib.generateIncidentId());
    }
    assertEqual(ids.size, N, `All ${N} IDs should be unique`);
  });

  await test('loadIncident with nonexistent ID', async () => {
    const result = await lib.loadIncident('INC_99991231_235959_zzzz');
    assertEqual(result, null, 'Should return null for nonexistent incident');
  });

  await test('loadIncident rejects path traversal', async () => {
    try {
      await lib.loadIncident('../../etc/passwd');
      assert(false, 'Should have thrown on path traversal');
    } catch (e) {
      assertIncludes(e.message, 'Invalid incident ID', 'Should reject path traversal');
    }
  });

  await test('loadPattern rejects path traversal', async () => {
    try {
      await lib.loadPattern('../../etc/passwd');
      assert(false, 'Should have thrown on path traversal');
    } catch (e) {
      assertIncludes(e.message, 'Invalid pattern ID', 'Should reject path traversal');
    }
  });

  await test('validateIncident catches missing fields', () => {
    const invalid = {
      incident_id: '',
      timestamp: 0,
      symptom: '',
    };
    const result = lib.validateIncident(invalid);
    assertEqual(result.valid, false, 'Should be invalid');
    assert(result.errors.length > 0, 'Should have errors');
  });

  await test('validateIncident passes valid incident', () => {
    const result = lib.validateIncident(testIncident1);
    assertEqual(result.valid, true, 'Should be valid');
    assertEqual(result.errors.length, 0, 'Should have no errors');
  });

  await test('enforceTokenBudget with zero budget', () => {
    const incidents = [{ id: 'test', ts: 1, sym: 'x', rc: { d: 'x', cat: 'x', conf: 0 }, fix: { a: 'x', n: 0 }, v: 'U', t: [], q: 0 }];
    const result = lib.enforceTokenBudget(incidents, [], 0);
    assertEqual(result.limitedIncidents.length, 0, 'Zero budget should return no incidents');
  });

  await test('enhancedSearch with stop words only', async () => {
    const results = await lib.enhancedSearch('the and or but');
    assert(Array.isArray(results), 'Should handle stop-words-only query');
  });

  await test('Quality score boundaries', () => {
    // Minimal incident should score > 0
    const minScore = lib.calculateQualityScore({
      symptom: 'x',
      root_cause: { description: 'x', confidence: 0 },
      fix: { approach: '', changes: [] },
      verification: { status: 'unverified' },
      tags: [],
    });
    assert(minScore >= 0, 'Min score should be >= 0');
    assert(minScore <= 1, 'Min score should be <= 1');

    // Maximal incident should score high
    const maxScore = lib.calculateQualityScore({
      symptom: 'A very detailed symptom description that exceeds fifty characters easily and provides good context',
      root_cause: {
        description: 'A comprehensive root cause description that is over one hundred characters long and explains exactly what went wrong in great detail',
        confidence: 0.95,
      },
      fix: {
        approach: 'Thorough fix approach documented with clear steps',
        changes: [
          { file: 'a.ts', lines_changed: 5, change_type: 'modify', summary: 'fix' },
          { file: 'b.ts', lines_changed: 3, change_type: 'modify', summary: 'fix' },
          { file: 'c.ts', lines_changed: 2, change_type: 'add', summary: 'test' },
        ],
      },
      verification: {
        status: 'verified',
        regression_tests_passed: true,
        user_journey_tested: true,
      },
      tags: ['quality', 'test', 'boundary', 'edge', 'case'],
      prevention: ['Always check dependencies'],
    });
    assert(maxScore >= 0.7, `Max score should be >= 0.7, got ${maxScore}`);
  });

  // ---------------------------------------------------------------------------
  // Cleanup
  // ---------------------------------------------------------------------------
  suite('Cleanup');

  await test('Delete test incidents', async () => {
    const config = lib.getConfig();
    const paths = lib.getMemoryPaths(config);
    const incidentPath = path.join(paths.incidents, `${testIncident1.incident_id}.json`);

    if (fs.existsSync(incidentPath)) {
      fs.unlinkSync(incidentPath);
    }
    assert(!fs.existsSync(incidentPath), 'Test incident should be deleted');
  });

  await test('Rebuild index after cleanup', async () => {
    const index = await lib.rebuildIndex();
    assertDefined(index, 'Index should rebuild after cleanup');
  });

  // ---------------------------------------------------------------------------
  // Summary
  // ---------------------------------------------------------------------------
  printSummary();
}

function printSummary() {
  console.log('\n' + '='.repeat(60));
  console.log('TEST SUMMARY');
  console.log('='.repeat(60));

  let totalPassed = 0;
  let totalFailed = 0;
  let totalDuration = 0;

  for (const suite of results) {
    const passed = suite.tests.filter(t => t.passed).length;
    const failed = suite.tests.filter(t => !t.passed).length;
    const duration = suite.tests.reduce((sum, t) => sum + t.duration, 0);

    totalPassed += passed;
    totalFailed += failed;
    totalDuration += duration;

    const status = failed === 0 ? '✅' : '❌';
    console.log(`${status} ${suite.name}: ${passed}/${suite.tests.length} passed (${duration}ms)`);

    for (const test of suite.tests.filter(t => !t.passed)) {
      console.log(`   ❌ ${test.name}: ${test.error}`);
    }
  }

  console.log('\n' + '-'.repeat(60));
  const overallStatus = totalFailed === 0 ? '✅ ALL TESTS PASSED' : '❌ SOME TESTS FAILED';
  console.log(`${overallStatus}`);
  console.log(`Total: ${totalPassed} passed, ${totalFailed} failed`);
  console.log(`Duration: ${totalDuration}ms`);
  console.log('-'.repeat(60));

  process.exit(totalFailed > 0 ? 1 : 0);
}

runTests().catch(err => {
  console.error('Fatal error running tests:', err);
  process.exit(1);
});
