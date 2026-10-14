# Hosted Nativ MCP

The hosted service exposes the existing tools, resources, and prompts at `/mcp`
over Streamable HTTP. It validates the caller's Nativ API key on every request
and forwards that caller's key to the REST API. It never uses `NATIV_API_KEY`
from the server environment for hosted calls.

## Connect

Use an MCP client that supports a remote Streamable HTTP URL and custom headers:

```json
{
  "mcpServers": {
    "nativ": {
      "url": "https://mcp.usenativ.com/mcp",
      "headers": {
        "X-API-Key": "nativ_your_api_key_here"
      }
    }
  }
}
```

`Authorization: Bearer nativ_your_api_key_here` is also accepted when a client
supports manually configured bearer credentials. Supply only one credential
header. OAuth discovery and interactive sign-in are not implemented; clients
requiring those flows need additional authentication support.

For REST connector builders, `/openapi.json` serves a focused OpenAPI 3.1 schema
for the localization API, including its `X-API-Key` security scheme and
`https://api.usenativ.com` server URL. It describes REST operations, not the MCP
wire protocol. REST media operations use multipart uploads.

## JSON-only API connectors

For clients that only support `application/json`, import
`https://mcp.usenativ.com/json-openapi.json`. It describes 21 new HTTP endpoints,
one per existing tool, under `/tools/{tool_name}`. These use the same `X-API-Key`
header and account permissions as hosted MCP.

For example, transcribe an audio/video URL without uploading multipart data:

```http
POST /tools/transcribe_audio
Content-Type: application/json
X-API-Key: nativ_your_api_key_here
```

```json
{
  "file_path": "https://your-storage.example.com/video.mp4",
  "source_language_code": "en"
}
```

For an image localization call, use `/tools/localize_image` with an HTTPS
`image_path`, `target_language_code`, and a native JSON `replacements` array:

```json
{
  "image_path": "https://your-storage.example.com/banner.png",
  "target_language_code": "fr",
  "replacements": [{"original": "Hello", "translated": "Bonjour"}]
}
```

Responses are JSON objects containing `tool`, `text`, `data`, and `artifacts`.
Generated files appear in `artifacts` with `url`, `filename`, `mime_type`, and
`expires_in_seconds` (3600). A client can display or forward those URLs without
processing file bytes. Reading or understanding the media still requires the
client's own image/video capabilities.

The JSON adapter accepts a native array for `synthesize_audio.segments` as well.
Existing MCP calls continue to use their original string arguments for
`replacements` and `segments`. The original `/openapi.json` schema and backend
REST endpoints are unchanged. JSON adapter bodies are limited to 1 MiB; media
uses HTTPS URLs rather than embedded base64.

## Media

Hosted tools take a public HTTPS URL in their existing `file_path`, `image_path`,
`audio_path`, `video_path`, `subtitle_path`, or `glossary_path` argument. Presigned
S3/GCS HTTPS URLs work while valid. `s3://`, `gs://`, HTTP, local paths, private
networks, and metadata endpoints are rejected. Downloads are limited to 100 MiB,
120 seconds, and five redirects; every hop is checked and pinned to a public IP.
Media hosts never receive the caller's Nativ key.

Hosted output paths are filename hints. Image/audio/video/subtitle outputs are
stored privately in GCS and returned as signed download URLs valid for one hour.
The bucket lifecycle deletes objects after one day (Cloud Storage processes
lifecycle deletion asynchronously). URLs are bearer capabilities; share them
only with intended recipients. No generated files depend on a particular Cloud
Run instance. The stdio transport continues to read/write local files.

## Deployment

Deploy the backend with support for `origin=mcp_batch_translation` before
deploying the MCP batch update. `translate_batch` now submits texts together
in groups of up to 32 segments within the API's 50,000-character text limit,
instead of issuing a separate translation request for every segment. The MCP
batch path uses the account's selected model, TM, and style guides. Existing
tool arguments and successful response formatting are preserved.

Backend MCP batches have a 180-second processing deadline, and the MCP tool
has a 240-second overall deadline. Incomplete results and timeouts are MCP
tool errors (HTTP 502 through the JSON adapter); they are not successful
translation strings. There are no automatic batch retries. For multi-chunk
inputs, earlier completed chunks may already have been billed when a later
chunk fails. Check usage before repeating a failed request.

To investigate latency, compare identical inputs, tool arguments, API key,
and backend URL. Logs include `mcp_batch_start` / `mcp_batch_complete`,
`mcp_translation_tm`, and `translation_model` elapsed times without source
text or credentials. Check Cloud Run CPU, memory, and request concurrency
alongside these timings before increasing instance size.

```bash
uv sync --extra hosted
uv run python -m unittest discover -s tests
bash deploy.sh
```

After deployment, set `NATIV_API_KEY` for a test account and verify the service:

```bash
uv run --extra hosted python scripts/smoke_hosted.py https://mcp.usenativ.com/mcp --media
```

`--media` generates a short unbilled voice preview to verify output storage,
URL signing, and download. Omit it to run only read-only checks.

The script creates a dedicated `nativ-mcp` Cloud Run service and service account,
a private output bucket, and the account permissions needed to write outputs
and sign URLs using IAM. It does not deploy the Nativ backend. Cloud Run accepts
public traffic; application middleware authenticates MCP requests. `/health`
and both OpenAPI schema routes are public. The service uses a stateless transport and JSON
responses, so requests can go to any replica. Server-initiated sampling,
elicitation, and streamed progress are not used by the current Nativ tools.

Set `MCP_PROJECT`, `MCP_REGION`, `MCP_SERVICE`, `MCP_BUCKET`, or `MCP_PUBLIC_URL`
to override deployment defaults. `NATIV_MCP_ALLOWED_HOSTS` contains additional
exact hostnames; `NATIV_MCP_ALLOWED_ORIGINS` contains comma-separated browser
origins. Server-side clients do not need CORS. Add the intended browser client's
origin explicitly if it sends an Origin header.

Cloud Run deployment returns a working `run.app` URL. Configure custom-domain
routing and DNS before sharing `https://mcp.usenativ.com/mcp` as live. For a
production custom domain, an HTTPS load balancer is the Google-recommended
option. This project already uses Cloud Run domain mappings for its API;
`deploy/configure_domain.py` can add the MCP subdomain using the same pattern:

```bash
uv run --extra hosted python deploy/configure_domain.py nativ-backend us-central1 nativ-mcp mcp.usenativ.com
```

The script prints the required DNS records and refuses to replace an existing
mapping to a different service. Cloud Run domain mappings remain preview. The
same routing can expose `/mcp` under `api.usenativ.com` if its ingress is moved
to a load balancer with path routing.

Refresh the bundled REST schema after changing backend API contracts:

```bash
curl --fail https://api.usenativ.com/openapi.json -o /tmp/nativ-openapi.json
python scripts/export_openapi.py /tmp/nativ-openapi.json
```
