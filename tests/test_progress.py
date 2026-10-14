import asyncio
import os
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import httpx2
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from nativ_mcp.hosted import create_app
from nativ_mcp.progress import tool_progress
from nativ_mcp.server import mcp


class ProgressTests(unittest.IsolatedAsyncioTestCase):
    async def check_progress(self, client):
        processing = asyncio.Event()
        progress_received = asyncio.Event()
        release = asyncio.Event()
        updates = []

        async def localize(*args, **kwargs):
            processing.set()
            await release.wait()
            return {'translated_text': 'স্বাগতম'}

        async def on_progress(progress, total, message):
            updates.append((progress, total, message))
            if progress > .01:
                progress_received.set()

        with patch('nativ_mcp.progress.PROGRESS_INTERVAL_SECONDS', .03), patch(
            'nativ_mcp.client.NativClient.translate', localize,
        ):
            task = asyncio.create_task(client.call_tool('translate', {
                'text': 'Welcome', 'target_language': 'Bengali',
            }, progress_callback=on_progress))
            try:
                await asyncio.wait_for(processing.wait(), 3)
                await asyncio.wait_for(progress_received.wait(), 3)
                self.assertFalse(task.done(), 'Progress must arrive before localization finishes')
                release.set()
                result = await asyncio.wait_for(task, 3)
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(result.is_error)
        self.assertIn('স্বাগতম', result.content[0].text)
        self.assertTrue(all(total is None for _, total, _ in updates))
        values = [progress for progress, _, _ in updates]
        self.assertEqual(values, sorted(values))

    async def test_local_progress_arrives_before_result(self):
        with patch.dict(os.environ, {'NATIV_API_KEY': 'nativ_test'}):
            async with Client(mcp) as client:
                await self.check_progress(client)

    async def test_hosted_progress_streams_before_result(self):
        app = create_app(artifact_store=SimpleNamespace(), api_transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={}),
        ))
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        sock.listen()
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
        server_task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async def started():
                while not server.started:
                    if server_task.done():
                        await server_task
                    await asyncio.sleep(.01)
            await asyncio.wait_for(started(), 3)
            async with httpx2.AsyncClient(headers={'X-API-Key': 'nativ_test'}, timeout=5) as http:
                async with Client(streamable_http_client(f'http://127.0.0.1:{port}/mcp', http_client=http)) as client:
                    await self.check_progress(client)
        finally:
            server.should_exit = True
            await asyncio.wait_for(server_task, 5)
            sock.close()

    async def test_progress_stops_when_tool_is_cancelled(self):
        reports = AsyncMock()
        context = SimpleNamespace(method='tools/call', params={'name':'translate'},
                                  meta={'progressToken':'test'},
                                  session=SimpleNamespace(report_progress=reports))
        with patch('nativ_mcp.progress.PROGRESS_INTERVAL_SECONDS', .01):
            async def hold(_):
                await asyncio.Event().wait()
            task = asyncio.create_task(tool_progress(context, hold))
            await asyncio.sleep(.04)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            count = reports.await_count
            await asyncio.sleep(.04)
        self.assertGreater(count, 0)
        self.assertEqual(reports.await_count, count)


if __name__ == '__main__':
    unittest.main()
