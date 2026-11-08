"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.withCorpusWrite = withCorpusWrite;
exports.writeJsonAtomic = writeJsonAtomic;
/** Same-corpus writer ownership across processes; readers never create lock state. */
const promises_1 = __importDefault(require("fs/promises"));
const path_1 = __importDefault(require("path"));
const os_1 = require("os");
const crypto_1 = require("crypto");
const async_hooks_1 = require("async_hooks");
const config_1 = require("./config");
const held = new async_hooks_1.AsyncLocalStorage();
const localHost = (0, os_1.hostname)();
const pause = () => new Promise(resolve => setTimeout(resolve, 20));
const codeOf = (error) => error.code;
function processAlive(pid) {
    try {
        process.kill(pid, 0);
        return true;
    }
    catch (error) {
        if (codeOf(error) === 'ESRCH')
            return false;
        throw error;
    }
}
async function readOwner(lock) {
    const owner = JSON.parse(await promises_1.default.readFile(path_1.default.join(lock, 'owner.json'), 'utf8'));
    if (owner.host !== localHost || !Number.isSafeInteger(owner.pid) || owner.pid <= 0 || typeof owner.nonce !== 'string' || !owner.nonce) {
        throw new Error(`Cannot establish corpus writer ownership: ${lock}`);
    }
    return owner;
}
async function recoverDeadWriter(lock) {
    try {
        const owner = await readOwner(lock);
        if (processAlive(owner.pid))
            return;
        const guard = path_1.default.join(lock, 'recovery');
        // Link data publishes the recovery PID and exact lock generation atomically.
        try {
            await promises_1.default.symlink(JSON.stringify({ pid: process.pid, host: localHost, owner: owner.nonce }), guard);
        }
        catch (error) {
            if (codeOf(error) === 'ENOENT')
                return;
            if (codeOf(error) !== 'EEXIST')
                throw error;
            try {
                const recovering = JSON.parse(await promises_1.default.readlink(guard));
                if (recovering.owner === owner.nonce && recovering.host === localHost && Number.isSafeInteger(recovering.pid) && recovering.pid > 0 && processAlive(recovering.pid))
                    return;
            }
            catch (readError) {
                if (codeOf(readError) === 'ENOENT')
                    return;
            }
            throw new Error(`Interrupted or unknown corpus writer recovery; retained ${guard}`);
        }
        const current = await readOwner(lock);
        if (current.nonce !== owner.nonce || processAlive(current.pid))
            return;
        const abandoned = `${lock}.abandoned-${process.pid}-${(0, crypto_1.randomBytes)(8).toString('hex')}`;
        await promises_1.default.rename(lock, abandoned);
        // Never unlink a recovery guard through the shared pathname: the directory
        // may already belong to a later writer. Remove only this quarantined tree.
        await promises_1.default.rm(abandoned, { recursive: true });
    }
    catch (error) {
        if (codeOf(error) !== 'ENOENT')
            throw error;
    }
}
async function acquire(root) {
    const lock = path_1.default.join(root, '.corpus-write-lock');
    const candidate = await promises_1.default.mkdtemp(path_1.default.join(root, '.corpus-writer-'));
    try {
        await promises_1.default.writeFile(path_1.default.join(candidate, 'owner.json'), JSON.stringify({ pid: process.pid, host: localHost, nonce: path_1.default.basename(candidate) }));
        for (;;) {
            try {
                await promises_1.default.rename(candidate, lock);
                break;
            }
            catch (error) {
                if (!['EEXIST', 'ENOTEMPTY'].includes(codeOf(error) || ''))
                    throw error;
                await recoverDeadWriter(lock);
                await pause();
            }
        }
    }
    catch (error) {
        await promises_1.default.rm(candidate, { recursive: true, force: true });
        throw error;
    }
    return async () => {
        // Free the shared name in one step, before recursive cleanup can expose an
        // empty directory that another writer could replace.
        await promises_1.default.rename(lock, candidate);
        await promises_1.default.rm(candidate, { recursive: true });
    };
}
async function withCorpusWrite(config, action) {
    const requested = (0, config_1.getMemoryPaths)(config).root;
    await promises_1.default.mkdir(requested, { recursive: true });
    const root = await promises_1.default.realpath(requested);
    if (held.getStore()?.get(root)?.active)
        return action();
    const release = await acquire(root);
    const lease = { active: true };
    const context = new Map(held.getStore());
    context.set(root, lease);
    try {
        return await held.run(context, action);
    }
    finally {
        lease.active = false;
        await release();
    }
}
/** Publish a complete JSON file; failed writes leave the prior file readable. */
async function writeJsonAtomic(filename, value, pretty = false) {
    const temporary = `${filename}.${process.pid}.${(0, crypto_1.randomBytes)(8).toString('hex')}.tmp`;
    try {
        await promises_1.default.writeFile(temporary, JSON.stringify(value, null, pretty ? 2 : undefined), { flag: 'wx', mode: 0o600 });
        await promises_1.default.rename(temporary, filename);
    }
    finally {
        await promises_1.default.unlink(temporary).catch(error => { if (codeOf(error) !== 'ENOENT')
            throw error; });
    }
}
//# sourceMappingURL=corpus-write.js.map