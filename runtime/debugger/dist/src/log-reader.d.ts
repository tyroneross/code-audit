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
export type LogSource = 'debugger' | 'project' | 'path';
export type LogSeverity = 'debug' | 'info' | 'warn' | 'error' | 'fatal';
export interface LogReaderOptions {
    source: LogSource;
    path?: string;
    since?: string;
    until?: string;
    level?: LogSeverity;
    keyword?: string;
    limit?: number;
}
export interface LogItem {
    timestamp: string;
    timestamp_valid?: boolean;
    level: LogSeverity;
    message: string;
    source_file: string;
    raw?: string;
}
export interface LogReaderResult {
    entries: LogItem[];
    entries_skipped?: number;
    files_read: string[];
    files_skipped?: Array<{
        path: string;
        reason: string;
    }>;
    total_matched: number;
    truncated: boolean;
}
/**
 * Read logs from the specified source.
 */
export declare function readProjectLogs(options: LogReaderOptions): Promise<LogReaderResult>;
//# sourceMappingURL=log-reader.d.ts.map