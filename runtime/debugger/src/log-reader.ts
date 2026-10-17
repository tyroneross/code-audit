/**
 * Log Reader
 *
 * Powers the `read_logs` MCP tool. Reads logs from:
 * 1. Debugger's own operation logs (.claude-code-debugger/logs/)
 * 2. Project logs — auto-discovers common log locations
 * 3. Explicit file paths
 *
 * Supports JSONL (structured) and plain text (regex-based extraction).
 */

import fs from 'fs/promises';
import { constants } from 'fs';
import path from 'path';
import os from 'os';
import { getLogPaths } from './config';

// ============================================================================
// TYPES
// ============================================================================

export type LogSource = 'debugger' | 'project' | 'path';
export type LogSeverity = 'debug' | 'info' | 'warn' | 'error' | 'fatal';

export interface LogReaderOptions {
  source: LogSource;
  path?: string;           // Required when source = 'path'
  since?: string;          // ISO 8601 or relative ('1h', '30m', '7d')
  until?: string;          // ISO 8601 or relative
  level?: LogSeverity;     // Minimum severity
  keyword?: string;        // Search filter
  limit?: number;          // Max entries (default 50)
}

export interface LogItem {
  timestamp: string;       // ISO 8601; inspection fallback is explicitly marked invalid
  timestamp_valid?: boolean; // false means the event time was absent or invalid
  level: LogSeverity;
  message: string;
  source_file: string;
  raw?: string;            // Original line for unstructured logs
}

export interface LogReaderResult {
  entries: LogItem[];
  entries_skipped?: number;
  files_read: string[];
  files_skipped?: Array<{ path: string; reason: string }>;
  total_matched: number;
  truncated: boolean;
}

// ============================================================================
// MAIN READER
// ============================================================================

/**
 * Read logs from the specified source.
 */
export async function readProjectLogs(options: LogReaderOptions): Promise<LogReaderResult> {
  const workingRoot = await fs.realpath(process.cwd());
  const homeRoot = await fs.realpath(os.homedir()).catch(() => path.resolve(os.homedir()));
  const homeRelative = path.relative(workingRoot, homeRoot);
  const containsHome = homeRelative === '' || (!path.isAbsolute(homeRelative) && homeRelative !== '..' && !homeRelative.startsWith('..' + path.sep));
  if (containsHome || workingRoot === path.parse(workingRoot).root) {
    throw new Error('Log inspection requires a specific project working directory, not home, an ancestor of home, or filesystem root');
  }
  const limit = options.limit ?? 50;
  if (!Number.isInteger(limit) || limit < 1 || limit > 500) throw new Error('limit must be an integer from 1 to 500');
  const sinceTs = options.since ? parseRelativeTime(options.since) : undefined;
  const untilTs = options.until ? parseRelativeTime(options.until) : undefined;
  const minLevel = options.level ? SEVERITY_ORDER[options.level] : 0;
  const keyword = options.keyword?.toLowerCase();

  let files: string[] = [];

  switch (options.source) {
    case 'debugger':
      files = await getDebuggerLogFiles();
      break;
    case 'project':
      files = await discoverProjectLogFiles();
      break;
    case 'path':
      if (!options.path) throw new Error('path is required when source is "path"');
      files = [options.path];
      break;
  }

  const allEntries: LogItem[] = [];
  const filesRead: string[] = [];
  const filesSkipped: Array<{ path: string; reason: string }> = [];
  // Conservative interactive inspection budget; larger archives need project tooling.
  for (const file of files.slice(16)) filesSkipped.push({ path: file, reason: '16-file inspection limit' });
  for (const file of files.slice(0, 16)) {
    try {
      const entries = await readLogFile(file);
      allEntries.push(...entries);
      filesRead.push(file);
    } catch (error) {
      if (options.source === 'path') throw error;
      filesSkipped.push({ path: file, reason: error instanceof Error ? error.message : 'unreadable log' });
    }
  }

  // Filter
  let entriesSkipped = 0;
  const filtered = allEntries.filter(entry => {
    if ((sinceTs !== undefined || untilTs !== undefined) && entry.timestamp_valid === false) { entriesSkipped++; return false; }
    if (sinceTs && new Date(entry.timestamp).getTime() < sinceTs) return false;
    if (untilTs && new Date(entry.timestamp).getTime() > untilTs) return false;
    if (SEVERITY_ORDER[entry.level] < minLevel) return false;
    if (keyword && !entry.message.toLowerCase().includes(keyword)) return false;
    return true;
  });

  // Sort by timestamp descending (most recent first)
  filtered.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

  const truncated = filtered.length > limit;

  return {
    entries: filtered.slice(0, limit),
    entries_skipped: entriesSkipped,
    files_read: filesRead,
    files_skipped: filesSkipped,
    total_matched: filtered.length,
    truncated,
  };
}

// ============================================================================
// FILE DISCOVERY
// ============================================================================

const SEVERITY_ORDER: Record<string, number> = {
  debug: 0, info: 1, warn: 2, warning: 2, error: 3, fatal: 4,
};

/**
 * Get debugger's own log files.
 */
async function getDebuggerLogFiles(): Promise<string[]> {
  const paths = getLogPaths();
  const files: string[] = [];

  for (const logFile of [paths.operations, paths.errors]) {
    try {
      await fs.access(logFile);
      files.push(logFile);
    } catch {
      // Doesn't exist yet
    }
  }

  return files;
}

/**
 * Auto-discover project log files in common locations.
 */
async function discoverProjectLogFiles(): Promise<string[]> {
  const cwd = process.cwd();
  const discovered: string[] = [];

  // Common log directories
  const logDirs = ['logs', 'log', '.logs'];
  for (const dir of logDirs) {
    const dirPath = path.join(cwd, dir);
    try {
      const entries = await fs.readdir(dirPath);
      for (const entry of entries) {
        if (entry.endsWith('.log') || entry.endsWith('.jsonl')) {
          discovered.push(path.join(dirPath, entry));
        }
      }
    } catch {
      // Dir doesn't exist
    }
  }

  // Common log files in project root
  const rootLogs = [
    'npm-debug.log',
    'yarn-error.log',
    'pnpm-debug.log',
    'lerna-debug.log',
  ];
  for (const logFile of rootLogs) {
    const filePath = path.join(cwd, logFile);
    try {
      await fs.access(filePath);
      discovered.push(filePath);
    } catch {
      // Doesn't exist
    }
  }

  // Next.js trace
  const nextTrace = path.join(cwd, '.next', 'trace');
  try {
    await fs.access(nextTrace);
    discovered.push(nextTrace);
  } catch {
    // Not a Next.js project or trace not enabled
  }

  // Also check debugger's own logs
  const debuggerFiles = await getDebuggerLogFiles();
  discovered.push(...debuggerFiles);

  return discovered;
}

// ============================================================================
// FILE PARSING
// ============================================================================

/**
 * Read and parse a log file. Auto-detects format.
 */
async function readLogFile(filePath: string): Promise<LogItem[]> {
  const root = await fs.realpath(process.cwd());
  const resolved = await fs.realpath(path.resolve(filePath));
  const relative = path.relative(root, resolved);
  if (relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) {
    throw new Error('Log path must remain inside the current project');
  }
  // 1 MiB bounds inspection memory; use project tooling for larger archives.
  const maxBytes = 1024 * 1024;
  // Reject FIFO/device paths before opening; nonblocking open also handles a path-swap race.
  if (!(await fs.stat(resolved)).isFile()) throw new Error('Log path must identify a regular file');
  const handle = await fs.open(resolved, constants.O_RDONLY | (constants.O_NOFOLLOW || 0) | (constants.O_NONBLOCK || 0));
  let content: string;
  try {
    const stat = await handle.stat();
    if (!stat.isFile()) throw new Error('Log path must identify a regular file');
    if (stat.size > maxBytes) throw new Error('Log exceeds the 1 MiB inspection limit');
    const buffer = Buffer.alloc(maxBytes + 1);
    let offset = 0;
    while (offset < buffer.length) {
      const { bytesRead } = await handle.read(buffer, offset, buffer.length - offset, offset);
      if (!bytesRead) break;
      offset += bytesRead;
    }
    if (offset > maxBytes) throw new Error('Log exceeds the 1 MiB inspection limit');
    content = buffer.subarray(0, offset).toString('utf8');
  } finally { await handle.close(); }
  const lines = content.trim().split('\n').filter(Boolean);

  if (lines.length === 0) return [];

  // Try JSONL first
  const firstLine = lines[0];
  try {
    JSON.parse(firstLine);
    return parseJsonlLines(lines, filePath);
  } catch {
    // Not JSONL, try plain text
  }

  return parseTextLines(lines, filePath);
}

/**
 * Parse JSONL log lines (structured format).
 */
function parseJsonlLines(lines: string[], sourceFile: string): LogItem[] {
  const entries: LogItem[] = [];

  for (const line of lines) {
    try {
      const obj = JSON.parse(line);

      // Support common structured log formats
      const { timestamp, valid } = safeEventTime(obj.ts ?? obj.timestamp ?? obj.time);

      const level = normalizeLevel(
        obj.level || obj.severity || obj.lvl || 'info'
      );

      const message = obj.msg || obj.message || obj.op
        ? `${obj.op || ''}${obj.msg || obj.message || ''}${obj.error?.message ? ` — ${obj.error.message}` : ''}`.trim()
        : JSON.stringify(obj).slice(0, 200);

      entries.push({
        timestamp,
        timestamp_valid: valid,
        level,
        message,
        source_file: sourceFile,
      });
    } catch {
      // Skip malformed lines
    }
  }

  return entries;
}

/**
 * Parse plain text log lines using regex patterns.
 */
function parseTextLines(lines: string[], sourceFile: string): LogItem[] {
  const entries: LogItem[] = [];

  // Common patterns:
  // [2024-01-15T10:30:00.000Z] ERROR something happened
  // 2024-01-15 10:30:00 [ERROR] something happened
  // ERROR: something happened
  const timestampPattern = /(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)/;
  const levelPattern = /\b(debug|info|warn(?:ing)?|error|fatal|DEBU[G]?|INFO|WARN(?:ING)?|ERROR|FATAL)\b/i;

  for (const line of lines) {
    const tsMatch = line.match(timestampPattern);
    const lvlMatch = line.match(levelPattern);

    const { timestamp, valid } = safeEventTime(tsMatch?.[1]);

    const level = lvlMatch ? normalizeLevel(lvlMatch[1]) : 'info';

    // Remove timestamp and level from message
    let message = line;
    if (tsMatch) message = message.replace(tsMatch[0], '');
    if (lvlMatch) message = message.replace(lvlMatch[0], '');
    message = message.replace(/^\s*[\[\]():|-]+\s*/, '').trim();

    if (message) {
      entries.push({
        timestamp,
        timestamp_valid: valid,
        level,
        message,
        source_file: sourceFile,
        raw: line,
      });
    }
  }

  return entries;
}

// ============================================================================
// HELPERS
// ============================================================================

/** Invalid event timestamps do not make the rest of a file unreadable. */
function safeEventTime(value: unknown): { timestamp: string; valid: boolean } {
  const parsed = value === undefined || value === null ? NaN : new Date(value as string | number).getTime();
  const valid = Number.isFinite(parsed);
  return { timestamp: new Date(valid ? parsed : Date.now()).toISOString(), valid };
}

/**
 * Normalize log level strings to standard severity.
 */
function normalizeLevel(level: string): LogSeverity {
  const l = level.toLowerCase();
  if (l === 'fatal') return 'fatal';
  if (l === 'error' || l === 'err') return 'error';
  if (l === 'warn' || l === 'warning') return 'warn';
  if (l === 'info') return 'info';
  if (l === 'debug' || l === 'trace' || l === 'verbose') return 'debug';
  return 'info';
}

/**
 * Parse relative time strings ('1h', '30m', '7d') or ISO 8601 to timestamp.
 */
function parseRelativeTime(input: string): number {
  // Try ISO 8601 first
  const date = new Date(input);
  if (!isNaN(date.getTime())) return date.getTime();

  // Parse relative
  const match = input.match(/^(\d+)\s*(s|m|h|d|w)$/);
  if (!match) throw new Error(`Invalid time format: ${input}. Use ISO 8601 or relative (1h, 30m, 7d)`);

  const value = parseInt(match[1], 10);
  const unit = match[2];

  const multipliers: Record<string, number> = {
    s: 1000,
    m: 60 * 1000,
    h: 60 * 60 * 1000,
    d: 24 * 60 * 60 * 1000,
    w: 7 * 24 * 60 * 60 * 1000,
  };

  return Date.now() - value * multipliers[unit];
}
