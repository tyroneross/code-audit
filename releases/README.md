# Local packages

Generated plugin archives live here locally and are excluded from Git. This keeps an archive from recursively including older packages. Public source archives are also available from the repository's GitHub Code menu.

From the repository root, rebuild a clean package from the current committed source:

```sh
git archive --format=tar.gz --output=releases/code-audit-0.2.0.tar.gz HEAD
```

Extract the archive into an empty folder before loading it as a plugin. It includes compiled MCP code; Node.js is required, but no dependency installation is needed for the MCP server.
