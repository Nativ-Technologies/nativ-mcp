#!/usr/bin/env python3
"""Guard immutable registry publications; never release packages or run generation."""
import argparse
import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

REGISTRY = "https://registry.modelcontextprotocol.io"
ROOT = Path(__file__).resolve().parent.parent


def read_json(url):
    request = Request(url, headers={"User-Agent": "nativ-registry-publication/1.0"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def expected_fields_match(expected, actual):
    """Allow registry-added fields while preserving every published input field."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            k in actual and expected_fields_match(v, actual[k])
            for k, v in expected.items() if k != "$schema"
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            expected_fields_match(e, a) for e, a in zip(expected, actual)
        )
    return expected == actual


def package_ownership(server, package, metadata):
    if package["registryType"] == "pypi":
        info = metadata["info"]
        marker = r"\bmcp-name:\s*" + re.escape(server["name"]) + r"(?=\s|-->|$)"
        return info["version"] == package["version"] and bool(re.search(marker, info.get("description", "")))
    if package["registryType"] == "npm":
        return metadata["version"] == package["version"] and metadata.get("mcpName") == server["name"]
    raise ValueError("Add an explicit ownership check before using a new package registry")


def registry_version(server, version):
    url = f"{REGISTRY}/v0.1/servers/{quote(server['name'], safe='')}/versions/{quote(version, safe='')}"
    try:
        return read_json(url)["server"]
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def needs_publication(server, existing):
    if existing is None:
        return True
    if not expected_fields_match(server, existing):
        raise ValueError("This version already exists with different metadata. Choose a new registry version.")
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    server = json.loads((ROOT / "server.json").read_text())
    if server["name"] != "io.github.Nativ-Technologies/nativ":
        raise ValueError("Unexpected server namespace")
    if server["repository"]["url"] != "https://github.com/Nativ-Technologies/nativ-mcp":
        raise ValueError("Unexpected source repository")

    for package in server.get("packages", []):
        name, version = quote(package["identifier"], safe=""), quote(package["version"], safe="")
        base = package["registryType"]
        url = f"https://pypi.org/pypi/{name}/{version}/json" if base == "pypi" else f"https://registry.npmjs.org/{name}/{version}"
        if not package_ownership(server, package, read_json(url)):
            raise ValueError(f"Published {base} package does not establish ownership of this server namespace")

    existing = registry_version(server, server["version"])
    publish = needs_publication(server, existing)
    if args.verify:
        if publish or not expected_fields_match(server, registry_version(server, "latest")):
            raise ValueError("Public registry does not yet expose the expected version and connection metadata")
        print(f"Verified official registry {server['name']} {server['version']}")
    else:
        if args.github_output:
            with args.github_output.open("a") as output:
                output.write(f"publish={str(publish).lower()}\n")
        print("Publication required" if publish else "Matching version already published; no duplicate submission")


if __name__ == "__main__":
    main()
