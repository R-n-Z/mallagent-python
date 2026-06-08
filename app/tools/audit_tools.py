"""退货审核工具集

对标 Java audit/ 目录下的 7 个工具类：
- ReturnRuleKnowledgeTools.java → query_auto_approve_rules / check_escalation_keywords / query_strict_reject_rules / query_receipt_thresholds
- ReturnOrderTools.java → get_apply_detail / get_order_time
- ReturnAuditTools.java → get_user_history / get_reject_count
- DateTimeCalculateTools.java → calculate_receive_days
- ExactMatchTools.java → exact_match_keywords
- HybridSearchTools.java → hybrid_keyword_search / analyze_return_text
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from functools import lru_cache

import httpx
from langchain_core.tools import tool
from loguru import logger

from app.config import config

# ==================== 规则数据加载 ====================

RULES_PATH = Path(__file__).parent.parent.parent / "data" / "audit" / "rules.json"

_rules_cache: Optional[dict] = None


def _load_rules() -> dict:
    """加载退货审核规则 JSON（带缓存）"""
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            _rules_cache = json.load(f)
        logger.info(f"退货审核规则加载成功, 版本: {_rules_cache.get('version', 'unknown')}")
        return _rules_cache
    except Exception as e:
        logger.error(f"退货审核规则加载失败: {e}")
        _rules_cache = {}
        return _rules_cache


# ==================== 规则知识库工具 ====================


@tool
def query_auto_approve_rules() -> str:
    """查询自动通过退货的规则条件。返回允许自动通过的退货原因列表、收货天数上限、必要条件。"""
    rules = _load_rules()
    if not rules:
        return json.dumps({"error": "规则知识库未加载"}, ensure_ascii=False)
    return json.dumps(rules.get("autoApproveRules", []), ensure_ascii=False, indent=2)


@tool
def check_escalation_keywords(reason: str, description: str = "") -> str:
    """检查退货申请中是否包含需要转人工处理的关键词。输入退货原因和描述，返回命中的关键词及处理建议。

    Args:
        reason: 退货原因
        description: 退货描述（可选）
    """
    rules = _load_rules()
    if not rules:
        return json.dumps({"error": "规则知识库未加载"}, ensure_ascii=False)

    combined = (reason + " " + (description or "")).lower()
    keywords = rules.get("escalationKeywords", [])
    matches = []

    for kw in keywords:
        word = kw.get("keyword", "").lower()
        if word and word in combined:
            matches.append(kw)

    if not matches:
        return json.dumps({
            "escalationNeeded": False,
            "message": "未命中转人工关键词",
            "matches": [],
        }, ensure_ascii=False)

    return json.dumps({
        "escalationNeeded": True,
        "message": f"命中 {len(matches)} 个转人工关键词",
        "matches": matches,
    }, ensure_ascii=False)


@tool
def query_strict_reject_rules(product_name: str = "", product_attr: str = "") -> str:
    """查询严格不允许退货的商品规则。输入商品名称和属性，返回匹配的拒绝规则。

    Args:
        product_name: 商品名称
        product_attr: 商品属性（品类等）
    """
    rules = _load_rules()
    if not rules:
        return json.dumps({"error": "规则知识库未加载"}, ensure_ascii=False)

    combined = ((product_name or "") + " " + (product_attr or "")).lower()
    strict_rules = rules.get("strictRejectRules", [])
    matches = []

    for rule in strict_rules:
        for kw in rule.get("productKeywords", []):
            if kw.lower() in combined:
                matches.append(rule)
                break

    if not matches:
        return json.dumps({
            "strictRejectMatched": False,
            "message": "未命中严格拒绝规则",
            "rules": [],
        }, ensure_ascii=False)

    return json.dumps({
        "strictRejectMatched": True,
        "message": f"命中 {len(matches)} 条严格拒绝规则",
        "rules": matches,
    }, ensure_ascii=False)


@tool
def query_receipt_thresholds() -> str:
    """查询收货天数阈值规则。返回允许无理由退货的天数、有条件退货的天数范围、严格审查和直接拒绝的天数阈值。"""
    rules = _load_rules()
    if not rules:
        return json.dumps({"error": "规则知识库未加载"}, ensure_ascii=False)
    return json.dumps(rules.get("receiptDayThresholds", {}), ensure_ascii=False, indent=2)


# ==================== 订单/申请查询工具 ====================


@tool
def get_apply_detail(apply_id: int) -> str:
    """查询退货申请详情。输入 applyId，返回完整申请信息（商品属性、退货原因、用户信息）。

    Args:
        apply_id: 退货申请ID
    """
    logger.info(f"查询退货申请详情: applyId={apply_id}")
    try:
        url = f"{config.mall_admin_base_url}/returnApply/{apply_id}"
        with httpx.Client(timeout=30) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        logger.error(f"查询退货申请详情失败: {e}")
        return json.dumps({"error": f"查询退货申请失败: {str(e)}"}, ensure_ascii=False)


@tool
def get_order_time(order_id: int) -> str:
    """查询订单收货时间。输入 orderId，返回收货时间、发货时间、支付时间等。

    Args:
        order_id: 订单ID
    """
    logger.info(f"查询订单收货时间: orderId={order_id}")
    try:
        url = f"{config.mall_admin_base_url}/returnApply/audit/order/{order_id}"
        with httpx.Client(timeout=30) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        logger.error(f"查询订单收货时间失败: {e}")
        return json.dumps({"error": f"查询订单信息失败: {str(e)}"}, ensure_ascii=False)


# ==================== 用户历史工具 ====================


@tool
def get_user_history(member_username: str) -> str:
    """查询用户历史退货申请记录。输入用户名，返回最近10条退货申请。

    Args:
        member_username: 用户名
    """
    logger.info(f"查询用户退货历史: memberUsername={member_username}")
    try:
        url = f"{config.mall_admin_base_url}/returnApply/audit/history"
        params = {"memberUsername": member_username, "limit": 10}
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        return json.dumps({"error": "查询退货历史失败"}, ensure_ascii=False)


@tool
def get_reject_count(member_username: str) -> str:
    """查询用户最近连续被拒绝的退货申请次数。输入用户名，返回连续拒绝次数。

    Args:
        member_username: 用户名
    """
    try:
        url = f"{config.mall_admin_base_url}/returnApply/audit/history"
        params = {"memberUsername": member_username, "limit": 10}
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        # 计数连续拒绝
        items = data.get("data", data)
        if isinstance(items, dict):
            items = items.get("list", [])
        if not isinstance(items, list):
            items = []

        consecutive = 0
        for item in items:
            status = item.get("status", -1)
            if status == 3:
                consecutive += 1
            else:
                break

        return json.dumps({
            "memberUsername": member_username,
            "consecutiveRejections": consecutive,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": "查询失败", "consecutiveRejections": -1}, ensure_ascii=False)


# ==================== 时间计算工具 ====================

_DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
]


def _parse_datetime(time_str: str) -> Optional[datetime]:
    """解析多种格式的日期时间字符串"""
    if not time_str or not time_str.strip():
        return None
    cleaned = time_str.strip().replace("Z", "").replace("z", "")
    if len(cleaned) >= 19:
        cleaned = cleaned[:19]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


@tool
def calculate_receive_days(receive_time: str, apply_time: str = "") -> str:
    """计算收货天数。输入收货时间，返回距今天数和窗口判定(WITHIN_7_DAYS/WITHIN_15_DAYS/OVER_15_DAYS)。

    Args:
        receive_time: 收货时间字符串 (如 "2025-05-28 14:30:00")
        apply_time: 申请时间字符串，不传则使用当前时间
    """
    logger.info(f"计算收货天数: receiveTime={receive_time}, applyTime={apply_time}")
    try:
        receive = _parse_datetime(receive_time)
        if apply_time and apply_time.strip():
            apply_dt = _parse_datetime(apply_time)
        else:
            apply_dt = datetime.now()

        if not receive:
            return json.dumps({
                "error": "时间解析失败",
                "receiveTime": receive_time,
                "applyTime": apply_time or str(datetime.now()),
            }, ensure_ascii=False)

        delta = apply_dt - receive
        days = delta.days
        hours = int(delta.total_seconds() // 3600)

        if days <= 7:
            threshold = "WITHIN_7_DAYS"
        elif days <= 15:
            threshold = "WITHIN_15_DAYS"
        else:
            threshold = "OVER_15_DAYS"

        return json.dumps({
            "receiveTime": receive_time,
            "applyTime": apply_time or apply_dt.isoformat(),
            "daysSinceReceive": days,
            "hoursSinceReceive": hours,
            "threshold": threshold,
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"计算收货天数失败: {e}")
        return json.dumps({"error": f"计算失败: {str(e)}"}, ensure_ascii=False)


# ==================== 精确匹配 + 混合检索 ====================


def _levenshtein(a: str, b: str) -> int:
    """计算编辑距离"""
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        dp[i][0] = i
    for j in range(len(b) + 1):
        dp[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[len(a)][len(b)]


@lru_cache(maxsize=1)
def _build_exact_index() -> dict:
    """构建精确匹配索引（从 rules.json 构建三层漏斗）"""
    rules = _load_rules()
    if not rules:
        return {"exact": {}, "synonyms": {}, "short": []}

    exact_index = {}
    synonym_map = {}
    short_keywords = []
    max_kw_len = config.rule_rag_fuzzy_max_keyword_length

    # escalationKeywords
    for kw in rules.get("escalationKeywords", []):
        word = kw["keyword"].lower()
        exact_index[word] = kw
        if len(word) <= max_kw_len:
            short_keywords.append(word)
        for syn in kw.get("synonyms", []):
            synonym_map.setdefault(syn.lower(), word)

    # strictRejectRules.productKeywords
    for rule in rules.get("strictRejectRules", []):
        for kw in rule.get("productKeywords", []):
            word = kw.lower()
            exact_index[word] = rule
            if len(word) <= max_kw_len:
                short_keywords.append(word)

    # autoApproveRules.allowedReasons
    for rule in rules.get("autoApproveRules", []):
        for kw in rule.get("allowedReasons", []):
            word = kw.lower()
            exact_index[word] = rule
            if len(word) <= max_kw_len:
                short_keywords.append(word)

    # 同义词
    for rule_list_key in ["escalationKeywords", "strictRejectRules", "autoApproveRules"]:
        for node in rules.get(rule_list_key, []):
            for syn in node.get("synonyms", []):
                # 找主关键词
                if rule_list_key == "escalationKeywords":
                    main = node["keyword"].lower()
                elif rule_list_key == "strictRejectRules":
                    main = node.get("productKeywords", [""])[0].lower()
                else:
                    main = node.get("allowedReasons", [""])[0].lower()
                synonym_map.setdefault(syn.lower(), main)

    return {
        "exact": exact_index,
        "synonyms": synonym_map,
        "short": list(set(short_keywords)),
    }


@tool
def exact_match_keywords(text: str) -> str:
    """精确匹配规则关键词（含同义词扩展和错别字模糊匹配）。输入一段文本，返回命中的规则关键词及其匹配方式。
    三层漏斗：精确匹配 → 同义词扩展 → 编辑距离模糊匹配。

    Args:
        text: 需要检查的文本
    """
    if not text or not text.strip():
        return json.dumps({"matches": []}, ensure_ascii=False)

    lower = text.lower()
    idx = _build_exact_index()
    exact_index = idx["exact"]
    synonym_map = idx["synonyms"]
    short_keywords = idx["short"]

    matches = []

    # 第一层：精确匹配
    for word, rule in exact_index.items():
        if word in lower:
            matches.append(_build_match(word, rule, "exact", 1.0))

    # 第二层：同义词匹配
    matched_keywords = {m["keyword"] for m in matches}
    for syn, original in synonym_map.items():
        if syn in lower and original not in matched_keywords:
            rule = exact_index.get(original)
            matches.append(_build_match(original, rule, "synonym", 0.9))
            matched_keywords.add(original)

    # 第三层：编辑距离模糊匹配（仅 ≥4 字长词）
    max_rel_dist = config.rule_rag_fuzzy_max_relative_distance
    for keyword in short_keywords:
        if len(keyword) < 4:
            continue
        if keyword in matched_keywords:
            continue

        kw_len = len(keyword)
        for i in range(len(lower) - max(1, kw_len - 2) + 1):
            for end in range(i + max(1, kw_len - 2), min(len(lower), i + kw_len + 3)):
                substr = lower[i:end]
                if abs(len(substr) - kw_len) > 1:
                    continue
                dist = _levenshtein(keyword, substr)
                rel_dist = dist / max(kw_len, len(substr))
                if rel_dist <= max_rel_dist:
                    rule = exact_index.get(keyword)
                    matches.append(_build_match(keyword, rule, "fuzzy", 0.7))
                    matched_keywords.add(keyword)
                    break
            if keyword in matched_keywords:
                break

    return json.dumps({
        "totalMatches": len(matches),
        "matches": matches,
    }, ensure_ascii=False)


def _build_match(keyword: str, rule: dict | None, source: str, score: float) -> dict:
    m = {
        "keyword": keyword,
        "source": source,
        "score": score,
    }
    if rule:
        m["category"] = rule.get("category", "")
        m["priority"] = rule.get("priority", "")
        m["ruleId"] = rule.get("ruleId", "")
    return m


@tool
def analyze_return_text(text: str) -> str:
    """语义分析退货文本 — 混合检索 + 精确匹配封装。输入退货原因+描述文本，输出按 escalation/strict_reject/auto_approve 分组的命中结果。

    Args:
        text: 需要分析的退货文本（退货原因 + 描述）
    """
    if not text or not text.strip():
        return json.dumps({
            "escalation": [],
            "strict_reject": [],
            "auto_approve": [],
            "hints": [],
        }, ensure_ascii=False)

    # 精确路
    exact_result = json.loads(exact_match_keywords(text))

    # 分类
    escalation = []
    strict_reject = []
    auto_approve = []

    rules = _load_rules()
    esc_keywords = {kw["keyword"] for kw in rules.get("escalationKeywords", [])}
    strict_keywords = set()
    for rule in rules.get("strictRejectRules", []):
        for kw in rule.get("productKeywords", []):
            strict_keywords.add(kw)
    auto_keywords = set()
    for rule in rules.get("autoApproveRules", []):
        for kw in rule.get("allowedReasons", []):
            auto_keywords.add(kw)

    for match in exact_result.get("matches", []):
        kw = match.get("keyword", "")
        entry = {"k": kw, "s": match.get("score", 0)}
        if kw in esc_keywords:
            escalation.append(entry)
        elif kw in strict_keywords:
            strict_reject.append(entry)
        elif kw in auto_keywords:
            auto_approve.append(entry)

    hints = []
    if escalation:
        hints.append("升级词命中，需语境判断")
    if strict_reject:
        hints.append("严格拒绝品类命中，优先检查品类限制")

    return json.dumps({
        "escalation": escalation,
        "strict_reject": strict_reject,
        "auto_approve": auto_approve,
        "hints": hints,
    }, ensure_ascii=False)
