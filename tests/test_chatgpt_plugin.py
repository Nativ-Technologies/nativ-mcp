import asyncio
import csv
import io
import json
import unittest
from unittest.mock import AsyncMock, patch
import httpx

from nativ_mcp.chatgpt import SCOPE, UI_URI, csv_bytes, with_csv_export
from nativ_mcp.hosted import create_app
from nativ_mcp.runtime import hosted_request, HostedRequest
from nativ_mcp.server import _get_client

RESOURCE = 'http://localhost:8080/chatgpt/mcp'


class PluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen = []
        async def authenticate(request):
            self.seen.append((request.url.path, dict(request.headers)))
            if request.url.path == '/master-tm/stats':
                return httpx.Response(200 if request.headers.get('x-api-key') == 'nativ_old' else 401, json={})
            token = request.headers.get('authorization', '')
            if token == 'Bearer nat_unavailable': return httpx.Response(500)
            if token == 'Bearer nat_wrong_resource':
                return httpx.Response(200, json={'active': True, 'resource': 'https://other.example', 'scope': SCOPE, 'user_id': '42'})
            if token not in ('Bearer nat_alice', 'Bearer nat_bob'): return httpx.Response(401)
            return httpx.Response(200, json={'active': True, 'resource': RESOURCE, 'scope': SCOPE, 'user_id': token.split('_')[-1]})
        self.app = create_app(api_transport=httpx.MockTransport(authenticate))
        self.ready, self.stop = asyncio.Event(), asyncio.Event()
        async def run_lifespan():
            async with self.app.router.lifespan_context(self.app):
                self.ready.set()
                await self.stop.wait()
        self.lifespan_task = asyncio.create_task(run_lifespan())
        await self.ready.wait()
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://localhost:8080')

    async def asyncTearDown(self):
        await self.http.aclose(); self.stop.set(); await self.lifespan_task

    async def rpc(self, method, params=None, token='nat_alice', path='/chatgpt/mcp'):
        response = await self.http.post(path, headers={'Authorization': 'Bearer '+token, 'Accept':'application/json, text/event-stream', 'MCP-Protocol-Version':'2025-11-25'}, json={'jsonrpc':'2.0','id':1,'method':method,'params': params or {}})
        if response.headers.get('content-type','').startswith('text/event-stream'):
            messages=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            value=next(m for m in messages if m.get('id') == 1)
            return response, value
        return response, response.json()

    async def test_public_discovery_and_fail_closed_authentication(self):
        response=await self.http.get('/.well-known/oauth-protected-resource/chatgpt/mcp')
        self.assertEqual(response.status_code,200); self.assertEqual(response.json()['resource'],RESOURCE)
        self.assertEqual(self.seen, [])
        for token,status in [('',401),('nativ_old',401),('nat_bad',401),('nat_wrong_resource',401),('nat_unavailable',503)]:
            response,_=await self.rpc('tools/list',token=token)
            self.assertEqual(response.status_code,status, response.text)
            if status==401:self.assertIn('resource_metadata=',response.headers['www-authenticate'])
        self.assertIsNone(hosted_request.get())

    async def test_separate_catalog_and_ui_metadata(self):
        response,data=await self.rpc('tools/list')
        self.assertEqual(response.status_code,200,response.text)
        tools=data['result']['tools']
        self.assertEqual(len(tools),7)
        self.assertNotIn('delete_style_guide',{t['name'] for t in tools})
        self.assertTrue(all(t['_meta']['securitySchemes'][0]['scopes']==[SCOPE] for t in tools))
        localize=next(t for t in tools if t['name']=='localize_text')
        self.assertEqual(localize['_meta']['ui']['resourceUri'],UI_URI)
        response,data=await self.rpc('resources/read',{'uri':UI_URI})
        self.assertEqual(data['result']['contents'][0]['mimeType'],'text/html;profile=mcp-app')
        self.assertIn('ui/notifications/tool-result',data['result']['contents'][0]['text'])
        response,data=await self.rpc('tools/list',token='nativ_old',path='/mcp')
        self.assertEqual(len(data['result']['tools']),51)

    async def test_translation_uses_oauth_and_structured_review_without_memory_write(self):
        observed=[]
        def client():
            actual=_get_client();observed.append(actual.headers)
            result=AsyncMock();result.translate.return_value={'translated_text':'Bonjour','backtranslation':'Hello','rationale':'Greeting','tm_match':{'score':100}}
            return result
        with patch('nativ_mcp.chatgpt._get_client',side_effect=client):
            response,data=await self.rpc('tools/call',{'name':'localize_text','arguments':{'text':'Hello','target_language':'French','target_language_code':'fr','max_characters':4}})
        self.assertEqual(response.status_code,200,data)
        self.assertFalse(data['result'].get('isError'),data)
        result=data['result']['structuredContent']
        self.assertEqual(result['items'][0]['translation'],'Bonjour')
        self.assertTrue(result['items'][0]['over_limit'])
        self.assertEqual(observed[0]['Authorization'],'Bearer nat_alice')
        self.assertNotIn('X-API-Key',observed[0])
        self.assertIsNone(hosted_request.get())

    async def test_context_and_saved_results_omit_unneeded_account_and_audit_fields(self):
        client=AsyncMock()
        client.get_languages.return_value={'languages':[{'id':1,'user_id':42,'language':'French','language_code':'fr'}]}
        client.get_brand_prompt.return_value={'user_id':42,'prompt':'Keep Field Notes unchanged','updated_at':'timestamp'}
        client.list_style_guides.return_value=[{'id':2,'title':'Field Notes','content':'Warm tone','created_at':'timestamp'}]
        client.search_tm.return_value={'matches':[]}
        client.add_tm_entry.return_value={'id':'entry-1','user_id':42,'end_user_id':7,'created_at':'timestamp','source_text':'Hello','target_text':'Bonjour'}
        with patch('nativ_mcp.chatgpt._get_client',return_value=client):
            _,data=await self.rpc('tools/call',{'name':'get_localization_context','arguments':{}})
            context=data['result']['structuredContent']
            self.assertEqual(context['languages']['languages'],[{'language':'French','language_code':'fr'}])
            self.assertEqual(context['brand_voice'],{'prompt':'Keep Field Notes unchanged'})
            self.assertEqual(context['style_guides'],[{'title':'Field Notes','content':'Warm tone'}])
            _,data=await self.rpc('tools/call',{'name':'save_approved_translation','arguments':{'source_text':'Hello','target_text':'Bonjour','source_language_code':'en','target_language_code':'fr','approved':True}})
            self.assertEqual(data['result']['structuredContent'],{'status':'saved','tm_id':'entry-1','entry':{'source_text':'Hello','target_text':'Bonjour'}})

    async def test_missing_approval_and_invalid_image_never_call_api(self):
        client=AsyncMock()
        with patch('nativ_mcp.chatgpt._get_client',return_value=client):
            _,data=await self.rpc('tools/call',{'name':'save_approved_translation','arguments':{'source_text':'Hello','target_text':'Bonjour','source_language_code':'en','target_language_code':'fr'}})
            self.assertTrue(data['result']['isError'])
            client.add_tm_entry.assert_not_awaited()
            _,data=await self.rpc('tools/call',{'name':'extract_creative_text','arguments':{'image_url':'file:///etc/passwd'}})
            self.assertTrue(data['result']['isError'])

    async def test_approved_wording_and_identity_isolation(self):
        seen=[]
        def client():
            seen.append(hosted_request.get().identity)
            result=AsyncMock();result.add_tm_entry.return_value={'id':'entry-1'};result.search_tm.return_value={'matches':[]}
            return result
        with patch('nativ_mcp.chatgpt._get_client',side_effect=client):
            for token in ['nat_alice','nat_bob']:
                _,data=await self.rpc('tools/call',{'name':'save_approved_translation','arguments':{'source_text':'Hello','target_text':'Bonjour','source_language_code':'en','target_language_code':'fr','approved':True}},token=token)
                self.assertFalse(data['result'].get('isError'),data)
        self.assertEqual(seen,['alice','bob'])

    async def test_repeating_an_approved_exact_pair_does_not_write_again(self):
        client=AsyncMock()
        match={'tm_id':'existing', 'source_text':'Hello', 'target_text':'Bonjour', 'information_source':'manual', 'source_name':None}
        client.search_tm.return_value={'matches':[match]}
        args={'name':'save_approved_translation','arguments':{'source_text':'Hello','target_text':'Bonjour','source_language_code':'en','target_language_code':'fr','approved':True}}
        with patch('nativ_mcp.chatgpt._get_client',return_value=client):
            _,data=await self.rpc('tools/call',args)
        self.assertFalse(data['result'].get('isError'))
        self.assertEqual(data['result']['structuredContent']['status'],'already_saved')
        client.add_tm_entry.assert_not_awaited()
        client.search_tm.assert_awaited_once_with('Hello',source_lang='en',target_lang='fr',limit=10)

    async def test_racing_approved_save_requires_evidence_of_existing_pair(self):
        client=AsyncMock()
        match={'tm_id':'existing', 'source_text':'Hello', 'target_text':'Bonjour', 'information_source':'manual', 'source_name':None}
        client.search_tm.side_effect=[{'matches':[]},{'matches':[match]}]
        response=httpx.Response(500,request=httpx.Request('POST','https://api.usenativ.com/master-tm/entries'))
        client.add_tm_entry.side_effect=httpx.HTTPStatusError('duplicate',request=response.request,response=response)
        args={'name':'save_approved_translation','arguments':{'source_text':'Hello','target_text':'Bonjour','source_language_code':'en','target_language_code':'fr','approved':True}}
        with patch('nativ_mcp.chatgpt._get_client',return_value=client):
            _,data=await self.rpc('tools/call',args)
        self.assertFalse(data['result'].get('isError'))
        self.assertEqual(data['result']['structuredContent']['entry']['tm_id'],'existing')
        client.search_tm.side_effect=[{'matches':[]},{'matches':[]}]
        with patch('nativ_mcp.chatgpt._get_client',return_value=client):
            _,data=await self.rpc('tools/call',args)
        self.assertTrue(data['result'].get('isError'))

    async def test_overlapping_callers_keep_separate_identities_and_limit_concurrency(self):
        ready, release = asyncio.Event(), asyncio.Event()
        identities = []
        async def translate(*args, **kwargs):
            identity = hosted_request.get().identity
            identities.append(identity)
            if len(identities) == 4: ready.set()
            await release.wait()
            self.assertEqual(hosted_request.get().identity, identity)
            return {'translated_text': 'Bonjour'}
        client = AsyncMock(); client.translate.side_effect = translate
        arguments = {'name':'localize_text','arguments':{'text':'Hello','target_language':'French','target_language_code':'fr'}}
        with patch('nativ_mcp.chatgpt._get_client', return_value=client):
            calls=[asyncio.create_task(self.rpc('tools/call', arguments, token=token)) for token in ['nat_alice','nat_bob','nat_alice','nat_bob']]
            await asyncio.wait_for(ready.wait(), 2)
            response,_=await self.rpc('tools/call', arguments)
            self.assertEqual(response.status_code,429)
            release.set()
            completed=await asyncio.gather(*calls)
            self.assertTrue(all(not result['result'].get('isError') for _,result in completed))
        self.assertEqual(sorted(identities), ['alice','alice','bob','bob'])
        self.assertIsNone(hosted_request.get())

    async def test_failed_translation_does_not_create_fabricated_success(self):
        client=AsyncMock();client.translate.return_value={'translated_text':''}
        with patch('nativ_mcp.chatgpt._get_client',return_value=client):
            _,data=await self.rpc('tools/call',{'name':'localize_text','arguments':{'text':'Hello','target_language':'French','target_language_code':'fr'}})
        self.assertTrue(data['result']['isError'])

if __name__ == '__main__':unittest.main()


class CSVExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_export_roundtrip_and_formula_protection(self):
        items = [{"source": 'Hello, "world"\nSecond line', "translation": 'Bonjour, "monde"'},
                 {"source": " =HYPERLINK(1)", "translation": "@formula"},
                 {"source": "-formula", "translation": "\tvalue"}]
        data = csv_bytes(items, "fr")
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        self.assertEqual(rows, [["Source", "Translation", "Language"],
                               [items[0]["source"], items[0]["translation"], "fr"],
                               ["' =HYPERLINK(1)", "'@formula", "fr"],
                               ["'-formula", "'\tvalue", "fr"]])

    async def test_export_uses_existing_temporary_store_and_preserves_draft_on_failure(self):
        store = AsyncMock()
        store.save.return_value = "https://storage.googleapis.com/private/temporary.csv?signature=test"
        token = hosted_request.set(HostedRequest(api_key="nat_fixture", artifact_store=store))
        try:
            draft = {"items": [{"source": "Hello", "translation": "Bonjour"}], "language_code": "fr", "status": "draft"}
            result = await with_csv_export(dict(draft))
            self.assertEqual(result["artifacts"][0]["url"], store.save.return_value)
            self.assertEqual(result["artifacts"][0]["expires_in_seconds"], 3600)
            self.assertEqual(store.save.await_args.args, (csv_bytes(draft["items"], "fr"), "nativ-localisation.csv", "text/csv;charset=utf-8"))
            store.save.side_effect = RuntimeError("private storage detail")
            failed = await with_csv_export(dict(draft))
            self.assertEqual(failed["items"], draft["items"])
            self.assertIn("temporarily unavailable", failed["export_error"])
            self.assertNotIn("private storage detail", str(failed))
            self.assertNotIn("artifacts", failed)
        finally:
            hosted_request.reset(token)
