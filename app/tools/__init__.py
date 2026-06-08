"""工具模块 - 供 Agent 调用的各种工具

无依赖工具模块级导入；Milvus/DashScope 依赖工具通过工厂函数懒加载
"""

# === 无依赖工具（模块级直接导入，不会触发 Milvus/Embedding 初始化） ===
from app.tools.time_tool import get_current_time
from app.tools.query_metrics_alerts import query_prometheus_alerts
from app.tools.query_logs_tools import query_logs, get_available_log_topics
from app.tools.audit_tools import (
    query_auto_approve_rules,
    check_escalation_keywords,
    query_strict_reject_rules,
    query_receipt_thresholds,
    get_apply_detail,
    get_order_time,
    get_user_history,
    get_reject_count,
    calculate_receive_days,
    exact_match_keywords,
    analyze_return_text,
)


def _get_retrieve_knowledge():
    """懒加载知识库检索（依赖 Milvus + Embedding）"""
    from app.tools.knowledge_tool import retrieve_knowledge
    return retrieve_knowledge


def _get_search_faq():
    """懒加载 FAQ 搜索（依赖 Milvus + Embedding）"""
    from app.tools.faq_tools import search_faq
    return search_faq


# === 工具集工厂函数（用于 Agent 初始化时调用） ===

def get_default_tools():
    """获取默认本地工具集"""
    return (
        _get_retrieve_knowledge(),
        get_current_time,
        query_prometheus_alerts,
        query_logs,
        get_available_log_topics,
    )


def get_customer_service_tools():
    """获取客服 Agent 工具集"""
    return (
        _get_search_faq(),
        get_current_time,
    )


def get_post_sales_tools():
    """获取售后 Agent 工具集"""
    return (
        _get_search_faq(),
        query_strict_reject_rules,
        query_auto_approve_rules,
        query_receipt_thresholds,
        calculate_receive_days,
        check_escalation_keywords,
    )


def get_return_audit_tools():
    """获取退货审核 Agent 工具集"""
    return (
        get_apply_detail,
        get_reject_count,
        analyze_return_text,
        query_strict_reject_rules,
        query_auto_approve_rules,
        query_receipt_thresholds,
        get_order_time,
        calculate_receive_days,
    )


# 兼容旧代码引用（模块级属性，非函数）
DEFAULT_LOCAL_AGENT_TOOLS = get_default_tools  # 别名
CUSTOMER_SERVICE_TOOLS = get_customer_service_tools
POST_SALES_TOOLS = get_post_sales_tools
RETURN_AUDIT_TOOLS = get_return_audit_tools


__all__ = [
    "get_default_tools",
    "get_customer_service_tools",
    "get_post_sales_tools",
    "get_return_audit_tools",
    "DEFAULT_LOCAL_AGENT_TOOLS",
    "CUSTOMER_SERVICE_TOOLS",
    "POST_SALES_TOOLS",
    "RETURN_AUDIT_TOOLS",
    "get_current_time",
    "query_prometheus_alerts",
    "query_logs",
    "get_available_log_topics",
    "query_auto_approve_rules",
    "check_escalation_keywords",
    "query_strict_reject_rules",
    "query_receipt_thresholds",
    "get_apply_detail",
    "get_order_time",
    "get_user_history",
    "get_reject_count",
    "calculate_receive_days",
    "exact_match_keywords",
    "analyze_return_text",
]
