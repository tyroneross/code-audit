#!/usr/bin/env node
/**
 * End-to-End Test Suite for Claude Code Debugger v1.4.0
 *
 * Tests all major features:
 * 1. Core Storage (incidents, patterns)
 * 2. Parallel Retrieval
 * 3. Assessment Orchestration
 * 4. Trace Ingestion
 * 5. Result Aggregation
 * 6. Token-Efficient Retrieval
 *
 * Run: node test-v1.4.0-e2e.js
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
    throw new Error(`${message}: expected ${expected}, got ${actual}`);
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

// =============================================================================
// TESTS
// =============================================================================

async function runTests() {
  console.log('\n' + '🧪'.repeat(30));
  console.log('CLAUDE CODE DEBUGGER v1.4.0 - END-TO-END TESTS');
  console.log('🧪'.repeat(30));

  // ---------------------------------------------------------------------------
  // 1. Module Loading Tests
  // ---------------------------------------------------------------------------
  suite('1. Module Loading');

  let lib;

  await test('Import main module from dist', async () => {
    lib = require('./dist/src/index.js');
    assert(lib !== undefined, 'Module should load');
  });

  await test('Core exports exist', () => {
    assertDefined(lib.getConfig, 'getConfig');
    assertDefined(lib.getMemoryPaths, 'getMemoryPaths');
    assertDefined(lib.storeIncident, 'storeIncident');
    assertDefined(lib.loadAllIncidents, 'loadAllIncidents');
    assertDefined(lib.checkMemory, 'checkMemory');
    assertDefined(lib.generateIncidentId, 'generateIncidentId');
    assertDefined(lib.generatePatternId, 'generatePatternId');
  });

  await test('v1.4.0 Parallel exports exist', () => {
    assertDefined(lib.parallelSearch, 'parallelSearch');
    assertDefined(lib.parallelPatternMatch, 'parallelPatternMatch');
    assertDefined(lib.parallelMemoryCheck, 'parallelMemoryCheck');
  });

  await test('v1.4.0 Assessment exports exist', () => {
    assertDefined(lib.detectDomains, 'detectDomains');
    assertDefined(lib.selectDomainsForAssessment, 'selectDomainsForAssessment');
    assertDefined(lib.generateAssessorPrompts, 'generateAssessorPrompts');
    assertDefined(lib.rankAssessments, 'rankAssessments');
    assertDefined(lib.formatOrchestrationResult, 'formatOrchestrationResult');
    assertDefined(lib.prepareOrchestration, 'prepareOrchestration');
  });

  await test('v1.4.0 Result aggregation exports exist', () => {
    assertDefined(lib.scoreAssessment, 'scoreAssessment');
    assertDefined(lib.scoreIncident, 'scoreIncident');
    assertDefined(lib.aggregateResults, 'aggregateResults');
    assertDefined(lib.formatAggregatedResults, 'formatAggregatedResults');
    assertDefined(lib.createQuickSummary, 'createQuickSummary');
  });

  await test('v1.4.0 Trace exports exist', () => {
    assertDefined(lib.storeTrace, 'storeTrace');
    assertDefined(lib.loadAllTraces, 'loadAllTraces');
    assertDefined(lib.generateTraceId, 'generateTraceId');
    assertDefined(lib.TraceSummarizer, 'TraceSummarizer');
    assertDefined(lib.OpenTelemetryAdapter, 'OpenTelemetryAdapter');
    assertDefined(lib.SentryAdapter, 'SentryAdapter');
    assertDefined(lib.LangchainAdapter, 'LangchainAdapter');
    assertDefined(lib.BrowserTraceAdapter, 'BrowserTraceAdapter');
    assertDefined(lib.getAdapter, 'getAdapter');
  });

  // ---------------------------------------------------------------------------
  // 2. Configuration Tests
  // ---------------------------------------------------------------------------
  suite('2. Configuration');

  await test('getConfig returns valid config', () => {
    const config = lib.getConfig();
    assertDefined(config.storageMode, 'storageMode');
    assert(
      config.storageMode === 'local' || config.storageMode === 'shared',
      'storageMode must be local or shared'
    );
    assertDefined(config.memoryPath, 'memoryPath');
    assertType(config.autoMine, 'boolean', 'autoMine');
  });

  await test('getMemoryPaths returns valid paths', () => {
    const config = lib.getConfig();
    const paths = lib.getMemoryPaths(config);
    assertDefined(paths.root, 'root path');
    assertDefined(paths.incidents, 'incidents path');
    assertDefined(paths.patterns, 'patterns path');
    assertDefined(paths.sessions, 'sessions path');
  });

  // ---------------------------------------------------------------------------
  // 3. Storage Tests
  // ---------------------------------------------------------------------------
  suite('3. Storage Operations');

  // Use proper ID format (INC_YYYYMMDD_HHMMSS_xxxx)
  const testIncidentId = lib.generateIncidentId();

  await test('Generate incident ID', () => {
    const id = lib.generateIncidentId();
    assert(id.startsWith('INC_'), 'ID should start with INC_');
    assert(id.length > 10, 'ID should be substantial');
  });

  await test('Generate pattern ID', () => {
    const id = lib.generatePatternId('test', 'category');
    assert(id.startsWith('PTN_'), 'ID should start with PTN_');
  });

  await test('Generate trace ID', () => {
    const id = lib.generateTraceId();
    assert(id.startsWith('TRC_'), 'ID should start with TRC_');
  });

  await test('Store test incident', async () => {
    const incident = {
      incident_id: testIncidentId,
      timestamp: Date.now(),
      symptom: 'E2E Test: React component infinite re-render loop',
      root_cause: {
        description: 'Missing dependency in useEffect hook causes re-render',
        category: 'react-hooks',
        confidence: 0.95,
      },
      fix: {
        approach: 'Add missing dependency to useEffect array',
        changes: [{
          file: 'test/Component.tsx',
          lines_changed: 1,
          change_type: 'modify',
          summary: 'Added dep to useEffect'
        }],
        time_to_fix: 15,
      },
      verification: {
        status: 'verified',
        regression_tests_passed: true,
        user_journey_tested: true,
        success_criteria_met: true,
      },
      tags: ['react', 'hooks', 'useEffect', 'e2e-test'],
      files_changed: ['test/Component.tsx'],
      quality_gates: {
        guardian_validated: true,
        tested_e2e: true,
        tested_from_ui: true,
        security_reviewed: false,
        architect_reviewed: false
      },
      completeness: {
        symptom: true,
        root_cause: true,
        fix: true,
        verification: true,
        quality_score: 0.8
      }
    };

    const result = await lib.storeIncident(incident);
    assertDefined(result.incident_id, 'Should return incident_id');
    assertDefined(result.file_path, 'Should return file_path');
  });

  await test('Load stored incident', async () => {
    const incident = await lib.loadIncident(testIncidentId);
    assertDefined(incident, 'Incident should load');
    assertEqual(incident.incident_id, testIncidentId, 'ID should match');
    assert(incident.symptom.includes('React'), 'Symptom should match');
  });

  await test('Load all incidents', async () => {
    const incidents = await lib.loadAllIncidents();
    assert(Array.isArray(incidents), 'Should return array');
    assert(incidents.length >= 1, 'Should have at least test incident');
  });

  // ---------------------------------------------------------------------------
  // 4. Search & Retrieval Tests
  // ---------------------------------------------------------------------------
  suite('4. Search & Retrieval');

  await test('Basic memory check', async () => {
    const result = await lib.checkMemory('React component re-render');
    assertDefined(result, 'Result should exist');
    // Result may have incidents array or other structure
    assert(typeof result === 'object', 'Result should be object');
  });

  await test('Enhanced search', async () => {
    const results = await lib.enhancedSearch('useEffect hook problem');
    assert(Array.isArray(results), 'Should return array');
  });

  await test('Search by tags', async () => {
    const results = await lib.searchByTags(['react', 'hooks']);
    assert(Array.isArray(results), 'Should return array');
  });

  await test('Get recent incidents', async () => {
    const recent = await lib.getRecentIncidents(10);
    assert(Array.isArray(recent), 'Should return array');
  });

  await test('Quick memory check', async () => {
    const result = await lib.quickMemoryCheck('API error');
    assertDefined(result, 'Result should exist');
  });

  // ---------------------------------------------------------------------------
  // 5. Parallel Retrieval Tests (v1.4.0)
  // ---------------------------------------------------------------------------
  suite('5. Parallel Retrieval (v1.4.0)');

  await test('Parallel search executes', async () => {
    const result = await lib.parallelSearch('React infinite loop render');
    assertDefined(result, 'Result should exist');
    assert(typeof result === 'object', 'Result should be object');
  });

  await test('Parallel pattern match', async () => {
    const result = await lib.parallelPatternMatch('API returns 500 error');
    assertDefined(result, 'Result should exist');
  });

  await test('Parallel memory check', async () => {
    const result = await lib.parallelMemoryCheck('performance bottleneck slow');
    assertDefined(result, 'Result should exist');
  });

  // ---------------------------------------------------------------------------
  // 6. Assessment Orchestration Tests (v1.4.0)
  // ---------------------------------------------------------------------------
  suite('6. Assessment Orchestration (v1.4.0)');

  await test('Detect domains from database symptom', () => {
    const detections = lib.detectDomains('Database query timeout during API call');
    assert(Array.isArray(detections), 'Should return array');
    const domains = detections.map(d => d.domain);
    assert(domains.includes('database'), 'Should detect database');
    assert(domains.includes('api'), 'Should detect api');
  });

  await test('Detect domains from frontend symptom', () => {
    const detections = lib.detectDomains('React useEffect causes infinite render');
    const domains = detections.map(d => d.domain);
    assert(domains.includes('frontend'), 'Should detect frontend');
  });

  await test('Detect domains from performance symptom', () => {
    const detections = lib.detectDomains('Application is slow with high memory usage');
    const domains = detections.map(d => d.domain);
    assert(domains.includes('performance'), 'Should detect performance');
  });

  await test('Select domains for assessment', () => {
    const detections = lib.detectDomains('Search API returns wrong results slowly');
    const selected = lib.selectDomainsForAssessment(detections);
    assert(Array.isArray(selected), 'Should return array');
  });

  await test('Generate assessor prompts', () => {
    const symptom = 'Login API fails with 500 error';
    const domains = ['api', 'database'];
    const prompts = lib.generateAssessorPrompts(symptom, domains);
    assertDefined(prompts, 'Prompts should exist');
    assert(typeof prompts === 'object', 'Should return object');
  });

  await test('Prepare orchestration', () => {
    const result = lib.prepareOrchestration('Search is slow and returns wrong results');
    assertDefined(result, 'Result should exist');
    assertDefined(result.detections, 'Detections should exist');
    assertDefined(result.selectedDomains, 'Selected domains should exist');
    assertDefined(result.prompts, 'Prompts should exist');
    assertType(result.shouldUseOrchestrator, 'boolean', 'shouldUseOrchestrator');
  });

  // ---------------------------------------------------------------------------
  // 7. Result Aggregation Tests (v1.4.0)
  // ---------------------------------------------------------------------------
  suite('7. Result Aggregation (v1.4.0)');

  await test('Score assessment returns scored item', () => {
    const assessment = {
      domain: 'api',
      confidence: 0.85,
      symptom_classification: 'API error',
      probable_causes: ['Auth issue'],
      recommended_actions: ['Check middleware'],
      related_incidents: [],
      search_tags: ['api', 'error']
    };
    const scored = lib.scoreAssessment(assessment);
    assertDefined(scored, 'Scored item should exist');
    assertDefined(scored.type, 'Type should exist');
    assertEqual(scored.type, 'assessment', 'Type should be assessment');
    assertDefined(scored.score, 'Score should exist');
    assert(scored.score >= 0 && scored.score <= 1, 'Score should be between 0 and 1');
  });

  await test('Format aggregated results returns string', () => {
    const aggregated = {
      items: [],
      total_count: 0,
      domains_involved: [],
      aggregate_confidence: 0,
      recommended_actions: [],
      search_tags: []
    };
    const formatted = lib.formatAggregatedResults(aggregated);
    assertType(formatted, 'string', 'Should return string');
  });

  await test('Create quick summary returns string', () => {
    const aggregated = {
      items: [],
      total_count: 0,
      domains_involved: ['api'],
      aggregate_confidence: 0.5,
      recommended_actions: ['Check auth'],
      search_tags: ['api']
    };
    const summary = lib.createQuickSummary(aggregated);
    assertType(summary, 'string', 'Should return string');
  });

  // ---------------------------------------------------------------------------
  // 8. Trace System Tests (v1.4.0)
  // ---------------------------------------------------------------------------
  suite('8. Trace System (v1.4.0)');

  await test('Generate trace ID format', () => {
    const id = lib.generateTraceId();
    assert(id.startsWith('TRC_'), 'ID should start with TRC_');
  });

  await test('OpenTelemetry adapter instantiates', () => {
    const adapter = new lib.OpenTelemetryAdapter();
    assertDefined(adapter, 'Should instantiate');
    assertDefined(adapter.parse, 'Should have parse method');
  });

  await test('Sentry adapter instantiates', () => {
    const adapter = new lib.SentryAdapter();
    assertDefined(adapter, 'Should instantiate');
    assertDefined(adapter.parse, 'Should have parse method');
  });

  await test('Langchain adapter instantiates', () => {
    const adapter = new lib.LangchainAdapter();
    assertDefined(adapter, 'Should instantiate');
    assertDefined(adapter.parse, 'Should have parse method');
  });

  await test('Browser trace adapter instantiates', () => {
    const adapter = new lib.BrowserTraceAdapter();
    assertDefined(adapter, 'Should instantiate');
    assertDefined(adapter.parse, 'Should have parse method');
  });

  await test('TraceSummarizer instantiates', () => {
    const summarizer = new lib.TraceSummarizer();
    assertDefined(summarizer, 'Should instantiate');
  });

  await test('getAdapter returns correct adapter', () => {
    const otelAdapter = lib.getAdapter('opentelemetry');
    assertDefined(otelAdapter, 'Should return OpenTelemetry adapter');

    const sentryAdapter = lib.getAdapter('sentry');
    assertDefined(sentryAdapter, 'Should return Sentry adapter');
  });

  await test('Store and load trace', async () => {
    const traceId = lib.generateTraceId();
    const trace = {
      trace_id: traceId,
      source: 'test',
      timestamp: Date.now(),
      category: 'error',
      severity: 'error',
      summary: {
        title: 'Test trace',
        description: 'E2E test trace',
        key_findings: ['Test finding'],
        token_count: 50,
      },
      raw_data: { test: true },
    };

    const stored = await lib.storeTrace(trace);
    assertDefined(stored.trace_id, 'Should return trace_id');
    assertDefined(stored.file_path, 'Should return file_path');
  });

  await test('Load all traces', async () => {
    const traces = await lib.loadAllTraces();
    assert(Array.isArray(traces), 'Should return array');
  });

  // ---------------------------------------------------------------------------
  // 9. Quality & Interactive Tests
  // ---------------------------------------------------------------------------
  suite('9. Quality Scoring');

  await test('Calculate quality score', () => {
    const incident = {
      incident_id: 'quality-test',
      timestamp: Date.now(),
      symptom: 'Test quality scoring with comprehensive details',
      root_cause: {
        description: 'This is a detailed root cause with enough information to understand the issue fully and completely',
        category: 'test',
        confidence: 0.9,
      },
      fix: {
        approach: 'Comprehensive fix approach with clear steps and proper documentation',
        changes: [{ file: 'test.ts', lines_changed: 5, change_type: 'modify', summary: 'fix' }],
        time_to_fix: 30,
      },
      verification: {
        status: 'verified',
        regression_tests_passed: true,
        user_journey_tested: true,
        success_criteria_met: true,
      },
      tags: ['quality', 'test', 'verification'],
      files_changed: ['test.ts'],
      quality_gates: {
        guardian_validated: true,
        tested_e2e: true,
        tested_from_ui: true,
        security_reviewed: false,
        architect_reviewed: false
      },
      completeness: {
        symptom: true,
        root_cause: true,
        fix: true,
        verification: true,
        quality_score: 0.8
      }
    };

    const score = lib.calculateQualityScore(incident);
    // Score is 0-1, not 0-100
    assert(score >= 0 && score <= 1, 'Score should be 0-1');
    assert(score >= 0.4, 'Well-documented incident should score >= 0.4');
  });

  await test('Generate quality feedback', () => {
    const incident = {
      incident_id: 'feedback-test',
      timestamp: Date.now(),
      symptom: 'Test feedback generation',
      root_cause: { description: 'Short', category: 'test', confidence: 0.5 },
      fix: { approach: 'Fix', changes: [] },
      verification: { status: 'unverified' },
      tags: [],
      files_changed: [],
      quality_gates: {},
      completeness: { quality_score: 0.3 }
    };

    const feedback = lib.generateQualityFeedback(incident);
    assertType(feedback, 'string', 'Feedback should be string');
    assert(feedback.length > 0, 'Feedback should not be empty');
  });

  // ---------------------------------------------------------------------------
  // 10. Pattern Operations
  // ---------------------------------------------------------------------------
  suite('10. Pattern Operations');

  await test('Load all patterns', async () => {
    const patterns = await lib.loadAllPatterns();
    assert(Array.isArray(patterns), 'Should return array');
  });

  await test('Suggest patterns runs without error', async () => {
    // suggestPatterns() is a display function that returns void
    await lib.suggestPatterns();
    // If it doesn't throw, it passes
    assert(true, 'suggestPatterns should execute without error');
  });

  // ---------------------------------------------------------------------------
  // Cleanup
  // ---------------------------------------------------------------------------
  suite('Cleanup');

  await test('Delete test incident', async () => {
    const config = lib.getConfig();
    const paths = lib.getMemoryPaths(config);
    const incidentPath = path.join(paths.incidents, `${testIncidentId}.json`);

    if (fs.existsSync(incidentPath)) {
      fs.unlinkSync(incidentPath);
    }
    assert(!fs.existsSync(incidentPath), 'Test incident should be deleted');
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
    const passed = suite.tests.filter((t) => t.passed).length;
    const failed = suite.tests.filter((t) => !t.passed).length;
    const duration = suite.tests.reduce((sum, t) => sum + t.duration, 0);

    totalPassed += passed;
    totalFailed += failed;
    totalDuration += duration;

    const status = failed === 0 ? '✅' : '❌';
    console.log(`${status} ${suite.name}: ${passed}/${suite.tests.length} passed (${duration}ms)`);

    // Show failed tests
    for (const test of suite.tests.filter((t) => !t.passed)) {
      console.log(`   ❌ ${test.name}: ${test.error}`);
    }
  }

  console.log('\n' + '-'.repeat(60));
  const overallStatus = totalFailed === 0 ? '✅ ALL TESTS PASSED' : '❌ SOME TESTS FAILED';
  console.log(`${overallStatus}`);
  console.log(`Total: ${totalPassed} passed, ${totalFailed} failed`);
  console.log(`Duration: ${totalDuration}ms`);
  console.log('-'.repeat(60));

  // Exit with appropriate code
  process.exit(totalFailed > 0 ? 1 : 0);
}

// Run tests
runTests().catch((err) => {
  console.error('Fatal error running tests:', err);
  process.exit(1);
});
