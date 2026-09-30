"""Deterministic memory policy; no database or model calls."""

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import jieba
from .schemas import MemoryConfig

CATEGORIES = {"semantic", "episodic", "focus"}
STATUSES = {"candidate", "active", "superseded", "expired", "retracted", "archived", "rejected"}
POLICY_VERSION = "memory2.1"
STOP = {"用户", "记住", "请", "什么", "怎么", "一下", "一个", "可以", "现在", "去年", "今年", "的是", "我们", "agent"}
SYNONYMS = {
    "简洁": "简短",
    "不要太长": "简短",
    "短一点": "简短",
    "汇报": "报告",
    "材料": "报告",
    "管理层": "管理",
    "喜欢": "偏好",
    "希望": "偏好",
}


def now():
    return datetime.now(timezone.utc)


def normalize(content):
    value = unicodedata.normalize("NFKC", content).lower()
    for word, replacement in SYNONYMS.items():
        value = value.replace(word, replacement)
    return re.sub(r"\s+", " ", value).strip()


def terms(content):
    text = normalize(content)
    words = {
        w.strip() for w in jieba.cut(text) if len(w.strip()) >= 2 and w.strip() not in STOP and re.search(r"\w", w)
    }
    # Bigrams help Chinese name/phrase matches without a vector service.
    for part in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(part[i : i + 2] for i in range(len(part) - 1) if part[i : i + 2] not in STOP)
    return sorted(words)[:256]


def digest(value):
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(value.encode()).hexdigest()


def config(agent):
    data = (getattr(agent, "memory_config", None) or {}).get("memory2", {})
    return MemoryConfig.model_validate(data or {})


def sensitive(content):
    return bool(
        re.search(
            r"(?:密码|口令|密钥|api[_ -]?key|secret|token)\s*[:：=]|-----BEGIN .*PRIVATE KEY|\b(?:sk-|AKIA)[A-Za-z0-9]{12,}",
            content,
            re.I,
        )
    )


def high_risk(content):
    return bool(
        re.search(r"人事评价|解雇|开除|违法|违法行为|法律责任|犯罪|重大财务|贪污|受贿|破产|董事会决策", content)
    )


def time_window(query, at=None):
    at = at or now()
    local = at.astimezone(ZoneInfo("Asia/Shanghai"))
    dates = re.findall(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})日?", query)
    if dates:
        try:
            year, month, day = map(int, dates[0])
            start = datetime(year, month, day, tzinfo=local.tzinfo).astimezone(timezone.utc)
            return start, start + timedelta(days=1), True
        except ValueError:
            return at, at, False
    year = local.year - 1 if "去年" in query else local.year if "今年" in query else None
    match = re.search(r"(20\d{2})年", query)
    if match:
        year = int(match.group(1))
    if year:
        return (
            datetime(year, 1, 1, tzinfo=local.tzinfo).astimezone(timezone.utc),
            datetime(year + 1, 1, 1, tzinfo=local.tzinfo).astimezone(timezone.utc),
            True,
        )
    return at, at, False


def filter_reason(mem, start, end, historical=False):
    meta = mem.metadata_json or {}
    if meta.get("content_purged") or meta.get("source_review_required"):
        return "source_unavailable"
    if mem.status in {"candidate", "rejected", "retracted", "archived"}:
        return "status"
    if mem.risk_level == "high" and not meta.get("risk_approved"):
        return "risk"
    if historical:
        if mem.type == "episodic":
            if mem.occurred_at is None:
                return "unknown_event_time"
            if not start <= mem.occurred_at < end:
                return "event_time"
        else:
            if mem.valid_from is None and mem.valid_to is None:
                return "unknown_validity"
            if mem.valid_from and mem.valid_from >= end:
                return "not_yet_valid"
            if mem.valid_to and mem.valid_to <= start:
                return "validity_ended"
    else:
        if mem.status != "active":
            return "status"
        if mem.valid_from and mem.valid_from > start:
            return "not_yet_valid"
        if mem.valid_to and mem.valid_to <= start:
            return "validity_ended"
        if mem.expires_at and mem.expires_at <= start:
            return "expired"
    return None


def relevance(query_terms, mem):
    words = set(mem.search_terms or terms(mem.content))
    if not query_terms:
        return 0.0
    return len(set(query_terms) & words) / len(set(query_terms))


# Explicit "请记住" facts must survive verbose natural questions: lexical
# overlap shrinks as the query grows (1 hit in 8 query terms = 0.125), so the
# generic threshold would silently hide memories the user explicitly stored.
EXPLICIT_RELEVANCE_FLOOR = 0.1


def relevance_threshold(cfg, mem):
    if getattr(mem, "source_mode", None) == "explicit":
        return min(cfg.relevance_threshold, EXPLICIT_RELEVANCE_FLOOR)
    return cfg.relevance_threshold


def token_estimate(text):
    # Deliberately conservative for Chinese and identifiers; no exact-token claim.
    return len(text) + 16
