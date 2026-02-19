#!/usr/bin/env node

const { spawn, execSync, execFileSync } = require("child_process");
const { existsSync } = require("fs");
const { join } = require("path");

const PYPI_PACKAGE = "nativ-mcp";
const UV_INSTALL_URL = "https://astral.sh/uv/install.sh";

function findInPath(cmd) {
  try {
    const out = execFileSync("which", [cmd], {
      encoding: "utf8",
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
    return out || null;
  } catch {
    return null;
  }
}

function resolveCmd(cmd) {
  const direct = findInPath(cmd);
  if (direct) return direct;

  const home = process.env.HOME || "";
  const candidates = [
    join(home, ".local", "bin", cmd),
    join(home, ".cargo", "bin", cmd),
    "/opt/homebrew/bin/" + cmd,
    "/usr/local/bin/" + cmd,
  ];
  for (const p of candidates) {
    if (existsSync(p)) return p;
  }
  return null;
}

function installUv() {
  process.stderr.write("nativ-mcp: uv not found — installing automatically...\n");
  try {
    execSync(`curl -LsSf ${UV_INSTALL_URL} | sh`, {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, UV_UNMANAGED_INSTALL: "" },
    });
  } catch (err) {
    process.stderr.write(
      "Failed to auto-install uv: " + err.message + "\n" +
        "Install manually: curl -LsSf https://astral.sh/uv/install.sh | sh\n"
    );
    process.exit(1);
  }

  const uvx = resolveCmd("uvx");
  if (uvx) return uvx;

  const uv = resolveCmd("uv");
  if (uv) return uv;

  process.stderr.write(
    "uv was installed but could not be found.\n" +
      "Try restarting your terminal and running again.\n"
  );
  process.exit(1);
}

function run(cmd, args) {
  const child = spawn(cmd, args, {
    stdio: "inherit",
    env: process.env,
  });
  child.on("exit", (code) => process.exit(code ?? 1));
  child.on("error", (err) => {
    process.stderr.write(`Failed to start ${cmd}: ${err.message}\n`);
    process.exit(1);
  });
}

let uvx = resolveCmd("uvx");
if (uvx) {
  run(uvx, [PYPI_PACKAGE]);
} else {
  let uv = resolveCmd("uv");
  if (uv) {
    run(uv, ["tool", "run", PYPI_PACKAGE]);
  } else {
    const resolved = installUv();
    if (resolved.endsWith("uvx")) {
      run(resolved, [PYPI_PACKAGE]);
    } else {
      run(resolved, ["tool", "run", PYPI_PACKAGE]);
    }
  }
}
