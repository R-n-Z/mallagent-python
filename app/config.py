"""配置管理模块

使用 Pydantic Settings 实现类型安全的配置管理

对标 Java application.yml 的所有配置项
"""

from typing import Dict, Any
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ==================== 应用配置 ====================
    app_name: str = "SuperBizAgent"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9900

    # ==================== DashScope 配置 ====================
    dashscope_api_key: str = ""
    dashscope_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen-max"
    dashscope_embedding_model: str = "text-embedding-v4"  # v4 支持多种维度（默认 1024）
    dashscope_timeout: int = 180000  # 超时毫秒（3分钟）
    dashscope_max_retries: int = 3
    dashscope_retry_initial_interval: int = 2000  # 初始重试间隔 ms
    dashscope_retry_multiplier: int = 2
    dashscope_retry_max_interval: int = 10000  # 最大重试间隔 ms

    # ==================== Milvus 配置 ====================
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_username: str = ""
    milvus_password: str = ""
    milvus_database: str = "default"
    milvus_timeout: int = 10000  # 毫秒

    # ==================== RAG 配置 ====================
    rag_top_k: int = 3
    rag_model: str = "qwen3-max"  # 对齐 Java，使用 qwen3-max

    # ==================== 文档分块配置 ====================
    chunk_max_size: int = 800
    chunk_overlap: int = 100

    # ==================== MCP 服务配置 ====================
    mcp_enabled: bool = False
    mcp_cls_transport: str = "streamable-http"
    mcp_cls_url: str = "http://localhost:8003/mcp"
    mcp_monitor_transport: str = "streamable-http"
    mcp_monitor_url: str = "http://localhost:8004/mcp"

    # ==================== Prometheus 配置 ====================
    prometheus_base_url: str = "http://127.0.0.1:9090"
    prometheus_request_timeout: float = 10.0
    prometheus_mock_enabled: bool = False  # Mock 模式开关

    # ==================== CLS 云日志配置 ====================
    cls_mock_enabled: bool = True  # MCP 未启用时使用模拟数据

    # ==================== Mall Admin 服务地址 ====================
    mall_admin_base_url: str = "http://localhost:8080"

    # ==================== 退货审核配置 ====================
    return_audit_rejection_max_consecutive: int = 3  # 连续拒绝次数上限
    return_audit_receipt_unconditional_days: int = 7   # 七天无理由退货
    return_audit_receipt_conditional_days: int = 15    # 超15天一般不允许

    # ==================== 规则 RAG 混合检索配置 ====================
    rule_rag_enabled: bool = True
    rule_rag_hybrid_vector_top_k: int = 6          # 向量路返回 top K
    rule_rag_hybrid_vector_threshold: float = 0.26  # 语义相似度最低阈值
    rule_rag_hybrid_keyword_weight: float = 0.30    # 精确路得分乘数
    rule_rag_hybrid_vector_weight: float = 0.65     # 向量路得分乘数
    rule_rag_fuzzy_max_relative_distance: float = 0.35  # 相对编辑距离上限
    rule_rag_fuzzy_max_keyword_length: int = 10         # 仅对 ≤10 字的词做模糊匹配

    # ==================== 文件上传配置 ====================
    file_upload_path: str = "./uploads"
    file_upload_allowed_extensions: str = "txt,md"

    @property
    def allowed_extensions_list(self) -> list[str]:
        """获取允许上传的扩展名列表"""
        return [ext.strip() for ext in self.file_upload_allowed_extensions.split(",")]

    @property
    def mcp_servers(self) -> Dict[str, Dict[str, Any]]:
        """获取完整的 MCP 服务器配置"""
        return {
            "cls": {
                "transport": self.mcp_cls_transport,
                "url": self.mcp_cls_url,
            },
            "monitor": {
                "transport": self.mcp_monitor_transport,
                "url": self.mcp_monitor_url,
            }
        }

    @property
    def rule_hybrid_search_params(self) -> Dict[str, Any]:
        """混合检索参数字典，方便传给搜索函数"""
        return {
            "vector_top_k": self.rule_rag_hybrid_vector_top_k,
            "vector_threshold": self.rule_rag_hybrid_vector_threshold,
            "keyword_weight": self.rule_rag_hybrid_keyword_weight,
            "vector_weight": self.rule_rag_hybrid_vector_weight,
            "fuzzy_max_relative_distance": self.rule_rag_fuzzy_max_relative_distance,
            "fuzzy_max_keyword_length": self.rule_rag_fuzzy_max_keyword_length,
        }


# 全局配置实例
config = Settings()
