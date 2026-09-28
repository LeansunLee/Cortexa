import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from sqlalchemy.dialects import postgresql

from cortexa.api.conversations import _retrieve_knowledge
from cortexa.data import doc_storage


def retrieve(monkeypatch, documents, query, bound_ids=None):
    agent = SimpleNamespace(id=uuid.uuid4(), workspace_id=uuid.uuid4(), knowledge_base_ids=bound_ids or [])
    database = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalars=lambda: Mock(all=lambda: documents))))
    monkeypatch.setattr(doc_storage, "load_document_content", lambda identifier: None)
    sources = []
    context = asyncio.run(_retrieve_knowledge(agent, query, database, sources=sources))
    statement = database.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    return context, sources, sql, agent


def document(name, content, encoding="utf-8"):
    return SimpleNamespace(id=uuid.uuid4(), knowledge_base_id=uuid.uuid4(), name=name, content=content, metadata_json={"encoding": encoding})


def test_private_knowledge_needs_no_binding_and_keeps_workspace_scope(monkeypatch):
    policy = document("黑旗600销售政策.pdf", "黑旗600销售政策：测试补贴规则。")
    context, sources, sql, agent = retrieve(monkeypatch, [policy], "黑旗600销售政策")
    assert "测试补贴规则" in context
    assert sources[0]["document_id"] == str(policy.id)
    assert sources[0]["description"] in context
    assert f"t_knowledge_bases.agent_id = '{agent.id}'" in sql
    assert f"t_knowledge_bases.workspace_id = '{agent.workspace_id}'" in sql
    assert "t_knowledge_bases.agent_id IS NULL" in sql
    assert "t_documents.valid_until IS NULL" in sql
    assert "t_documents.valid_until >=" in sql


def test_binary_policy_is_reported_unreadable_not_cited(monkeypatch):
    policy = document("黑旗600销售政策.pdf", "JVBERi0xLjQ=...[全文已存储到文件系统]", "base64")
    context, sources, _, _ = retrieve(monkeypatch, [policy], "黑旗600销售政策")
    assert policy.name in context
    assert "没有可读取的正文" in context
    assert "JVBER" not in context
    assert sources == []


def test_unrelated_document_is_not_a_fallback_citation(monkeypatch):
    context, sources, _, _ = retrieve(monkeypatch, [document("天气.txt", "明天晴天")], "黑旗600销售政策")
    assert context == ""
    assert sources == []


def test_policy_content_beyond_summary_reaches_context(monkeypatch):
    policy = document('黑旗600销售政策.pdf', '政策正文。' * 450 + '末页补贴金额为测试值。')
    context, _, _, _ = retrieve(monkeypatch, [policy], '黑旗600补贴')
    assert '末页补贴金额为测试值' in context


def test_specific_product_query_does_not_hide_third_policy(monkeypatch):
    docs = [document('黑旗600' + name + '.pdf', '黑旗600政策补贴' + name) for name in ['产品手册', '定价申请', '价格签批']]
    _, sources, _, _ = retrieve(monkeypatch, docs, '黑旗600政策补贴')
    assert len(sources) == 3


def test_processing_pdf_reports_wait_instead_of_missing_upload(monkeypatch):
    policy = document('黑旗600销售政策.pdf', '')
    policy.metadata_json['extraction_status'] = 'processing'
    context, sources, _, _ = retrieve(monkeypatch, [policy], '黑旗600政策')
    assert '系统正在进行文字识别' in context and '无需重新上传' in context
    assert sources == []


def test_exact_product_title_keeps_pricing_table_above_other_models(monkeypatch):
    docs = [document(f'灰石{i}政策返利补贴.pdf', '定价政策返利补贴黑旗') for i in range(10)]
    target = document('黑旗600价格签批.pdf', '32800 元')
    _, sources, _, _ = retrieve(monkeypatch, docs + [target], '黑旗600的定价政策返利补贴')
    assert sources[0]['document_id'] == str(target.id)
