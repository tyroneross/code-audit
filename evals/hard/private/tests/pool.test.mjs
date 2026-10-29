import { test } from 'node:test'
import assert from 'node:assert/strict'
const dir = process.env.CASE_DIR
const { BrowserPool } = await import(`${dir}/browser-pool.ts`)

const within = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('timed out (hang)')), ms))])

test('close() while a holder is active rejects pending waiters instead of hanging', async () => {
  const pool = new BrowserPool()
  await pool.acquire()
  const b = pool.acquire()
  b.catch(() => {})
  await pool.close()
  await assert.rejects(within(b, 500), /closed/)
})

test('a fresh acquire after release() cannot jump ahead of a queued waiter', async () => {
  const pool = new BrowserPool()
  const order = []
  await pool.acquire()
  const b = (async () => { await pool.acquire(); order.push('B'); await new Promise(r => setTimeout(r, 5)); pool.release() })()
  await Promise.resolve()
  pool.release()
  const c = (async () => { await pool.acquire(); order.push('C'); pool.release() })()
  await within(Promise.all([b, c]), 1000)
  assert.deepEqual(order, ['B', 'C'])
})

test('a waiter woken by close() never launches a driver on the closed pool', async () => {
  const pool = new BrowserPool()
  await pool.acquire()
  const b = pool.acquire()
  b.catch(() => {})
  await pool.close()
  pool.release()
  await assert.rejects(within(b, 500), /closed/)
  assert.equal(pool.hasWarmDriver(), false)
})
