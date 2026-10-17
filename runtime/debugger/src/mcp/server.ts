#!/usr/bin/env node
/**
 * Coding Debugger MCP Server
 *
 * JSON-RPC 2.0 over stdio (MCP protocol).
 * Exposes debugging memory tools: search, store, detail, status, list, patterns, outcome, read_logs.
 */

import { createInterface } from 'readline';
import { TOOLS, handleToolCall } from './tools';
import { configureLogger } from '../logger';
import { format } from 'util';

// One routing policy for the lifetime of stdio; per-call swaps race under concurrency.
const toStderr = (...args: unknown[]) => { process.stderr.write(format(...args) + '\n'); };
console.log = toStderr;
console.info = toStderr;
console.debug = toStderr;

// --- JSON-RPC transport over stdio ---

const rl = createInterface({ input: process.stdin, terminal: false });
// stdio is newline-delimited JSON-RPC: malformed input must not poison later messages.
rl.on('line', (line) => {
  if (!line.trim()) return;
  let msg: unknown;
  try { msg = JSON.parse(line); }
  catch { sendError(null, -32700, 'Parse error'); return; }
  if (!msg || typeof msg !== 'object' || Array.isArray(msg) ||
      (msg as { jsonrpc?: unknown }).jsonrpc !== '2.0' ||
      typeof (msg as { method?: unknown }).method !== 'string' ||
      ('id' in msg && typeof (msg as { id?: unknown }).id !== 'string' && typeof (msg as { id?: unknown }).id !== 'number')) {
    sendError(null, -32600, 'Invalid Request'); return;
  }
  void handleMessage(msg as Parameters<typeof handleMessage>[0]);
});

function send(msg: unknown) {
  process.stdout.write(JSON.stringify(msg) + '\n');
}

function sendResult(id: string | number, result: unknown) {
  send({ jsonrpc: '2.0', id, result });
}

function sendError(id: string | number | null, code: number, message: string) {
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

async function handleMessage(msg: {
  jsonrpc: string;
  id?: string | number;
  method: string;
  params?: unknown;
}) {
  if (msg.jsonrpc !== '2.0') return;

  const { id, method, params } = msg;
  if (id === undefined) return; // Notifications never produce responses or invoke write tools.

  try {
    switch (method) {
      case 'initialize': {
        sendResult(id!, {
          protocolVersion: ['2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25'].includes(String((params as { protocolVersion?: string })?.protocolVersion))
            ? (params as { protocolVersion: string }).protocolVersion : '2025-11-25',
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
        if (id !== undefined) sendResult(id, {});
        break;
      }

      case 'tools/list': {
        sendResult(id!, { tools: TOOLS });
        break;
      }

      case 'tools/call': {
        const { name, arguments: args } = params as {
          name: string;
          arguments?: Record<string, unknown>;
        };
        const result = await handleToolCall(name, args || {});
        sendResult(id!, result);
        break;
      }

      default: {
        if (id !== undefined) {
          sendError(id, -32601, `Method not found: ${method}`);
        }
      }
    }
  } catch (err) {
    if (id !== undefined) {
      sendError(
        id,
        -32000,
        err instanceof Error ? err.message : 'Internal error'
      );
    }
  }
}

// Initialize internal logger
configureLogger();

// Log to stderr so it doesn't interfere with the protocol
process.stderr.write('Debugger MCP server started\n');
