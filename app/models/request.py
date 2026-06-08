"""请求数据模型

定义 API 请求的 Pydantic 模型
"""

from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """对话请求 — 兼容两种格式：
    1. 旧格式: {"Id": "...", "Question": "..."}
    2. Java ContextEnvelope 格式: {"user": {...}, "product": {...}, "message": {...}}
    """

    id: Optional[str] = Field(None, description="会话 ID", alias="Id")
    question: Optional[str] = Field(None, description="用户问题", alias="Question")
    product_name: Optional[str] = Field(None, alias="productName")

    # ContextEnvelope 子字段 (raw dict)
    user: Optional[Dict[str, Any]] = Field(None)
    product: Optional[Dict[str, Any]] = Field(None)
    message: Optional[Dict[str, Any]] = Field(None)
    session_id: Optional[str] = Field(None, alias="sessionId")
    history: Optional[List[Dict[str, Any]]] = Field(None)

    class Config:
        populate_by_name = True
        extra = "allow"


class ClearRequest(BaseModel):
    """清空会话请求"""

    session_id: str = Field(..., description="会话 ID", alias="sessionId")

    class Config:
        populate_by_name = True


class ReturnAuditRequest(BaseModel):
    """退货审核请求"""

    apply_id: int = Field(..., description="退货申请ID", alias="applyId")
    session_id: str = Field("default", alias="sessionId")

    class Config:
        populate_by_name = True


class SyncContextRequest(BaseModel):
    """同步上下文请求（商家端回复后同步到 Agent 会话）"""

    session_id: str = Field(..., alias="sessionId")
    message: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        populate_by_name = True
        extra = "allow"
