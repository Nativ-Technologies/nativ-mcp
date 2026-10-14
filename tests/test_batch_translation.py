import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from mcp import Client
from nativ_mcp.client import NativClient
from nativ_mcp.server import mcp


class BatchTranslationTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, texts):
        async with Client(mcp) as client:
            return await client.call_tool('translate_batch', {
                'texts': texts, 'target_language': 'Marathi',
                'target_language_code': 'mr-IN', 'context': 'Campaign voiceover',
                'formality': 'neutral',
            })

    async def test_eight_cues_make_one_shared_context_request(self):
        texts = [f'Cue {i}' for i in range(8)]
        outputs = [f'मराठी {i}' for i in range(8)]
        details = [{'tm_match': {'score': 87}}] + [{}] * 7
        with patch.dict('os.environ', {'NATIV_API_KEY': 'nativ_test'}), patch.object(
            NativClient, '_request', AsyncMock(return_value={
                'translated_text': json.dumps(outputs), 'segment_details': details,
            }),
        ) as upstream:
            result = await self.call(texts)
        self.assertFalse(result.is_error)
        upstream.assert_awaited_once()
        body = upstream.call_args.kwargs['json_body']
        self.assertEqual(json.loads(body['text']), texts)
        self.assertEqual(body['origin'], 'mcp_batch_translation')
        self.assertEqual(body['language_code'], 'mr-IN')
        self.assertEqual(body['context'], 'Campaign voiceover')
        self.assertEqual(body['formality'], 'neutral')
        self.assertTrue(body['include_tm_info'])
        output = result.content[0].text
        self.assertIn('(TM 87%)', output)
        self.assertLess(output.index('मराठी 0'), output.index('मराठी 7'))

    async def test_incomplete_result_is_protocol_error_not_success_text(self):
        for response in ({'translated_text': '["एक"]'}, {'translated_text': '["एक", ""]'},
                         {'translated_text': 'unbatched response'}):
            with self.subTest(response=response), patch.dict('os.environ', {'NATIV_API_KEY': 'nativ_test'}), patch.object(
                NativClient, '_request', AsyncMock(return_value=response),
            ) as upstream:
                result = await self.call(['One', 'Two'])
                self.assertTrue(result.is_error)
                upstream.assert_awaited_once()

    async def test_timeout_is_explicit_and_not_retried(self):
        with patch.dict('os.environ', {'NATIV_API_KEY': 'nativ_test'}), patch.object(
            NativClient, '_request', AsyncMock(side_effect=httpx.ReadTimeout('')),
        ) as upstream:
            result = await self.call(['Cue'])
        self.assertTrue(result.is_error)
        self.assertIn('timed out', result.content[0].text)
        upstream.assert_awaited_once()

    async def test_backend_deadline_is_explicit_tool_error(self):
        request = httpx.Request('POST', 'https://api.usenativ.com/text/culturalize')
        response = httpx.Response(504, request=request)
        error = httpx.HTTPStatusError('timeout', request=request, response=response)
        with patch.dict('os.environ', {'NATIV_API_KEY': 'nativ_test'}), patch.object(
            NativClient, '_request', AsyncMock(side_effect=error),
        ):
            result = await self.call(['Cue'])
        self.assertTrue(result.is_error)
        self.assertIn('deadline', result.content[0].text)

    async def test_outer_deadline_cancels_the_upstream_call(self):
        cancelled = asyncio.Event()
        async def slow(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch.dict('os.environ', {'NATIV_API_KEY': 'nativ_test'}), patch(
            'nativ_mcp.server._BATCH_DEADLINE_SECONDS', .01,
        ), patch.object(NativClient, '_request', slow):
            result = await self.call(['Cue'])
        self.assertTrue(result.is_error)
        self.assertTrue(cancelled.is_set())

    async def test_chunk_boundaries_keep_duplicates_and_order(self):
        texts = ['Same'] * 33
        upstream = AsyncMock(side_effect=[{'translated_text': json.dumps(['A'] * 32)},
                                         {'translated_text': '["B"]'}])
        with patch.object(NativClient, '_request', upstream):
            results = await NativClient('nativ_test').translate_batch(texts, 'Marathi')
        self.assertEqual(len(results), 33)
        self.assertEqual(results[-1]['translated_text'], 'B')
        self.assertEqual([len(json.loads(c.kwargs['json_body']['text'])) for c in upstream.call_args_list], [32, 1])

    async def test_empty_batch_does_not_call_backend(self):
        with patch.dict('os.environ', {'NATIV_API_KEY': 'nativ_test'}), patch.object(NativClient, '_request', AsyncMock()) as upstream:
            result = await self.call([])
        self.assertFalse(result.is_error)
        upstream.assert_not_awaited()

    async def test_logs_do_not_include_source_text_or_api_key(self):
        with patch.dict('os.environ', {'NATIV_API_KEY': 'nativ_private'}), patch.object(
            NativClient, '_request', AsyncMock(return_value={'translated_text': '["अनुवाद"]'}),
        ), self.assertLogs('nativ-mcp', level='INFO') as logs:
            await self.call(['private customer copy'])
        output = '\n'.join(logs.output)
        self.assertNotIn('private customer copy', output)
        self.assertNotIn('nativ_private', output)
        self.assertIn('mcp_batch_complete', output)
