"""Descriptions are additive: existing calls keep exactly the same contracts."""
import json
import unittest
from pathlib import Path
from mcp import Client
from nativ_mcp.server import mcp
from nativ_mcp.chatgpt import create_plugin_server
from nativ_mcp.json_api import openapi_schema


def without_descriptions(value):
    if isinstance(value, dict):
        return {k: without_descriptions(v) for k, v in value.items() if k != 'description'}
    if isinstance(value, list):
        return [without_descriptions(v) for v in value]
    return value


class ParameterDescriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_parameter_documented_without_contract_changes(self):
        baseline = json.loads((Path(__file__).parent / 'fixtures/parameter-schema-before-descriptions.json').read_text())
        for name, server in [('mcp', mcp), ('plugin', create_plugin_server())]:
            async with Client(server) as client:
                tools = (await client.list_tools()).tools
            actual = [t.model_dump(mode='json', exclude_none=True) for t in tools]
            self.assertEqual(without_descriptions(actual), baseline[name])
            for tool in tools:
                for parameter, schema in tool.input_schema.get('properties', {}).items():
                    self.assertTrue(schema.get('description', '').strip(), (tool.name, parameter))
            if name == 'mcp':
                schema = openapi_schema(tools, 'https://mcp.usenativ.com')
                for path, item in schema['paths'].items():
                    props = item['post']['requestBody']['content']['application/json']['schema']['properties']
                    for parameter, prop in props.items():
                        self.assertTrue(prop.get('description', '').strip(), (path, parameter))
