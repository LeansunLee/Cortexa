import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from agentdevstu.agents import proxy_executor
from agentdevstu.db.models import Agent


@pytest.mark.parametrize('mapping', [{}, {'query': '$.input', 'tenant': '$.tenant'}])
@pytest.mark.parametrize('prompt', ['', '  ', '请返回真实数据'])
def test_prompt_sent_before_mapping_without_mutating_input(monkeypatch, mapping, prompt):
    captured = []
    async def respond(request):
        import json
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'answer': '结果'})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        proxy_executor.httpx,
        'AsyncClient',
        lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw),
    )
    monkeypatch.setattr(proxy_executor, '_get_version_id', AsyncMock(return_value=None))
    source = {'input': '查询销量', 'tenant': 'demo'}
    agent = Agent(proxy_config={'endpoint': 'https://example.test/run', 'request_mapping': mapping, 'supplemental_prompt': prompt})
    result = asyncio.run(proxy_executor.execute_proxy_agent(agent, source, AsyncMock()))
    assert result['success']
    expected = (prompt + '\n\n' if prompt.strip() else '') + '查询销量'
    assert captured == [{('query' if mapping else 'input'): expected, 'tenant': 'demo'}]
    assert source == {'input': '查询销量', 'tenant': 'demo'}


def test_prompt_requires_text_input():
    agent = Agent(proxy_config={'endpoint': 'https://example.test/run', 'supplemental_prompt': '请查询'})
    result = asyncio.run(proxy_executor.execute_proxy_agent(agent, {'question': '销量'}, AsyncMock()))
    assert not result['success']
    assert 'input' in result['error']


def test_prompt_resolution_sends_only_synthesized_prompt(monkeypatch):
    captured = []

    class ResolverModel:
        async def ainvoke(self, messages):
            assert '张三' in messages[1]['content']
            return SimpleNamespace(content=json.dumps({
                'prompt': '查询张三当前的 DMS 权限状态，并尽快返回结果。',
                'missingInformation': [],
                'confidence': 0.96,
                'usedSources': ['current_task', 'conversation_context'],
            }, ensure_ascii=False))

    async def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'answer': '查询完成'})

    from agentdevstu.config import llm_providers
    real_client = httpx.AsyncClient
    monkeypatch.setattr(llm_providers, 'create_llm', lambda _: ResolverModel())
    monkeypatch.setattr(proxy_executor.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr(proxy_executor, '_get_version_id', AsyncMock(return_value=None))
    agent = Agent(
        model='test-model',
        proxy_config={
            'endpoint': 'https://example.test/run',
            'request_mapping': {'prompt': '$.input'},
            'supplemental_prompt': '整理为 DMS 查询请求，不要编造信息。',
            'prompt_resolution': {
                'enabled': True,
                'allowed_sources': ['current_task', 'conversation_context'],
                'confidence_threshold': 0.7,
            },
        },
    )

    result = asyncio.run(proxy_executor.execute_proxy_agent(
        agent,
        {'input': '查一下他的权限，尽快'},
        AsyncMock(),
        resolution_context={'conversation_context': '前文提到的人员是张三'},
    ))

    assert result['success'] is True
    assert result['resolution']['mode'] == 'prompt'
    assert captured == [{'prompt': '查询张三当前的 DMS 权限状态，并尽快返回结果。'}]
    assert '整理为 DMS' not in captured[0]['prompt']


def test_prompt_resolution_blocks_when_context_is_ambiguous(monkeypatch):
    class ResolverModel:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content=json.dumps({
                'prompt': '',
                'missingInformation': ['请补充需要查询的人员姓名。'],
                'confidence': 0.3,
                'usedSources': ['current_task'],
            }, ensure_ascii=False))

    from agentdevstu.config import llm_providers
    monkeypatch.setattr(llm_providers, 'create_llm', lambda _: ResolverModel())
    monkeypatch.setattr(
        proxy_executor.httpx,
        'AsyncClient',
        lambda **_: (_ for _ in ()).throw(AssertionError('不应调用 Proxy')),
    )
    agent = Agent(proxy_config={
        'endpoint': 'https://example.test/run',
        'prompt_resolution': {'enabled': True},
    })

    result = asyncio.run(proxy_executor.execute_proxy_agent(agent, {'input': '查一下他的权限'}, AsyncMock()))

    assert result['success'] is False
    assert result['requires_input'] is True
    assert result['error'] == '请补充需要查询的人员姓名。'
