"""Export the REST operations used by MCP for API connector builders."""

import json
import re
import sys
from pathlib import Path


def references(value):
    if isinstance(value, dict):
        if "$ref" in value:
            yield value["$ref"].split("/")[-1]
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def export(source):
    root = Path(__file__).resolve().parents[1]
    paths = set()
    for filename in ("client.py", "workflow_tools.py"):
        paths.update(re.findall(r'"(/[^"\s]+)"', (root / "src/nativ_mcp" / filename).read_text()))
    selected = {}
    for path in sorted(paths):
        if path not in source["paths"]:
            raise ValueError(f"REST schema is missing {path}")
        selected[path] = source["paths"][path]
        for operation in selected[path].values():
            if isinstance(operation, dict) and "operationId" in operation:
                operation["security"] = [{"NativAPIKey": []}]
    pending = list(references(selected))
    schemas = {}
    while pending:
        name = pending.pop()
        if name not in schemas:
            schemas[name] = source["components"]["schemas"][name]
            pending.extend(references(schemas[name]))
    return {
        "openapi": source["openapi"],
        "info": {"title": "Nativ Localization API", "version": "0.5.0", "description": "REST operations used by Nativ MCP. Media requests use multipart file uploads; responses may include base64 media."},
        "servers": [{"url": "https://api.usenativ.com"}],
        "security": [{"NativAPIKey": []}],
        "paths": selected,
        "components": {"securitySchemes": {"NativAPIKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}, "schemas": schemas},
    }


if __name__ == "__main__":
    schema = export(json.loads(Path(sys.argv[1]).read_text()))
    target = Path(__file__).resolve().parents[1] / "src/nativ_mcp/rest-openapi.json"
    target.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"Exported {len(schema['paths'])} REST paths to {target}")
