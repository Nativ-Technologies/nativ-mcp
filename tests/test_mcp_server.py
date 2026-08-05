import unittest

from mcp import Client
from mcp.server import MCPServer

from nativ_mcp.server import mcp


class MCPServerCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_loads_and_registers_capabilities(self) -> None:
        self.assertIsInstance(mcp, MCPServer)

        async with Client(mcp) as client:
            self.assertTrue((await client.list_tools()).tools)
            self.assertTrue((await client.list_resources()).resources)
            self.assertTrue((await client.list_prompts()).prompts)


if __name__ == "__main__":
    unittest.main()
