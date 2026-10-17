/**
 * Small dependency-free string similarity helpers.
 *
 * The MCP server imports retrieval at startup, so core retrieval cannot depend
 * on package dependencies that may be absent in plugin cache mirrors.
 */
export declare function jaroWinklerDistance(a: string, b: string): number;
//# sourceMappingURL=string-similarity.d.ts.map