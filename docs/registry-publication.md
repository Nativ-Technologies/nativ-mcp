# Official MCP registry publication

`server.json` is the reviewed public metadata. The GitHub Actions workflow publishes
it after a matching change reaches `main`, or through a manual run on `main`.
It uses the repository's short-lived GitHub OIDC identity. No personal token,
package publishing credential or Nativ API key is needed by the workflow.

Before publication it checks the already-released package's namespace ownership,
validates metadata with the official publisher and detects an existing matching
version. A changed record cannot overwrite the same immutable version. Afterward
it verifies the exact version and latest public record, including the connection
URL and required API-key header. It never releases npm/PyPI packages or invokes
localisation operations.

The publisher is pinned to v1.8.8 with its release archive SHA-256. The checkout
action is pinned to the checked v5 commit. Review both pins when upgrading.

## Published package scope

The 9 November 2026 update lists verified PyPI `nativ-mcp` 0.5.0 and the hosted
Streamable HTTP endpoint. The existing npm 0.5.0 wrapper remains available through
the documented `npx` setup. Its published metadata lacks the `mcpName` property
required by the official registry, so it is omitted from this registry record.
Do not advertise a package whose ownership verification will fail. A future npm
release can add that property and be included in a new registry metadata version;
keep the wrapper's pinned Python version aligned with an actually published package.

This updates discovery metadata, not the running MCP service or client configs.
Previously published registry versions are retained.

References checked 9 November 2026:

- https://modelcontextprotocol.io/registry/github-actions
- https://modelcontextprotocol.io/registry/authentication
- https://modelcontextprotocol.io/registry/package-types
- https://github.com/modelcontextprotocol/registry/releases/tag/v1.8.8
