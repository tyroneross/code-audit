import type { MemoryConfig } from './types';
export declare function withCorpusWrite<T>(config: MemoryConfig | undefined, action: () => Promise<T>): Promise<T>;
/** Publish a complete JSON file; failed writes leave the prior file readable. */
export declare function writeJsonAtomic(filename: string, value: unknown, pretty?: boolean): Promise<void>;
//# sourceMappingURL=corpus-write.d.ts.map