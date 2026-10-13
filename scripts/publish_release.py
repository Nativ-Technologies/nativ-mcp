"""Publish matching PyPI/npm artifacts after local release verification."""

import configparser
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    version = json.loads((root / "npm/package.json").read_text())["version"]
    files = [
        root / f"dist/nativ_mcp-{version}-py3-none-any.whl",
        root / f"dist/nativ_mcp-{version}.tar.gz",
    ]
    npm_archive = root / f"dist/nativ-mcp-{version}.tgz"
    for artifact in [*files, npm_archive]:
        if not artifact.is_file():
            raise SystemExit(f"Missing release artifact: {artifact}")
    env = os.environ.copy()
    if not env.get("UV_PUBLISH_TOKEN"):
        config = configparser.ConfigParser(interpolation=None)
        config.read(Path.home() / ".pypirc")
        token = config.get("pypi", "password", fallback="").strip()
        if not token:
            raise SystemExit("Configure UV_PUBLISH_TOKEN or the [pypi] token in ~/.pypirc first.")
        env["UV_PUBLISH_TOKEN"] = token
    # Fail before uploading anything if npm login has expired.
    subprocess.run(["npm", "whoami", "--registry", "https://registry.npmjs.org"], check=True, cwd=root)
    subprocess.run([
        "uv", "publish", "--trusted-publishing", "never",
        "--check-url", "https://pypi.org/simple/", *map(str, files),
    ], check=True, cwd=root, env=env)
    # The npm launcher pins this Python release, so PyPI must be available first.
    import httpx

    response = httpx.get(f"https://pypi.org/pypi/nativ-mcp/{version}/json", timeout=30)
    response.raise_for_status()
    if len(response.json().get("urls", [])) < 2:
        raise SystemExit("Both Python release artifacts must be available before npm publishing.")
    subprocess.run([
        "npm", "publish", str(npm_archive), "--registry", "https://registry.npmjs.org", "--access", "public",
    ], check=True, cwd=root)
    print(f"Published PyPI and npm nativ-mcp {version}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
