import unittest
from unittest.mock import patch
import httpx
from nativ_mcp.client import NativClient


class CreditEntitlementTests(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_credit_errors_remain_errors_without_promoting_a_purchase(self):
        for bearer in (True, False):
            for multipart in (True, False):
                client=NativClient('fixture-key',bearer=bearer)
                transport=httpx.MockTransport(lambda request: httpx.Response(402,json={'detail':'Insufficient credits'}))
                http=httpx.AsyncClient(transport=transport)
                with self.subTest(bearer=bearer,multipart=multipart), patch('nativ_mcp.client.httpx.AsyncClient',return_value=http):
                    with self.assertRaises(RuntimeError) as caught:
                        if multipart:
                            await client._request_multipart('/image/localize',files={'image':('sample.png',b'fixture','image/png')})
                        else:
                            await client.translate('Hello','French',language_code='fr')
                message=str(caught.exception)
                self.assertIn('Insufficient Nativ credits',message)
                self.assertEqual('Top up' in message,not bearer)
                self.assertEqual('https://' in message,not bearer)
