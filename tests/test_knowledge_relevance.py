import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from cortexa.agents.knowledge import retrieve_knowledge
from cortexa.data import doc_storage
from cortexa.rag.relevance import select_documents, query_variants, models
from cortexa.runtime.loop import token_upper_bound


def doc(name, text, metadata=None):
    return SimpleNamespace(
        id=uuid.uuid4(), knowledge_base_id=uuid.uuid4(), name=name, content=text, metadata_json=metadata or {}
    )


def decisions(documents, query, **kwargs):
    plan, ranked = select_documents(documents, query, {str(d.id): d.content for d in documents}, **kwargs)
    return plan, {d.name: r for r, d in ranked}


def retrieve(monkeypatch, documents, query, budget=6000):
    monkeypatch.setattr(doc_storage, "load_document_content", lambda _: None)
    agent = SimpleNamespace(id=uuid.uuid4(), workspace_id=uuid.uuid4(), knowledge_base_ids=[])
    db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalars=lambda: Mock(all=lambda: documents))))
    sources, stats = [], {}
    context = asyncio.run(retrieve_knowledge(agent, query, db, sources, stats, context_budget=budget))
    return context, sources, stats


def test_exact_model_same_series_other_model_and_variant_are_distinct():
    documents = [
        doc(name + "清库复盘.pdf", "已执行清库活动，2026年实际售出120台")
        for name in ["金吉拉250", "金吉拉250CVT", "金吉拉2500", "金吉拉350", "黑旗600"]
    ]
    plan, result = decisions(documents, "金吉拉250清库案例")
    assert plan.entities[0]["name"] == "金吉拉250"
    assert result["金吉拉250清库复盘.pdf"]["evidence_grade"] == "DIRECT"
    for name in ["金吉拉250CVT", "金吉拉2500", "金吉拉350"]:
        assert result[name + "清库复盘.pdf"]["entity_relation"] == "SAME_SERIES"
        assert not result[name + "清库复盘.pdf"]["eligible"]
    assert result["黑旗600清库复盘.pdf"]["evidence_grade"] == "IRRELEVANT"
    assert models("金吉拉250-标准版清库")[0]["name"] == "金吉拉250标准版"
    assert models("金吉拉250 Pro Ultra EC")[0]["name"] == "金吉拉250proultraec"


def test_metadata_id_alias_and_intent_hit_without_query_keywords(monkeypatch):
    metadata = {
        "retrieval": {
            "entities": [{"id": "M-250", "name": "金吉拉250", "aliases": ["J250"], "family": "金吉拉"}],
            "intents": ["clearance"],
            "document_type": "case",
            "case_status": "completed",
        }
    }
    target = doc("区域执行记录.pdf", "2026-09 执行数量120台，期末结存12台。", metadata)
    context, sources, stats = retrieve(monkeypatch, [target], "J250库存去化案例")
    assert sources[0]["evidence_grade"] == "DIRECT" and "执行数量120台" in context
    assert stats["retrieval_trace"]["query_analysis"]["entities"][0]["id"] == "M-250"
    _, result = decisions([target], "model_id:M-250 清库案例")
    assert result[target.name]["entity_relation"] == "EXACT"


def test_alias_ambiguity_and_conflicting_metadata_do_not_invent_entity_scope():
    a = doc("执行记录A", "清库活动已完成120台", {"entities": [{"id": "A", "name": "金吉拉250", "aliases": ["小金"]}]})
    b = doc("执行记录B", "清库活动已完成100台", {"entities": [{"id": "B", "name": "金吉拉350", "aliases": ["小金"]}]})
    plan, result = decisions([a, b], "小金清库案例")
    assert plan.ambiguous_entity and "ambiguous_alias:小金" in plan.uncertainties
    assert all(not item["eligible"] for item in result.values())
    conflicting = doc("金吉拉350清库复盘", "已执行清库活动120台", {"entities": [{"id": "A", "name": "金吉拉250"}]})
    _, result = decisions([conflicting], "金吉拉250清库案例")
    assert result[conflicting.name]["entity_reason"] == "metadata_title_entity_conflict"
    assert result[conflicting.name]["evidence_grade"] != "DIRECT"


def test_expansion_is_business_synonyms_only_and_keeps_exact_entity():
    query = "金吉拉250CVT库存去化案例"
    variants = query_variants(query)
    assert len(variants) > 1
    assert all([m["name"] for m in models(v)] == ["金吉拉250cvt"] for v in variants)
    assert all(v.startswith(query) for v in variants)
    from cortexa.rag.multi_query import generate_query_variants

    fake_llm = Mock()
    assert generate_query_variants(query, llm=fake_llm) == variants
    fake_llm.invoke.assert_not_called()
    _, result = decisions([doc("金吉拉250CVT清库复盘", "2026年已执行清库，售出120台")], query)
    assert next(iter(result.values()))["evidence_grade"] == "DIRECT"


def test_no_direct_case_does_not_promote_pricing_template_or_other_model(monkeypatch):
    documents = [
        doc("金吉拉250价格审批", "金吉拉250提货价19000元"),
        doc("金吉拉350清库复盘", "清库活动已完成120台"),
        doc("金吉拉250清库案例模板", "拟按清库活动案例填写2026数据"),
    ]
    context, sources, stats = retrieve(monkeypatch, documents, "金吉拉250清库活动案例")
    assert "Evidence Insufficient" in context and stats["direct_count"] == 0
    assert all(s["evidence_grade"] == "RELATED" for s in sources)
    assert "金吉拉350清库复盘" not in context
    assert "不能作为目标实体的事实或真实案例" in context


@pytest.mark.parametrize(
    "algorithm,scores", [("lexical", [2, 999]), ("bm25", [0.001, 30]), ("cosine", [0.18, 0.99]), ("rrf", [0.0001, 0.5])]
)
def test_raw_score_scales_do_not_override_evidence_gate(algorithm, scores):
    target = doc("金吉拉250清库复盘", "已执行清库活动120台")
    unrelated = doc("公司介绍", "金吉拉250活动推广产品清库库存资料")
    scorer = lambda name, text, context: scores[0] if name == target.name else scores[1]
    _, result = decisions([unrelated, target], "金吉拉250清库案例", score_fn=scorer, algorithm=algorithm)
    assert result[target.name]["eligible"]
    assert not result[unrelated.name]["eligible"]
    assert result[target.name]["algorithm"] == algorithm


def test_top_k_is_ceiling_and_weak_keyword_hits_do_not_fill_it(monkeypatch):
    documents = [doc("金吉拉250清库复盘", "2026年已执行清库活动，售出120台")]
    documents += [doc(f"公司介绍{i}", "金吉拉250库存产品活动政策") for i in range(20)]
    context, sources, stats = retrieve(monkeypatch, documents, "金吉拉250清库案例")
    assert len(sources) == 1 and stats["candidate_count"] == 21
    assert stats["selected_count"] == 1 and stats["direct_count"] == 1
    assert "公司介绍" not in context
    assert any("profile_not_requested" in c["filter_reasons"] for c in stats["retrieval_trace"]["ranking"])


def test_direct_evidence_wins_context_budget_and_optional_background_is_labelled(monkeypatch):
    target = doc("金吉拉250清库复盘", "2026年已执行清库活动，售出120台。")
    background = doc("金吉拉250产品手册", "参数配置车款说明。" * 800)
    query = "金吉拉250清库案例，参考产品参数背景"
    context, sources, stats = retrieve(monkeypatch, [background, target], query, budget=1100)
    assert token_upper_bound(context) <= 1100
    assert sources[0]["document_id"] == str(target.id) and sources[0]["evidence_grade"] == "DIRECT"
    assert stats["retrieval_trace"]["injected_context"] == context
    assert any("context_budget" in item["filter_reasons"] for item in stats["retrieval_trace"]["ranking"])
    tiny, sources, stats = retrieve(monkeypatch, [target], query, budget=128)
    assert token_upper_bound(tiny) <= 128
    assert not sources and stats["evidence_status"] == "EVIDENCE_INSUFFICIENT"


def test_multiple_entities_missing_evidence_is_explicit(monkeypatch):
    target = doc("金吉拉250清库复盘", "已执行清库活动，售出120台")
    context, sources, stats = retrieve(monkeypatch, [target], "金吉拉250与黑旗600清库案例对比")
    assert sources[0]["evidence_grade"] == "DIRECT"
    assert stats["missing_entities"] == ["黑旗600"] and "Evidence Insufficient" in context


def test_business_id_mismatch_overrides_identical_display_name():
    documents = [
        doc("同名清库复盘", "清库活动已完成120台", {"entities": [{"id": ident, "name": "金吉拉250"}]})
        for ident in ["A", "B"]
    ]
    _, result = select_documents(documents, "model_id:A 清库案例", {str(d.id): d.content for d in documents})
    assert [r["eligible"] for r, d in result if d.metadata_json["entities"][0]["id"] == "B"] == [False]


def test_processing_metadata_hit_is_reported_even_without_title_keyword(monkeypatch):
    pending = doc(
        "区域执行记录.pdf",
        "",
        {"extraction_status": "processing", "entities": [{"id": "M-250", "name": "金吉拉250", "aliases": ["J250"]}]},
    )
    context, sources, stats = retrieve(monkeypatch, [pending], "J250清库案例")
    assert "系统正在进行文字识别" in context and not sources
    assert stats["evidence_status"] == "EVIDENCE_INSUFFICIENT"


def test_bm25_metadata_only_hit_survives_zero_raw_score():
    from cortexa.rag.bm25_search import bm25_retrieve

    metadata = {
        "retrieval": {
            "entities": [{"id": "M-250", "name": "金吉拉250"}],
            "intents": ["clearance"],
            "document_type": "case",
            "case_status": "completed",
        }
    }
    row = SimpleNamespace(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_name="执行记录",
        summary="132",
        content="132",
        document_metadata=metadata,
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=Mock(fetchall=lambda: [row])))
    results = asyncio.run(bm25_retrieve(db, [str(uuid.uuid4())], "model_id:M-250 清库案例", min_score=999))
    assert len(results) == 1 and results[0].score == 0
    assert results[0].metadata["evidence_grade"] == "DIRECT"


@pytest.mark.parametrize("algorithm", ["bm25", "hyde", "multi_query", "ensemble", "parent_child"])
def test_every_rag_strategy_is_gated_against_original_entity(algorithm):
    from cortexa.rag.retriever import RetrievalResult, _gate_results

    target = doc("金吉拉250清库复盘", "已执行清库活动120台")
    wrong = doc("金吉拉250CVT清库复盘", "已执行清库活动200台")
    values = [
        RetrievalResult(uuid.uuid4(), d.id, d.name, d.content, score) for d, score in [(wrong, 0.99), (target, 0.01)]
    ]
    db = SimpleNamespace(scalars=AsyncMock(return_value=Mock(all=lambda: [target, wrong])))
    results = asyncio.run(_gate_results(db, [str(target.knowledge_base_id)], "金吉拉250清库案例", values, algorithm))
    assert [r.document_id for r in results] == [target.id]
    assert results[0].metadata["relevance"]["algorithm"] == algorithm


def test_background_manual_requires_explicit_need_and_has_limited_purpose(monkeypatch):
    manual = doc("金吉拉250产品手册", "发动机配置及车辆参数。")
    query = "金吉拉250清库案例，参考产品参数背景"
    context, sources, stats = retrieve(monkeypatch, [manual], query)
    assert sources[0]["evidence_grade"] == "BACKGROUND"
    assert "仅提供背景信息，不支持目标事实" in context and "Evidence Insufficient" in context


def test_body_and_budget_excerpt_cannot_borrow_other_variant_case(monkeypatch):
    wrong_body = doc("金吉拉250清库复盘", "金吉拉250CVT已执行清库活动，售出200台")
    _, result = decisions([wrong_body], "金吉拉250清库案例")
    assert result[wrong_body.name]["evidence_grade"] != "DIRECT"
    text = "金吉拉250CVT已执行清库活动，售出200台。" * 350 + "\n金吉拉250已执行清库活动，售出120台。"
    mixed = doc("金吉拉250与250CVT清库复盘", text)
    context, sources, stats = retrieve(monkeypatch, [mixed], "金吉拉250清库案例", budget=1300)
    # A wrong-variant-only passage cannot become a direct source merely because
    # the file title names the requested model.
    assert not sources or "金吉拉250已执行" in sources[0]["description"]
    assert token_upper_bound(context) <= 1300


def test_unknown_model_retains_uncertainty_instead_of_using_generic_policy():
    document = doc("公司促销政策申请", "促销政策允许提供消费者补贴。")
    plan, result = decisions([document], "R3促销政策")
    assert plan.entities[0]["name"] == "r3" and plan.uncertainties
    assert result[document.name]["evidence_grade"] != "DIRECT"


def test_unknown_ascii_variant_is_not_prefix_equal_to_base_model():
    variant = doc("金吉拉250ABS清库复盘", "已执行清库活动，售出120台")
    plan, result = decisions([variant], "金吉拉250清库案例")
    assert models(variant.name)[0]["name"] == "金吉拉250abs"
    assert not result[variant.name]["eligible"]


def test_numeric_alias_cannot_bind_a_different_brand_entity():
    unrelated = doc(
        "其他车型清库复盘",
        "清库活动已完成120台",
        {"entities": [{"id": "OTHER", "name": "另一款250", "aliases": ["250"]}]},
    )
    plan, result = decisions([unrelated], "金吉拉250清库案例")
    assert plan.entities[0]["name"] == "金吉拉250" and not plan.entities[0]["id"]
    assert not result[unrelated.name]["eligible"]


def test_chinese_unknown_variant_and_unknown_named_subject_are_not_general_facts():
    variant = doc("金吉拉250旅行版清库复盘", "已执行清库活动120台")
    _, result = decisions([variant], "金吉拉250清库案例")
    assert models(variant.name)[0]["name"] == "金吉拉250旅行版"
    assert not result[variant.name]["eligible"]
    generic = doc("清库活动复盘", "已执行清库活动120台")
    plan, result = decisions([generic], "小山妖清库案例")
    assert plan.entities[0]["source"] == "unresolved_phrase"
    assert result[generic.name]["evidence_grade"] != "DIRECT"


def test_business_id_namespace_prevents_cross_domain_id_collision():
    metadata = lambda kind: {
        "retrieval": {
            "entities": [{"id": "1", "type": kind, "name": "金吉拉250"}],
            "intents": ["clearance"],
            "document_type": "case",
            "case_status": "completed",
        }
    }
    model = doc("模型记录", "120台", metadata("model"))
    customer = doc("客户记录", "400台", metadata("customer"))
    plan, result = decisions([model, customer], "model_id:1 清库案例")
    assert result[model.name]["evidence_grade"] == "DIRECT"
    assert result[customer.name]["evidence_grade"] == "IRRELEVANT"
    plan, result = decisions([model, customer], "entity_id:1 清库案例")
    assert plan.ambiguous_entity and all(not r["eligible"] for r in result.values())


def test_unknown_intent_does_not_turn_entity_word_hits_into_direct_evidence():
    plan, result = decisions([doc("黑旗600清库复盘", "已执行清库120台")], "黑旗600")
    assert "intent_unresolved" in plan.uncertainties
    assert next(iter(result.values()))["evidence_grade"] != "DIRECT"


def test_family_only_query_does_not_recall_other_families_as_same_entity():
    family = doc("金吉拉系列政策申请", "金吉拉系列政策：不同车款分别审批补贴。")
    other = doc("黑旗系列政策申请", "销售政策与补贴说明。")
    child = doc("金吉拉350政策审批", "金吉拉350提货价和补贴政策。")
    plan, result = decisions([other, child, family], "金吉拉政策")
    assert plan.entities[0]["source"] == "family_constraint"
    assert result[family.name]["evidence_grade"] == "DIRECT"
    assert result[other.name]["evidence_grade"] == "IRRELEVANT"
    assert result[child.name]["evidence_grade"] == "RELATED"


def test_hypothetical_case_is_not_promoted_by_execution_words_and_numbers():
    hypothetical = doc("金吉拉250清库案例", "以下是假设案例，仅供测算：金吉拉250已执行清库，销量达到120台。")
    _, result = decisions([hypothetical], "金吉拉250清库案例")
    assert result[hypothetical.name]["evidence_grade"] != "DIRECT"
    assert "hypothetical_or_uncompleted_case" in result[hypothetical.name]["filter_reasons"]
