/** Same-corpus writer ownership across processes; readers never create lock state. */
import fs from 'fs/promises';
import path from 'path';
import { hostname } from 'os';
import { randomBytes } from 'crypto';
import { AsyncLocalStorage } from 'async_hooks';
import type { MemoryConfig } from './types';
import { getMemoryPaths } from './config';

type Lease = { active: boolean };
const held = new AsyncLocalStorage<Map<string, Lease>>();
const localHost = hostname();
const pause = () => new Promise(resolve => setTimeout(resolve, 20));
const codeOf = (error: unknown) => (error as NodeJS.ErrnoException).code;

function processAlive(pid: number): boolean {
  try { process.kill(pid, 0); return true; }
  catch (error) { if (codeOf(error) === 'ESRCH') return false; throw error; }
}

type Owner = { pid: number; host: string; nonce: string };

async function readOwner(lock: string): Promise<Owner> {
  const owner = JSON.parse(await fs.readFile(path.join(lock, 'owner.json'), 'utf8'));
  if (owner.host !== localHost || !Number.isSafeInteger(owner.pid) || owner.pid <= 0 || typeof owner.nonce !== 'string' || !owner.nonce) {
    throw new Error(`Cannot establish corpus writer ownership: ${lock}`);
  }
  return owner;
}

async function recoverDeadWriter(lock: string): Promise<void> {
  try {
    const owner = await readOwner(lock);
    if (processAlive(owner.pid)) return;
    const guard = path.join(lock, `recovery-${encodeURIComponent(owner.nonce)}`);
    // A delayed recoverer may publish into a later lock directory. Its marker
    // must be scoped to the generation it read so it cannot poison that owner.
    // Link data publishes the recovery PID and exact lock generation atomically.
    try { await fs.symlink(JSON.stringify({ pid: process.pid, host: localHost, owner: owner.nonce }), guard); }
    catch (error) {
      if (codeOf(error) === 'ENOENT') return;
      if (codeOf(error) !== 'EEXIST') throw error;
      try {
        const recovering = JSON.parse(await fs.readlink(guard));
        if (recovering.owner === owner.nonce && recovering.host === localHost && Number.isSafeInteger(recovering.pid) && recovering.pid > 0 && processAlive(recovering.pid)) return;
      } catch (readError) { if (codeOf(readError) === 'ENOENT') return; }
      throw new Error(`Interrupted or unknown corpus writer recovery; retained ${guard}`);
    }
    const current = await readOwner(lock);
    if (current.nonce !== owner.nonce || processAlive(current.pid)) return;
    const abandoned = `${lock}.abandoned-${process.pid}-${randomBytes(8).toString('hex')}`;
    await fs.rename(lock, abandoned);
    // Never unlink a recovery guard through the shared pathname: the directory
    // may already belong to a later writer. Remove only this quarantined tree.
    await fs.rm(abandoned, { recursive: true });
  } catch (error) {
    if (codeOf(error) !== 'ENOENT') throw error;
  }
}

async function acquire(root: string): Promise<() => Promise<void>> {
  const lock = path.join(root, '.corpus-write-lock');
  const candidate = await fs.mkdtemp(path.join(root, '.corpus-writer-'));
  try {
    await fs.writeFile(path.join(candidate, 'owner.json'), JSON.stringify({ pid: process.pid, host: localHost, nonce: path.basename(candidate) }));
    // Never evict a live PID: hung owners and PID reuse remain liveness limits.
    for (;;) {
      try { await fs.rename(candidate, lock); break; }
      catch (error) {
        if (!['EEXIST', 'ENOTEMPTY'].includes(codeOf(error) || '')) throw error;
        await recoverDeadWriter(lock);
        await pause();
      }
    }
  } catch (error) {
    await fs.rm(candidate, { recursive: true, force: true });
    throw error;
  }
  return async () => {
    // Free the shared name in one step, before recursive cleanup can expose an
    // empty directory that another writer could replace.
    await fs.rename(lock, candidate);
    await fs.rm(candidate, { recursive: true });
  };
}

export async function withCorpusWrite<T>(config: MemoryConfig | undefined, action: () => Promise<T>): Promise<T> {
  const requested = getMemoryPaths(config).root;
  await fs.mkdir(requested, { recursive: true });
  const root = await fs.realpath(requested);
  if (held.getStore()?.get(root)?.active) return action();
  const release = await acquire(root);
  const lease = { active: true };
  const context = new Map(held.getStore());
  context.set(root, lease);
  try { return await held.run(context, action); }
  finally { lease.active = false; await release(); }
}

/** Publish a complete JSON file; failed writes leave the prior file readable. */
export async function writeJsonAtomic(filename: string, value: unknown, pretty = false): Promise<void> {
  const temporary = `${filename}.${process.pid}.${randomBytes(8).toString('hex')}.tmp`;
  try {
    let existingMode: number | undefined;
    try { existingMode = (await fs.stat(filename)).mode & 0o7777; }
    catch (error) { if (codeOf(error) !== 'ENOENT') throw error; }
    await fs.writeFile(temporary, JSON.stringify(value, null, pretty ? 2 : undefined), { flag: 'wx', mode: existingMode });
    // Existing permissions survive replacement even when the writer's umask
    // would otherwise remove shared-reader permissions from the temporary file.
    if (existingMode !== undefined) await fs.chmod(temporary, existingMode);
    await fs.rename(temporary, filename);
  } finally {
    await fs.unlink(temporary).catch(error => { if (codeOf(error) !== 'ENOENT') throw error; });
  }
}
