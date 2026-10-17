"use strict";
/**
 * Small dependency-free string similarity helpers.
 *
 * The MCP server imports retrieval at startup, so core retrieval cannot depend
 * on package dependencies that may be absent in plugin cache mirrors.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.jaroWinklerDistance = jaroWinklerDistance;
function jaroWinklerDistance(a, b) {
    const jaro = jaroDistance(a, b);
    const prefixLength = commonPrefixLength(a, b, 4);
    return jaro + prefixLength * 0.1 * (1 - jaro);
}
function jaroDistance(a, b) {
    if (a === b)
        return 1;
    if (!a || !b)
        return 0;
    const maxDistance = Math.floor(Math.max(a.length, b.length) / 2) - 1;
    const aMatches = new Array(a.length).fill(false);
    const bMatches = new Array(b.length).fill(false);
    let matches = 0;
    for (let i = 0; i < a.length; i++) {
        const start = Math.max(0, i - maxDistance);
        const end = Math.min(i + maxDistance + 1, b.length);
        for (let j = start; j < end; j++) {
            if (bMatches[j] || a[i] !== b[j])
                continue;
            aMatches[i] = true;
            bMatches[j] = true;
            matches++;
            break;
        }
    }
    if (matches === 0)
        return 0;
    const aMatchedChars = [];
    const bMatchedChars = [];
    for (let i = 0; i < a.length; i++) {
        if (aMatches[i])
            aMatchedChars.push(a[i]);
    }
    for (let i = 0; i < b.length; i++) {
        if (bMatches[i])
            bMatchedChars.push(b[i]);
    }
    let transpositions = 0;
    for (let i = 0; i < aMatchedChars.length; i++) {
        if (aMatchedChars[i] !== bMatchedChars[i])
            transpositions++;
    }
    const halfTranspositions = transpositions / 2;
    return (matches / a.length +
        matches / b.length +
        (matches - halfTranspositions) / matches) / 3;
}
function commonPrefixLength(a, b, max) {
    let length = 0;
    for (let i = 0; i < Math.min(max, a.length, b.length); i++) {
        if (a[i] !== b[i])
            break;
        length++;
    }
    return length;
}
//# sourceMappingURL=string-similarity.js.map