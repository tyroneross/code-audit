import { test } from 'node:test'
import assert from 'node:assert/strict'
const dir = process.env.CASE_DIR
const { shouldEmitEmptyGrounding } = await import(`${dir}/grounding.ts`)
const { rrfFuse } = await import(`${dir}/rrf-fusion.ts`)

// Sources as the QA route builds them: score copied verbatim from /api/search,
// which returns rrfFuse() scores.
function sourcesFrom(fused) {
  return fused.slice(0, 5).map((h) => ({ uuid: h.doc_id, kind: 'corpus', title: h.doc_id, body: 'x', score: h.score }))
}

test('strong hybrid hits (top of every leg) are enough to ground an answer', () => {
  const leg = ['a', 'b', 'c', 'd', 'e'].map((doc_id, i) => ({ doc_id, rank: i }))
  const fused = rrfFuse({ bm25: leg, vector: leg, kg: leg })
  assert.equal(shouldEmitEmptyGrounding(sourcesFrom(fused)), false)
})

test('a single-leg top-5 result set still grounds', () => {
  const leg = ['a', 'b', 'c', 'd', 'e'].map((doc_id, i) => ({ doc_id, rank: i }))
  const fused = rrfFuse({ bm25: leg })
  assert.equal(shouldEmitEmptyGrounding(sourcesFrom(fused)), false)
})

test('only deep-tail hits (rank > 100 in a single leg) do not ground', () => {
  const leg = Array.from({ length: 300 }, (_, i) => ({ doc_id: 'd' + i, rank: i }))
  const fused = rrfFuse({ bm25: leg }).slice(250)
  assert.equal(shouldEmitEmptyGrounding(sourcesFrom(fused)), true)
})

test('fewer than two sources never ground', () => {
  assert.equal(shouldEmitEmptyGrounding([{ uuid: 'a', kind: 'corpus', title: 'a', body: 'x', score: 0.05 }]), true)
})
