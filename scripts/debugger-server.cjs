#!/usr/bin/env node
// Keep existing per-project memory and explicit CLAUDE_MEMORY_* overrides compatible.
// No install, mining, provider setup or global configuration side effects.
require('../runtime/debugger/dist/src/mcp/server.js');
