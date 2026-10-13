"""Create a new Cloud Run mapping without replacing existing domain routes."""

import json
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

import certifi


project, region, service, domain = sys.argv[1:]
access = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
base = f"https://{region}-run.googleapis.com/apis/domains.cloudrun.com/v1/namespaces/{project}/domainmappings"
context = ssl.create_default_context(cafile=certifi.where())


def call(url, payload=None):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode() if payload else None,
        headers={"Authorization": "Bearer " + access, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, context=context, timeout=30) as response:
        return json.load(response)


try:
    mapping = call(base + "/" + domain)
except urllib.error.HTTPError as exc:
    if exc.code != 404:
        raise
    mapping = call(base, {
        "apiVersion": "domains.cloudrun.com/v1", "kind": "DomainMapping",
        "metadata": {"name": domain, "namespace": project},
        "spec": {"routeName": service},
    })
if mapping["spec"]["routeName"] != service:
    raise RuntimeError("Domain already routes to a different service; no changes made.")
print(json.dumps({"domain": domain, "conditions": mapping.get("status", {}).get("conditions", []), "dns": mapping.get("status", {}).get("resourceRecords", [])}, indent=2))
