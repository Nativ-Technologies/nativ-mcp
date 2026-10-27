# ChatGPT plugin release

The public-directory package is in `plugin/`. Build it with:

```sh
python scripts/package_plugin.py /absolute/path/nativ-chatgpt-plugin-1.0.0.zip
```

The existing API-key `/mcp` endpoint retains its original 51-tool catalogue.
The new `/chatgpt/mcp` endpoint uses a focused seven-tool catalogue and OAuth.
It does not accept a manually supplied Nativ API key.

## Deployment order

1. Apply `nativ-backend/migrations/20261026_mcp_oauth_pkce.sql` before deploying backend code. The four nullable columns are additive; legacy GPT Actions grants retain their existing semantics.
2. Apply `nativ-backend/migrations/20261027_mcp_oauth_member.sql`, then deploy the backend member-binding update. Plugin users need current admin or maintainer permissions. Missing, moved, demoted or MFA-protected members fail closed. Existing resource-bound grants must reconnect. Deploy the backend OAuth changes. Public client ID `nativ-chatgpt-plugin` requires S256 PKCE, the exact resource `https://mcp.usenativ.com/chatgpt/mcp`, and scope `nativ:localize`. This client has no secret. The legacy GPT Actions client still requires its existing secret.
3. Deploy the MCP service with its existing API URL, storage bucket, signing account, public URL and host allowlists. No new external runtime dependency is needed.
4. Verify public resource discovery, authorization-server discovery, an unauthenticated 401 challenge, then a real authorization-code exchange and tool call with a dedicated reviewer account.
5. Upload the ZIP through OpenAI Platform Plugins under Nativ. Complete publisher/domain verification and reviewer information. Set `NATIV_OPENAI_DOMAIN_CHALLENGE` on the MCP service to the exact challenge value shown by the portal. It is served verbatim from `/.well-known/openai-apps-challenge`.
6. Check the callback URL shown by the portal. The backend accepts the stable `https://chatgpt.com/connector_platform_oauth_redirect` by default. If the portal uses a connection-specific callback, add that exact URL to `MCP_OAUTH_REDIRECT_URIS` (comma separated) before testing. Do not allow arbitrary redirects.
7. Run the five positive and three negative scenarios in the package using the reviewer account. Supply an accessible recording of the real workflow and keep the reviewer account available for future reviews. The screenshot in this package is explicitly labelled as an interface preview with fictional sample data.
8. Submit once required checks pass. Review attestations and legal agreements require the publisher's approval. Publish and market availability after approval and live verification.

## Boundaries

- The review component receives structured results through MCP Apps and also supports ChatGPT's tool-output compatibility field. It renders text safely and never treats reference content as instructions.
- Saving memory requires explicit approval of the exact source and translated wording. Generation does not imply approval.
- The resource-bound OAuth grant permits only the plugin's localisation, context and memory API paths. It cannot administer accounts, change roles, clone voices or delete shared memory.
- Media tools require accessible HTTPS image URLs. Private ChatGPT attachment handoff is not implemented. Hosted files use the existing bounded downloader; outputs retain the existing signed-link expiry.
- Image generation and text localisation can use the connected account's Nativ credits. The plugin does not process payments.
- Reviewer credentials are entered separately in the portal and must never be put in the ZIP, screenshots, source control, application logs or public launch material.

## Verification

Run the complete MCP unittest suite against the production lockfile's MCP version (2.0.0), and the backend `test_mcp_oauth.py` HTTP/security regression suite. Mocked tests do not replace the required real ChatGPT reviewer scenarios.


## Reviewer walkthrough

A captioned walkthrough of actual ChatGPT Work UI captures, using only the fictional Field Notes workspace, is available at https://www.usenativ.com/review/chatgpt/. The video is a shortened sequence rather than a continuous screen recording. It discloses the observed initial card-loading retry, account requirements and current image input limits. The package screenshot is an actual review-card capture, not a mock interface. Reviewer credentials are supplied privately in the submission portal and must never be committed.
