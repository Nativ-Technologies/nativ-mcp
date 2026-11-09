import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location("registry_metadata", Path(__file__).resolve().parents[1] / "scripts/registry_metadata.py")
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)


class RegistryPublicationGuards(unittest.TestCase):
    def setUp(self):
        self.server = {"name": "io.github.Nativ-Technologies/nativ", "version": "0.5.0", "remotes": [{"url": "https://mcp.usenativ.com/mcp"}]}

    def test_matching_version_is_not_republished(self):
        self.assertFalse(registry.needs_publication(self.server, {**self.server, "title": "Registry enrichment"}))

    def test_changed_endpoint_cannot_overwrite_a_version(self):
        changed = {**self.server, "remotes": [{"url": "https://example.com/mcp"}]}
        with self.assertRaises(ValueError):
            registry.needs_publication(self.server, changed)

    def test_registry_can_omit_only_default_false_optional_flags(self):
        expected = {"name": "NATIV_API_URL", "isRequired": False, "isSecret": False}
        self.assertTrue(registry.expected_fields_match(expected, {"name": "NATIV_API_URL"}))
        self.assertFalse(registry.expected_fields_match({"isRequired": True}, {}))
        self.assertFalse(registry.expected_fields_match({"isSecret": True}, {}))
        self.assertFalse(registry.expected_fields_match({"other": False}, {}))

    def test_only_a_missing_version_allows_first_publication(self):
        self.assertTrue(registry.needs_publication(self.server, None))
        with patch.object(registry, "read_json", side_effect=HTTPError("url", 404, "missing", {}, None)):
            self.assertIsNone(registry.registry_version(self.server, "0.5.0"))
        with patch.object(registry, "read_json", side_effect=HTTPError("url", 503, "unavailable", {}, None)):
            with self.assertRaises(HTTPError):
                registry.registry_version(self.server, "0.5.0")

    def test_packages_must_prove_exact_namespace_ownership(self):
        package = {"registryType": "pypi", "version": "0.5.0"}
        good = {"info": {"version": "0.5.0", "description": "mcp-name: io.github.Nativ-Technologies/nativ"}}
        self.assertTrue(registry.package_ownership(self.server, package, good))
        self.assertFalse(registry.package_ownership(self.server, package, {"info": {"version": "0.5.0", "description": "mcp-name: io.github.someone-else/nativ"}}))
        self.assertFalse(registry.package_ownership(self.server, package, {"info": {"version": "0.5.0", "description": "mcp-name: io.github.Nativ-Technologies/nativ-something-else"}}))
        self.assertFalse(registry.package_ownership(self.server, {"registryType": "npm", "version": "0.5.0"}, {"version": "0.5.0"}))
