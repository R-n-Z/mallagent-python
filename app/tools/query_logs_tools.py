"""日志查询工具（对标 Java QueryLogsTools.java）

支持 CLS 云日志查询，Mock 模式下返回模拟日志数据
"""

import json
from datetime import datetime, timezone, timedelta
from langchain_core.tools import tool
from loguru import logger

from app.config import config

# 有效地域列表
VALID_REGIONS = ["ap-guangzhou", "ap-shanghai", "ap-beijing", "ap-chengdu"]
DEFAULT_REGION = "ap-guangzhou"

# 日志主题定义
LOG_TOPICS = [
    {
        "topic_name": "system-metrics",
        "description": "系统指标日志，包含 CPU、内存、磁盘使用率等系统资源监控数据",
        "example_queries": ["cpu_usage:>80", "memory_usage:>85", "disk_usage:>90"],
        "related_alerts": ["HighCPUUsage", "HighMemoryUsage", "HighDiskUsage"],
    },
    {
        "topic_name": "application-logs",
        "description": "应用日志，包含错误日志、警告日志、慢请求日志、下游依赖调用日志等",
        "example_queries": ["level:ERROR", "level:FATAL", "http_status:500", "response_time:>3000"],
        "related_alerts": ["ServiceUnavailable", "SlowResponse", "HighMemoryUsage"],
    },
    {
        "topic_name": "database-slow-query",
        "description": "数据库慢查询日志，包含执行时间较长的 SQL 查询",
        "example_queries": ["query_time:>2", "table:orders", "*"],
        "related_alerts": ["SlowResponse", "ServiceUnavailable"],
    },
    {
        "topic_name": "system-events",
        "description": "系统事件日志，包含 Kubernetes Pod 重启、OOM Kill、容器崩溃等系统级事件",
        "example_queries": ["restart OR crash", "oom_kill", "event_type:PodRestart"],
        "related_alerts": ["ServiceUnavailable", "HighMemoryUsage"],
    },
]


@tool
def get_available_log_topics() -> str:
    """获取可用的日志主题列表。在查询日志前应先调用此工具了解有哪些日志主题可供查询。
    返回日志主题的名称、描述和示例查询。
    """
    logger.info("获取可用的日志主题列表")
    return json.dumps({
        "success": True,
        "topics": LOG_TOPICS,
        "available_regions": VALID_REGIONS,
        "default_region": DEFAULT_REGION,
        "message": f"共有 {len(LOG_TOPICS)} 个可用的日志主题。建议使用默认地域 '{DEFAULT_REGION}'",
    }, ensure_ascii=False, indent=2)


@tool
def query_logs(
    region: str = DEFAULT_REGION,
    log_topic: str = "system-metrics",
    query: str = "",
    limit: int = 20,
) -> str:
    """查询 CLS 云日志服务的日志。支持按主题和条件查询。

    可用日志主题：
    1) 'system-metrics' — 系统指标日志（CPU/内存/磁盘）
    2) 'application-logs' — 应用日志（错误/慢请求/下游依赖）
    3) 'database-slow-query' — 数据库慢查询日志
    4) 'system-events' — 系统事件日志（Pod重启/OOM等）

    Args:
        region: 地域，默认 ap-guangzhou
        log_topic: 日志主题
        query: 查询条件（Lucene 语法），为空时返回近5条核心日志
        limit: 返回条数，默认20，最大100
    """
    actual_limit = min(max(limit or 20, 1), 100)
    safe_query = (query or "").lower()
    safe_topic = (log_topic or "system-metrics").lower()

    logger.info(f"查询日志: region={region}, topic={safe_topic}, query={safe_query}")

    try:
        if config.cls_mock_enabled:
            log_entries = _build_mock_logs(safe_topic, safe_query, actual_limit)
        else:
            # 真实模式：应由 MCP 客户端注入工具
            return json.dumps({
                "success": False,
                "message": "CLS Mock 模式未启用。生产环境请通过 MCP 客户端连接真实 CLS 服务。",
            }, ensure_ascii=False)

        return json.dumps({
            "success": len(log_entries) > 0,
            "region": region,
            "log_topic": safe_topic,
            "query": safe_query or "DEFAULT_QUERY",
            "logs": log_entries,
            "total": len(log_entries),
            "message": f"成功查询到 {len(log_entries)} 条日志" if log_entries else "未找到匹配的日志",
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"查询日志失败: {e}")
        return json.dumps({"success": False, "message": f"查询失败: {str(e)}"}, ensure_ascii=False)


def _now_iso(offset_minutes: int = 0) -> str:
    """生成 ISO 格式时间字符串"""
    dt = datetime.now() + timedelta(minutes=offset_minutes)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _build_mock_logs(topic: str, query: str, limit: int) -> list[dict]:
    """构建 Mock 日志数据"""
    logs = []

    if topic == "system-metrics":
        if "cpu" in query or ">80" in query:
            for i in range(min(5, limit)):
                logs.append({
                    "timestamp": _now_iso(-i * 2),
                    "level": "WARN",
                    "service": "payment-service",
                    "instance": "pod-payment-service-7d8f9c6b5-x2k4m",
                    "message": f"CPU使用率过高: {92.0 - i * 1.5:.1f}%, 进程: java (PID: 1), 线程数: 245",
                    "metrics": {"cpu_usage": f"{92.0 - i * 1.5:.1f}", "cpu_cores": "4"},
                })
        if "memory" in query or ">85" in query or "oom" in query:
            for i in range(min(5, limit)):
                logs.append({
                    "timestamp": _now_iso(-i * 3),
                    "level": "WARN",
                    "service": "order-service",
                    "instance": "pod-order-service-5c7d8e9f1-m3n2p",
                    "message": f"内存使用率过高: {91.0 - i * 1.2:.1f}%, JVM堆: {3.8 - i * 0.1:.1f}GB/4GB",
                    "metrics": {"memory_usage": f"{91.0 - i * 1.2:.1f}", "jvm_heap_max": "4GB"},
                })

    elif topic == "application-logs":
        if "error" in query or "fatal" in query or "500" in query:
            logs.append({
                "timestamp": _now_iso(-5),
                "level": "ERROR",
                "service": "order-service",
                "instance": "pod-order-service-5c7d8e9f1-m3n2p",
                "message": "数据库连接池耗尽: Cannot acquire connection from pool, active: 50/50, waiting: 23",
                "metrics": {"error_type": "ConnectionPoolExhaustedException"},
            })
            logs.append({
                "timestamp": _now_iso(-12),
                "level": "FATAL",
                "service": "order-service",
                "instance": "pod-order-service-5c7d8e9f1-m3n2p",
                "message": "java.lang.OutOfMemoryError: Java heap space",
                "metrics": {"error_type": "OutOfMemoryError", "heap_max": "4GB"},
            })
        if "slow" in query or ">3000" in query:
            for i in range(min(3, limit)):
                logs.append({
                    "timestamp": _now_iso(-i * 2),
                    "level": "WARN",
                    "service": "user-service",
                    "instance": "pod-user-service-8e9f0a1b2-k5j6h",
                    "message": f"慢请求: /api/v1/users/profile, 响应时间: {4200 - i * 150}ms",
                    "metrics": {"response_time_ms": str(4200 - i * 150)},
                })
        if "redis" in query or "database" in query or "mq" in query or "downstream" in query:
            logs.append({
                "timestamp": _now_iso(-7),
                "level": "ERROR",
                "service": "payment-service",
                "message": "Redis 连接超时: 无法连接到 Redis 集群 redis-cluster-01:6379",
                "metrics": {"dependency": "redis"},
            })

    elif topic == "database-slow-query":
        logs.extend([
            {
                "timestamp": _now_iso(-3),
                "level": "WARN",
                "service": "mysql",
                "instance": "mysql-primary-01",
                "message": "慢查询: SELECT * FROM orders WHERE user_id=? 执行时间: 3.2s, 扫描行数: 1,245,678",
                "metrics": {"query_time_sec": "3.2", "table": "orders"},
            },
            {
                "timestamp": _now_iso(-8),
                "level": "WARN",
                "service": "mysql",
                "message": "慢查询: UPDATE orders SET status=? 执行时间: 4.5s, 锁等待: 2.1s",
                "metrics": {"query_time_sec": "4.5", "lock_time_sec": "2.1"},
            },
        ])

    elif topic == "system-events":
        if "restart" in query or "crash" in query or "oom_kill" in query:
            logs.append({
                "timestamp": _now_iso(-15),
                "level": "WARN",
                "service": "kubernetes",
                "message": "Pod 重启事件: pod-order-service-xxx, 原因: OOMKilled, 重启次数: 3",
                "metrics": {"event_type": "PodRestart", "reason": "OOMKilled"},
            })

    # 如果无匹配，返回通用日志
    if not logs:
        for i in range(min(limit, 5)):
            logs.append({
                "timestamp": _now_iso(-i),
                "level": "INFO",
                "service": "generic-service",
                "message": f"日志消息 #{i}",
                "metrics": {},
            })

    return logs[:limit]
