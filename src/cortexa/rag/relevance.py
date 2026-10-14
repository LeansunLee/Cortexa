"""Deterministic entity/intent evidence gate, independent of raw score scales."""

import re
import unicodedata
from dataclasses import dataclass, field, asdict

INTENTS = {
    "clearance": ("去库存", "清库", "清库存", "库存去化", "消化库存", "库存消化", "去化"),
    "inventory": ("库存", "在库", "库销比", "库存周转", "存货"),
    "pricing": ("定价", "价格", "提货价", "售价", "降价", "价格审批", "价格签批"),
    "policy": ("政策", "返利", "补贴", "资金池", "激励", "优惠"),
    "marketing": ("促销", "推广", "营销", "活动"),
    "sales": ("销售", "销量", "销售额", "达成率", "发货", "销售计划"),
    "specification": ("产品参数", "参数", "配置", "排量", "产品信息", "规格"),
}
DOC_TYPES = {
    "case": ("案例", "复盘", "活动总结", "执行结果", "实际案例"),
    "policy": ("政策", "申请", "审批", "签批", "备案", "制度", "补贴", "返利"),
    "manual": ("手册", "参数", "规格", "配置"),
    "report": ("报表", "报告", "明细", "台账", "统计", "数据"),
    "profile": ("公司介绍", "公司简介", "企业介绍", "企业简介"),
}
PURPOSES = {
    "DIRECT": "支持已匹配实体和意图的事实，不能外推到未覆盖实体",
    "RELATED": "仅供方法、政策框架或比较参考，不能作为目标实体的事实或真实案例",
    "BACKGROUND": "仅提供背景信息，不支持目标事实",
    "IRRELEVANT": "不注入",
}


def normalize(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value))).lower()


def models(text):
    # Reuse the existing domain vocabulary, but parse complete model/variant
    # tokens. 250 != 2500 != 250CVT; no substring identity inference.
    from cortexa.agents.knowledge import PRODUCT_FAMILIES

    pattern = (
        r"("
        + "|".join(map(re.escape, PRODUCT_FAMILIES))
        + r")\s*(\d{2,4})(?!\d)((?:[\s_-]*(?:CVT|Pro|Ultra|EC|标准版|都市版|自动版|长轴距版|逍遥版|Commander|NEO|ACE)|[A-Za-z]{1,12}[0-9]*|[\u4e00-\u9fff]{1,4}版)*)"
    )
    return [
        {"name": normalize(re.sub(r"[-_]", "", m.group())), "family": m.group(1), "type": "model"}
        for m in re.finditer(pattern, text, re.I)
    ]


def metadata_entities(doc):
    meta = getattr(doc, "metadata_json", None) or {}
    retrieval = meta.get("retrieval") if isinstance(meta.get("retrieval"), dict) else {}
    raw = retrieval.get("entities", meta.get("entities", []))
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raw = []
    if not raw and any(meta.get(k) for k in ("entity_id", "model_id", "entity_name", "model_name", "车型", "车款")):
        raw = [
            {
                "id": meta.get("entity_id") or meta.get("model_id"),
                "name": meta.get("entity_name") or meta.get("model_name") or meta.get("车型") or meta.get("车款"),
                "aliases": meta.get("entity_aliases") or meta.get("aliases") or [],
                "family": meta.get("family"),
                "type": meta.get("entity_type") or ("model" if meta.get("model_id") or meta.get("model_name") else ""),
            }
        ]
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        ident = str(item.get("id") or "")
        if not name and not ident:
            continue
        aliases = item.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        aliases = [str(a) for a in aliases if isinstance(a, (str, int)) and str(a)]
        parsed = models(name)
        result.append(
            {
                "id": ident,
                "name": normalize(name),
                "aliases": [normalize(a) for a in aliases],
                "family": str(item.get("family") or (parsed[0]["family"] if parsed else "")),
                "type": str(item.get("type") or ("model" if parsed else "")),
            }
        )
    return result


def entity_key(entity):
    ident = entity.get("id")
    return (entity.get("type") + ":" + ident if ident and entity.get("type") else ident) or entity["name"]


def alias_present(alias, text):
    if not alias or alias.isdigit():
        return False
    for match in re.finditer(re.escape(alias), normalize(text)):
        tail = normalize(text)[match.end() :]
        before = normalize(text)[match.start() - 1 : match.start()] if match.start() else ""
        if re.fullmatch(r"[\u4e00-\u9fff]+", alias) and match.start() and before.isalnum():
            prefix = normalize(text)[: match.start()]
            if not re.search(r"(?:查询|关于|了解|型号|车型|企业|公司|寻找|对|为|给|和|与|的)$", prefix):
                continue
        if (
            alias[0].isascii()
            and alias[0].isalnum()
            and before
            and (before.isascii() and before.isalnum() or before in "-_")
        ):
            continue
        if tail and tail[0].isascii() and tail[0].isalnum():
            continue
        if re.match(r"标准版|都市版|自动版|长轴距版|逍遥版|[\u4e00-\u9fff]{1,4}版", tail):
            continue
        return True
    return False


@dataclass
class QueryAnalysis:
    entities: list = field(default_factory=list)
    intent: str | None = None
    document_type: str | None = None
    keywords: list = field(default_factory=list)
    expansion: list = field(default_factory=list)
    uncertainties: list = field(default_factory=list)
    allow_related: bool = False
    allow_background: bool = False
    ambiguous_entity: bool = False

    def trace(self):
        return asdict(self)


def analyze_query(query, documents=()):
    from cortexa.agents.knowledge import _build_query_context

    analysis = QueryAnalysis()
    # The registry is assembled ONLY from the already authorized candidates.
    registry = [e for doc in documents for e in metadata_entities(doc)]
    query_models = models(query)
    explicit_ids = re.findall(r"(entity_id|model_id|业务ID|车型ID)\s*[:=：]\s*([\w-]+)", query, re.I)
    for key, ident in explicit_ids:
        entity_type = "model" if key.lower() == "model_id" or key == "车型ID" else ""
        entries = [
            e for e in registry if e["id"] == ident and (not entity_type or not e["type"] or e["type"] == entity_type)
        ]
        entries.sort(key=lambda e: bool(entity_type and e["type"] == entity_type), reverse=True)
        if not entity_type and len({e["type"] for e in entries}) > 1:
            analysis.ambiguous_entity = True
            analysis.uncertainties.append("ambiguous_business_id:" + ident)
        analysis.entities.append(
            {
                "id": ident,
                "name": entries[0]["name"] if entries else "",
                "family": entries[0]["family"] if entries else "",
                "source": "business_id",
                "type": entity_type or (entries[0]["type"] if entries else ""),
            }
        )
    if not explicit_ids:
        hits = {}
        for e in registry:
            for alias in [e["name"], *e["aliases"]]:
                if alias == e["family"] and alias != e["name"]:
                    continue  # A family name cannot alias one individual model.
                if alias_present(alias, query):
                    hits.setdefault(alias, {})[(e["type"], e["id"] or e["name"])] = e
        # Longer, fully specified aliases win. Never broaden ambiguous aliases.
        for alias, entries in sorted(hits.items(), key=lambda item: -len(item[0])):
            if any(entity_key(e) == entity_key(a) for e in entries.values() for a in analysis.entities):
                continue
            if len(entries) > 1:
                analysis.ambiguous_entity = True
                analysis.uncertainties.append("ambiguous_alias:" + alias)
                continue
            e = next(iter(entries.values()))
            analysis.entities.append(
                {**{k: e[k] for k in ("id", "name", "family", "type")}, "source": "metadata_alias"}
            )
        for e in query_models:
            if any(
                e["name"] == a["name"]
                or any(
                    alias_present(alias, e["name"])
                    for r in registry
                    if r["id"] and r["id"] == a["id"]
                    for alias in [r["name"], *r["aliases"]]
                )
                for a in analysis.entities
            ):
                continue
            analysis.entities.append({"id": "", **e, "source": "model_token", "type": "model"})
    if not analysis.entities and not analysis.ambiguous_entity:
        from cortexa.agents.knowledge import PRODUCT_FAMILIES

        for family in PRODUCT_FAMILIES:
            if family in query:
                analysis.entities.append(
                    {"id": "", "name": family, "family": family, "source": "family_constraint", "type": "family"}
                )
    if not analysis.entities and not analysis.ambiguous_entity:
        unknown_models = re.findall(
            r"(?<![A-Za-z0-9])([A-Za-z]{1,12}[- ]?\d{1,5}(?:[A-Za-z]{1,8})?)(?![A-Za-z0-9])", query
        )
        for name in unknown_models:
            analysis.entities.append(
                {"id": "", "name": normalize(name), "family": "", "source": "unresolved_token", "type": ""}
            )
            analysis.uncertainties.append("entity_not_in_metadata_registry:" + name)
    if not analysis.entities and not analysis.ambiguous_entity:
        remainder = query
        business_words = sorted(
            {w for values in [*INTENTS.values(), *DOC_TYPES.values()] for w in values}
            | {
                "查询",
                "搜索",
                "检索",
                "参考",
                "背景",
                "对比",
                "比较",
                "资料",
                "相关",
                "目标",
                "本月",
                "上个月",
                "去年",
                "今年",
                "最新",
                "制定",
                "设计",
                "安排",
                "提供",
                "做一轮",
                "一个",
                "请问",
                "请",
                "一下",
                "当前",
                "现有",
                "销售计划",
                "计划",
                "售后",
                "内部",
                "公司",
            },
            key=len,
            reverse=True,
        )
        for word in business_words:
            remainder = remainder.replace(word, "")
        remainder = re.sub(r"\d+(?:年|月|日)?|[^\w\u4e00-\u9fff]", "", remainder).strip()
        if len(remainder) > 1:
            analysis.entities.append(
                {"id": "", "name": normalize(remainder), "family": "", "source": "unresolved_phrase", "type": ""}
            )
            analysis.uncertainties.append("core_entity_phrase_unresolved:" + remainder)
    for key, words in INTENTS.items():
        if any(word in query for word in words):
            analysis.intent = key
            analysis.expansion = list(words)
            break
    for key, words in DOC_TYPES.items():
        if any(word in query for word in words):
            analysis.document_type = key
            break
    if not analysis.entities:
        analysis.uncertainties.append("core_entity_unresolved")
    if analysis.intent is None:
        analysis.uncertainties.append("intent_unresolved")
    if analysis.document_type is None:
        analysis.uncertainties.append("document_type_unresolved")
    analysis.allow_related = bool(re.search(r"参考|借鉴|模板|比较|对比|方案|制定|设计|活动|计划", query))
    analysis.allow_background = bool(re.search(r"背景|产品信息|参数|配置|手册|概况|介绍", query))
    from cortexa.agents.knowledge import PRODUCT_FAMILIES

    entity_terms = {e["name"] for e in analysis.entities}
    analysis.keywords = list(
        dict.fromkeys(
            k
            for k in _build_query_context(query)["keywords"]
            if normalize(k) not in entity_terms and k not in {"资料", "查询", "搜索", "检索", "相关", *PRODUCT_FAMILIES}
        )
    )
    return analysis


def query_variants(query, documents=(), limit=3):
    analysis = analyze_query(query, documents)
    # Deterministic synonym substitution only. Entity text and uncertainty stay
    # unchanged; never let an LLM introduce another model during expansion.
    variants = [query]
    if analysis.intent:
        original = next((w for w in INTENTS[analysis.intent] if w in query), None)
        if original:
            for word in INTENTS[analysis.intent]:
                value = query + "（业务同义词：" + word + "）"
                if value not in variants:
                    variants.append(value)
    return variants[: limit + 1]


def entity_relation(doc, full_text, analysis):
    entities = metadata_entities(doc)
    source = "metadata" if entities else "title"
    entities = entities or [{"id": "", **e} for e in models(doc.name)]
    if not entities and any(e.get("type") == "family" for e in analysis.entities):
        from cortexa.agents.knowledge import PRODUCT_FAMILIES

        entities = [
            {"id": "", "name": family, "family": family, "type": "family"}
            for family in PRODUCT_FAMILIES
            if re.search(r"(?<![\u4e00-\u9fff])" + re.escape(family) + r"(?!\s*\d)", doc.name)
        ]
    if not entities:
        source = "content"
        entities = [{"id": "", **e} for e in models(full_text)]
    if analysis.ambiguous_entity:
        return "UNKNOWN", source, [], "ambiguous_entity_constraint"
    if not analysis.entities:
        return "GENERAL", source, entities, "no_explicit_entity"
    matches, uncertain_id = [], False
    for target in analysis.entities:
        for e in entities:
            if target.get("type") and e.get("type") and target["type"] != e["type"]:
                continue
            if target["id"] and e["id"] == target["id"]:
                if (bool(target.get("type")) != bool(e.get("type"))) or (
                    not target.get("type")
                    and target["name"] != e["name"]
                    and target["name"] not in e.get("aliases", [])
                ):
                    uncertain_id = True
                    continue
            if target["id"]:
                same = (e["id"] == target["id"]) if e["id"] else bool(target["name"] and e["name"] == target["name"])
            else:
                same = bool(target["name"] and e["name"] == target["name"])
            if same:
                matches.append(entity_key(target))
    entities = list({(e.get("type"), e.get("id"), e.get("name")): e for e in entities}.values())
    title_models = models(doc.name)
    if matches and source == "metadata" and title_models:
        known_names = {name for e in entities for name in [e["name"], *e.get("aliases", [])] if name}
        if known_names and not any(e["name"] in known_names for e in title_models):
            return "UNKNOWN", source, entities, "metadata_title_entity_conflict"
    if matches:
        return "EXACT", source, entities, "exact_entity:" + ",".join(sorted(set(matches)))
    if any(
        t["family"]
        and t["family"] == e.get("family")
        and (
            not t.get("type")
            or not e.get("type")
            or t["type"] == e["type"]
            or {t["type"], e["type"]} <= {"family", "model"}
        )
        for t in analysis.entities
        for e in entities
    ):
        return "SAME_SERIES", source, entities, "same_series_is_not_same_entity"
    if uncertain_id:
        return "UNKNOWN", source, entities, "business_id_namespace_unresolved"
    if entities:
        if any(t["id"] and not t["name"] for t in analysis.entities) and not any(e["id"] for e in entities):
            return "UNKNOWN", source, entities, "business_id_not_resolved"
        return "OTHER", source, entities, "different_entity"
    return "UNKNOWN", source, [], "entity_not_established"


def document_type(doc):
    meta = getattr(doc, "metadata_json", None) or {}
    retrieval = meta.get("retrieval") if isinstance(meta.get("retrieval"), dict) else {}
    explicit = retrieval.get("document_type") or meta.get("document_type")
    if explicit:
        return explicit, "metadata"
    for kind, words in DOC_TYPES.items():
        if any(w in doc.name for w in words):
            return kind, "title"
    return None, "unknown"


def passage_supports_entity(text, analysis):
    mentioned = {m["name"] for m in models(text)}
    expected = {e["name"] for e in analysis.entities if e["name"]}
    if not mentioned or not expected:
        return True  # Numeric/ID-labelled material retains its metadata scope.
    families = {e["family"] for e in analysis.entities if e.get("type") == "family"}
    return bool(mentioned & expected) or bool(families & {m["family"] for m in models(text)})


def assess(doc, query, full_text, analysis, raw_score, algorithm="lexical"):
    relation, entity_source, entities, reason = entity_relation(doc, full_text, analysis)
    kind, type_source = document_type(doc)
    meta = getattr(doc, "metadata_json", None) or {}
    retrieval = meta.get("retrieval") if isinstance(meta.get("retrieval"), dict) else {}
    topics = retrieval.get("intents", meta.get("intents", []))
    if isinstance(topics, str):
        topics = [topics]
    if not isinstance(topics, list):
        topics = []
    text = (doc.name + "\n" + (doc.content or "") + "\n" + full_text).lower()
    words = INTENTS.get(analysis.intent, ())
    intent_hits = [w for w in words if w in text]
    title_hits = [w for w in words if w in doc.name]
    metadata_intent = bool(analysis.intent and analysis.intent in topics)
    measured_support = bool(intent_hits and re.search(r"(?:库存|销量|销售额|达成率|回款).{0,16}\d+", full_text))
    intent_match = bool(
        metadata_intent
        or title_hits
        or len(intent_hits) >= 2
        or measured_support
        or (analysis.intent == "clearance" and intent_hits)
    )
    meaningful = [k for k in analysis.keywords if k.lower() in text and not models(k)]
    type_match = analysis.document_type is None or analysis.document_type == kind
    readable = bool(full_text.strip() or (doc.content or "").strip())
    gate = "intent_support" if analysis.intent else "multi_term_support"
    semantic = (
        intent_match
        if analysis.intent
        else (
            bool(analysis.document_type and type_match)
            or len(set(meaningful)) >= 2
            or (len(analysis.keywords) == 1 and analysis.keywords[0] in doc.name)
        )
    )
    if analysis.entities and not analysis.intent and not analysis.document_type:
        semantic = False
    case_status = retrieval.get("case_status", meta.get("case_status"))
    case_verified = case_status == "completed" or bool(
        re.search(r"已执行|复盘|已完成|活动总结|执行结果|活动已结束", full_text) and re.search(r"\d", full_text)
    )
    case_verified = case_verified and case_status not in {"draft", "template", "planned"}
    hypothetical_case = bool(
        re.search(r"假设案例|模拟案例|案例模板|仅供测算|待执行|尚未执行|未执行|计划执行", full_text)
    )
    if hypothetical_case:
        case_verified = False
    if analysis.document_type == "case" and not case_verified:
        type_match = False
    draft = retrieval.get("evidence_status") in {"draft", "template", "unverified"} or bool(
        re.search(r"模板|草案|建议稿|拟定", doc.name)
    )
    grade, filters = "IRRELEVANT", []
    if not readable:
        filters.append("unreadable_content")
    elif analysis.ambiguous_entity:
        filters.append(reason)
    elif kind == "profile" and not analysis.allow_background and analysis.document_type != "profile":
        filters.append("profile_not_requested")
    elif relation == "OTHER":
        filters.append(reason)
    elif relation == "EXACT" or relation == "GENERAL":
        if semantic and type_match and (relation != "EXACT" or entity_source in {"metadata", "title"}):
            grade = "DIRECT"
        elif semantic and (kind in {"policy", "case", "report"} or entity_source == "content"):
            grade = "RELATED"
            filters.append("document_type_or_entity_scope_not_direct")
        elif (
            analysis.allow_related
            and analysis.intent in {"clearance", "marketing", "pricing"}
            and kind == "policy"
            and relation == "EXACT"
        ):
            grade = "RELATED"
            filters.append("policy_constraint_reference_only")
        elif kind == "manual" and relation == "EXACT":
            grade = "BACKGROUND"
            filters.append("manual_is_background_for_this_intent")
        else:
            filters.append("insufficient_business_relevance")
    elif relation == "SAME_SERIES" and semantic:
        grade = "RELATED"
        filters.append(reason)
    elif (
        relation == "UNKNOWN"
        and (
            semantic or (analysis.allow_related and analysis.intent in {"clearance", "marketing"} and kind == "policy")
        )
        and kind in {"policy", "report", "case"}
    ):
        grade = "RELATED"
        filters.append("generic_material_is_not_entity_evidence")
    elif kind == "profile" and analysis.allow_background:
        grade = "BACKGROUND"
    else:
        filters.append("insufficient_entity_or_business_relevance")
    if grade == "DIRECT" and analysis.entities and not passage_supports_entity(full_text, analysis):
        grade = "RELATED"
        filters.append("body_entity_scope_mismatch")
    if grade == "DIRECT" and draft:
        grade = "RELATED"
        filters.append("draft_or_template_not_fact_evidence")
    if analysis.document_type == "case" and hypothetical_case:
        filters.append("hypothetical_or_uncompleted_case")
    # Structural relevance decides admission; raw scores are only ordered
    # inside an evidence class, so BM25/RRF/cosine scales are never compared
    # against a single invented cut-off.
    specificity = {"metadata": 3, "title": 2, "content": 1}.get(entity_source, 0)
    rerank = (specificity if relation == "EXACT" else 0) + 2 * len(title_hits) + len(intent_hits) + int(type_match)
    eligible = (
        grade == "DIRECT"
        or (grade == "RELATED" and analysis.allow_related and relation not in {"SAME_SERIES", "OTHER"})
        or (grade == "BACKGROUND" and analysis.allow_background)
    )
    if grade == "RELATED" and relation == "SAME_SERIES":
        # Same-series references require an explicit comparison request.
        eligible = bool(re.search(r"对比|比较|其他车型|同系列", query)) or any(
            e.get("type") == "family" for e in analysis.entities
        )
    if not eligible and grade != "IRRELEVANT":
        filters.append("reference_not_needed_or_entity_constraint_not_expanded")
    return {
        "document_id": str(doc.id),
        "name": doc.name,
        "algorithm": algorithm,
        "raw_score": raw_score,
        "rerank_score": rerank,
        "entity_relation": relation,
        "entity_source": entity_source,
        "entities": entities,
        "evidence_scope": reason.split(":", 1)[1].split(",") if relation == "EXACT" else [],
        "document_type": kind,
        "type_source": type_source,
        "intent_hits": intent_hits,
        "evidence_grade": grade,
        "purpose": PURPOSES[grade],
        "gate_policy": algorithm + ":" + gate,
        "case_verified": case_verified,
        "eligible": eligible,
        "filter_reasons": filters,
        "entity_reason": reason,
    }


def select_documents(documents, query, full_texts, *, score_fn=None, algorithm="lexical", analysis=None):
    from cortexa.agents.knowledge import _build_query_context, _score_text

    analysis = analysis or analyze_query(query, documents)
    context = _build_query_context(query)
    scorer = score_fn or _score_text
    ranked = []
    # Recall includes metadata, summary and full text before any entity gate.
    for doc in documents:
        full = full_texts.get(str(doc.id), "")
        score = max(scorer(doc.name, doc.content or "", context), scorer(doc.name, full, context))
        decision = assess(doc, query, full, analysis, score, algorithm)
        ranked.append((decision, doc))
    order = {"DIRECT": 0, "RELATED": 1, "BACKGROUND": 2, "IRRELEVANT": 3}
    ranked.sort(
        key=lambda item: (
            order[item[0]["evidence_grade"]],
            -item[0]["rerank_score"],
            -item[0]["raw_score"],
            str(item[1].id),
        )
    )
    return analysis, ranked
