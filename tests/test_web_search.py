import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage

from cortexa.tools import web_search as web


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    monkeypatch.setenv('WEB_SEARCH_PROVIDER', 'bocha')
    monkeypatch.setenv('BOCHA_API_KEY', 'test-secret')
    monkeypatch.delenv('TAVILY_API_KEY', raising=False)
    monkeypatch.delenv('SERPER_API_KEY', raising=False)


def test_parser_filters_bad_links_deduplicates_and_bounds_content():
    payload = {'code': 200, 'data': {'webPages': {'value': [
        {'name': '标题', 'url': url, 'summary': '摘要' * 500}
        for url in ['javascript:alert(1)', 'https://example.com/a', 'https://example.com/a', 'https://example.com/b']
    ]}}}
    results = web.parse_results(payload, 'bocha', 5)
    assert [r['url'] for r in results] == ['https://example.com/a', 'https://example.com/b']
    assert all(len(r['snippet']) <= 700 for r in results)
    assert len(web.parse_results(payload, 'bocha', 1)) == 1
    for invalid in [{}, {'code': 500}, {'code': 200, 'data': {'webPages': {'value': 'bad'}}}]:
        with pytest.raises(ValueError):
            web.parse_results(invalid, 'bocha', 5)
    assert web.parse_results({'code': 200, 'data': {'webPages': {'value': []}}}, 'bocha', 5) == []


def test_unconfigured_explicit_keyed_provider_never_sends_request(monkeypatch):
    monkeypatch.setenv('WEB_SEARCH_PROVIDER', 'bocha')
    monkeypatch.delenv('BOCHA_API_KEY')
    monkeypatch.setattr(web.httpx, 'AsyncClient', lambda **kw: pytest.fail('No network without credentials'))
    assert not web.search_status()['configured']
    assert '未配置' in asyncio.run(web.search_public_web('公开主题'))['error']


def test_default_provider_uses_first_available_keyless_provider(monkeypatch):
    monkeypatch.delenv('WEB_SEARCH_PROVIDER', raising=False)
    monkeypatch.delenv('BOCHA_API_KEY', raising=False)
    monkeypatch.delenv('TAVILY_API_KEY', raising=False)
    monkeypatch.delenv('SERPER_API_KEY', raising=False)
    provider, setting, key = web.search_config()
    assert provider == 'searxng'
    assert setting[0] == 'SearXNG（自建）'
    assert key == ''
    assert web.search_status()['configured']


@pytest.mark.parametrize('provider,env_key,payload', [
    ('bocha', 'BOCHA_API_KEY', {'code': 200, 'data': {'webPages': {'value': [{'name': '官网', 'url': 'https://example.com', 'summary': '摘要'}]}}}),
    ('tavily', 'TAVILY_API_KEY', {'results': [{'title': '官网', 'url': 'https://example.com', 'content': '摘要'}]}),
    ('serper', 'SERPER_API_KEY', {'organic': [{'title': '官网', 'link': 'https://example.com', 'snippet': '摘要'}]}),
])
def test_provider_wire_protocol_and_normalized_result(monkeypatch, provider, env_key, payload):
    import json
    monkeypatch.setenv('WEB_SEARCH_PROVIDER', provider)
    monkeypatch.setenv(env_key, 'test-secret')
    original = httpx.AsyncClient
    def handler(request):
        assert str(request.url) == web.PROVIDERS[provider][2]
        data = json.loads(request.content)
        assert data.get('query', data.get('q')) == '公开主题'
        if provider == 'bocha':
            assert request.headers['Authorization'] == 'Bearer test-secret'
        elif provider == 'tavily':
            assert data['api_key'] == 'test-secret'
        else:
            assert request.headers['X-API-KEY'] == 'test-secret'
        return httpx.Response(200, json=payload)
    monkeypatch.setattr(web.httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    result = asyncio.run(web.search_public_web('公开主题'))
    assert result['results'] == [{'title': '官网', 'url': 'https://example.com', 'snippet': '摘要'}]
    assert 'test-secret' not in str(result) + str(web.search_status())


def test_tool_budget_cache_sources_and_validation(monkeypatch):
    search = AsyncMock(return_value={'results': [{'title': '事实', 'url': 'https://example.com', 'snippet': '摘要'}]})
    monkeypatch.setattr(web, 'search_public_web', search)
    async def scenario():
        sources = []
        tool = web.make_search_tool(sources)
        first = await tool.ainvoke({'query': '公开主题'})
        assert await tool.ainvoke({'query': '公开主题'}) == first
        await tool.ainvoke({'query': '公开主题2'})
        await tool.ainvoke({'query': '公开主题3'})
        assert '预算' in (await tool.ainvoke({'query': '公开主题4'}))['error']
        assert search.await_count == 3 and len(sources) == 1
        for args in [{'query': ''}, {'query': 'x', 'max_results': 6}, {'query': 'x', 'url': 'http://localhost'}]:
            assert '参数无效' in await tool.ainvoke(args)
        assert search.await_count == 3
    asyncio.run(scenario())


def test_binding_workspace_status_proxy_and_user_prohibition():
    async def scenario():
        workspace = uuid.uuid4()
        agent = SimpleNamespace(workspace_id=workspace, agent_type='llm', tool_ids=[])
        db = AsyncMock()
        assert await web.load_search_tools(agent, db) == []
        db.get.assert_not_called()
        agent.tool_ids = [str(web.search_tool_id(workspace))]
        db.get.return_value = SimpleNamespace(workspace_id=workspace, status='active')
        assert len(await web.load_search_tools(agent, db, '最新新闻')) == 1
        assert await web.load_search_tools(agent, db, '不要联网，整理内部资料') == []
        agent.agent_type = 'proxy'
        assert await web.load_search_tools(agent, db) == []
        agent.agent_type = 'llm'
        db.get.return_value.status = 'inactive'
        assert await web.load_search_tools(agent, db) == []
        db.get.return_value = SimpleNamespace(workspace_id=uuid.uuid4(), status='active')
        assert await web.load_search_tools(agent, db) == []
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', [httpx.ConnectError('private transport detail'), TimeoutError('timeout'), ValueError('bad response')])
def test_transport_errors_are_explicit_and_redacted(monkeypatch, failure):
    class Client:
        async def __aenter__(self):
            raise failure
        async def __aexit__(self, *args):
            pass
    monkeypatch.setattr(web.httpx, 'AsyncClient', lambda **kw: Client())
    result = asyncio.run(web.search_public_web('公开主题'))
    assert result['results'] == [] and '失败' in result['error']
    assert 'private transport detail' not in str(result)


def test_runtime_returns_real_tool_result_to_model(monkeypatch):
    monkeypatch.setattr(web, 'search_public_web', AsyncMock(return_value={'results': [{'title': '官网', 'url': 'https://example.com', 'snippet': '摘要'}]}))
    class Model:
        def bind_tools(self, tools):
            return self
        async def ainvoke(self, history):
            if len(history) == 1:
                return AIMessage(content='', tool_calls=[{'name': 'web_search', 'args': {'query': '官网'}, 'id': 'call1', 'type': 'tool_call'}])
            assert history[-1].tool_call_id == 'call1'
            assert 'https://example.com' in history[-1].content
            return AIMessage(content='来源：https://example.com')
    result = asyncio.run(web.invoke_with_tools(Model(), [{'role': 'user', 'content': '搜索官网'}], [web.make_search_tool()]))
    assert 'https://example.com' in result.content


def test_runtime_forces_matched_business_tool_before_answering():
    from langchain_core.tools import StructuredTool

    calls = []

    async def query_region(region: str):
        return {'data': [{'name': '真实记录', 'region': region}]}

    business_tool = StructuredTool.from_function(
        coroutine=query_region,
        name='query_configured_records',
        description='由数据源配置提供的通用查询',
    )

    class BoundModel:
        def __init__(self, tool_choice):
            self.tool_choice = tool_choice

        async def ainvoke(self, history):
            calls.append(self.tool_choice)
            if len(history) == 1:
                # After the fix, we no longer use tool_choice='required'
                # because some models (e.g. mimo) don't support it
                assert self.tool_choice is None
                return AIMessage(content='', tool_calls=[{
                    'name': 'query_configured_records',
                    'args': {'region': '杭州'},
                    'id': 'business_call',
                    'type': 'tool_call',
                }])
            assert '真实记录' in history[-1].content
            return AIMessage(content='仅根据真实记录回答')

    class Model:
        def bind_tools(self, tools, tool_choice=None):
            assert [tool.name for tool in tools] == ['query_configured_records']
            return BoundModel(tool_choice)

    result = asyncio.run(web.invoke_with_tools(
        Model(),
        [{'role': 'user', 'content': '杭州有哪些记录'}],
        [business_tool],
        required_tools=[business_tool],
    ))
    assert result.content == '仅根据真实记录回答'
    # After the fix, we no longer use tool_choice='required'
    assert calls == [None, None]


def test_runtime_refuses_ungrounded_answer_when_required_tool_is_not_called():
    from langchain_core.tools import StructuredTool
    from cortexa.tools.runtime import DATA_QUERY_GROUNDING_FAILURE

    async def query_records():
        return {'data': []}

    business_tool = StructuredTool.from_function(
        coroutine=query_records,
        name='query_configured_records',
        description='配置查询',
    )

    class BoundModel:
        async def ainvoke(self, history):
            return AIMessage(content='模型猜测的业务结果')

    class Model:
        def bind_tools(self, tools, tool_choice=None):
            return BoundModel()

    result = asyncio.run(web.invoke_with_tools(
        Model(),
        [{'role': 'user', 'content': '查询业务数据'}],
        [business_tool],
        required_tools=[business_tool],
    ))
    assert result.content == DATA_QUERY_GROUNDING_FAILURE
    assert '模型猜测' not in result.content


def test_searxng_needs_no_key_and_uses_json_search(monkeypatch):
    monkeypatch.setenv('WEB_SEARCH_PROVIDER', 'searxng')
    monkeypatch.setenv('SEARXNG_URL', 'http://127.0.0.1:8888')
    monkeypatch.delenv('BOCHA_API_KEY')
    original = httpx.AsyncClient
    def handler(request):
        assert request.method == 'GET'
        assert request.url.host == '127.0.0.1'
        assert request.url.path == '/search'
        assert request.url.params['q'] == '公开主题'
        assert request.url.params['format'] == 'json'
        assert 'authorization' not in request.headers and 'x-api-key' not in request.headers
        return httpx.Response(200, json={'results': [{'title': '官网', 'url': 'https://example.com', 'content': '摘要'}]})
    monkeypatch.setattr(web.httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    status = web.search_status()
    assert status['configured'] and not status['requires_api_key']
    result = asyncio.run(web.search_public_web('公开主题'))
    assert result['results'][0]['snippet'] == '摘要'
    assert result['provider'] == 'SearXNG（自建）'


def test_searxng_reports_upstream_failure_instead_of_empty_success():
    with pytest.raises(ValueError):
        web.parse_results({'results': [], 'unresponsive_engines': [['bing', 'timeout']]}, 'searxng', 5)
    assert web.parse_results({'results': [], 'unresponsive_engines': []}, 'searxng', 5) == []


def test_searxng_invalid_server_config_fails_closed(monkeypatch):
    monkeypatch.setenv('WEB_SEARCH_PROVIDER', 'searxng')
    for endpoint in ['file:///etc/passwd', 'http://user:password@localhost', 'http://localhost/?token=secret']:
        monkeypatch.setenv('SEARXNG_URL', endpoint)
        assert not web.search_status()['configured']
