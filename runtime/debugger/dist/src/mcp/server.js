#!/usr/bin/env node
"use strict";
/**
 * Coding Debugger MCP Server
 *
 * JSON-RPC 2.0 over stdio (MCP protocol).
 * Exposes debugging memory tools: search, store, detail, status, list, patterns, outcome, read_logs.
 */
Object.defineProperty(exports, "__esModule", { value: true });
const readline_1 = require("readline");
const tools_1 = require("./tools");
const logger_1 = require("../logger");
const util_1 = require("util");
// One routing policy for the lifetime of stdio; per-call swaps race under concurrency.
const toStderr = (...args) => { process.stderr.write((0, util_1.format)(...args) + '\n'); };
console.log = toStderr;
console.info = toStderr;
console.debug = toStderr;
// --- JSON-RPC transport over stdio ---
const rl = (0, readline_1.createInterface)({ input: process.stdin, terminal: false });
// stdio is newline-delimited JSON-RPC: malformed input must not poison later messages.
rl.on('line', (line) => {
    if (!line.trim())
        return;
    let msg;
    try {
        msg = JSON.parse(line);
    }
    catch {
        sendError(null, -32700, 'Parse error');
        return;
    }
    if (!msg || typeof msg !== 'object' || Array.isArray(msg) ||
        msg.jsonrpc !== '2.0' ||
        typeof msg.method !== 'string' ||
        ('id' in msg && typeof msg.id !== 'string' && typeof msg.id !== 'number')) {
        sendError(null, -32600, 'Invalid Request');
        return;
    }
    void handleMessage(msg);
});
function send(msg) {
    process.stdout.write(JSON.stringify(msg) + '\n');
}
function sendResult(id, result) {
    send({ jsonrpc: '2.0', id, result });
}
function sendError(id, code, message) {
    send({ jsonrpc: '2.0', id, error: { code, message } });
}
// --- MCP Protocol ---
const SERVER_INFO = {
    name: 'coding-debugger',
    version: '1.9.1',
};
const CAPABILITIES = {
    tools: {},
};
// --- Message handler ---
async function handleMessage(msg) {
    if (msg.jsonrpc !== '2.0')
        return;
    const { id, method, params } = msg;
    if (id === undefined)
        return; // Notifications never produce responses or invoke write tools.
    try {
        switch (method) {
            case 'initialize': {
                sendResult(id, {
                    protocolVersion: ['2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25'].includes(String(params?.protocolVersion))
                        ? params.protocolVersion : '2025-11-25',
                    serverInfo: SERVER_INFO,
                    capabilities: CAPABILITIES,
                });
                break;
            }
            case 'notifications/initialized': {
                // Client acknowledged — no response needed
                break;
            }
            case 'ping': {
                if (id !== undefined)
                    sendResult(id, {});
                break;
            }
            case 'tools/list': {
                sendResult(id, { tools: tools_1.TOOLS });
                break;
            }
            case 'tools/call': {
                const { name, arguments: args } = params;
                const result = await (0, tools_1.handleToolCall)(name, args || {});
                sendResult(id, result);
                break;
            }
            default: {
                if (id !== undefined) {
                    sendError(id, -32601, `Method not found: ${method}`);
                }
            }
        }
    }
    catch (err) {
        if (id !== undefined) {
            sendError(id, -32000, err instanceof Error ? err.message : 'Internal error');
        }
    }
}
// Initialize internal logger
(0, logger_1.configureLogger)();
// Log to stderr so it doesn't interfere with the protocol
process.stderr.write('Debugger MCP server started\n');
//# sourceMappingURL=server.js.map