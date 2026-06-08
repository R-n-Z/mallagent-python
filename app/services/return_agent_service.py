"""退货审核 Agent 服务（对标 Java ReturnAgentService.java）

单 ReactAgent + 7 工具 + 短路逻辑 + LRU 缓存
"""

import time
from functools import lru_cache
from typing import Any, AsyncGenerator, Dict, Optional
from collections import OrderedDict
import threading

from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain_qwq import ChatQwen
from langchain_core.messages import HumanMessage
from loguru import logger

from app.config import config
from app.tools import get_return_audit_tools
from app.utils.prompt_loader import load_prompt


class LRUCache:
    """简单 LRU 缓存（对标 Java analyzeReturnText 的 LRU 缓存）"""

    def __init__(self, capacity: int = 100):
        self.cache: OrderedDict[str, str] = OrderedDict()
        self.capacity = capacity
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    def put(self, key: str, value: str):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)


class ReturnAgentService:
    """退货审核 Agent 服务"""

    def __init__(self):
        self.model = ChatQwen(
            model=config.rag_model,
            api_key=config.dashscope_api_key,
            api_base=config.dashscope_api_base,
            temperature=0.3,
        )
        # LRU 缓存 — 相同退货文本不重复调 embedding
        self.analyze_cache = LRUCache(capacity=100)
        # 用户连续拒绝计数
        self.rejection_count: Dict[str, int] = {}
        self._rejection_lock = threading.Lock()

        self.checkpointer = MemorySaver()
        self.agent = self._build_agent()
        logger.info("退货审核 Agent 初始化完成")

    def _build_agent(self):
        """构建单 ReactAgent"""
        prompt = load_prompt("audit/return_audit.md")
        return create_react_agent(
            model=self.model,
            tools=list(get_return_audit_tools()),
            prompt=prompt,
            name="return_audit_agent",
        )

    async def audit(
        self,
        apply_id: int,
        session_id: str = "default",
    ) -> Dict[str, Any]:
        """执行退货审核

        Args:
            apply_id: 退货申请ID
            session_id: 会话ID

        Returns:
            审核结果字典
        """
        logger.info(f"[Audit-Start] applyId={apply_id}")
        start_time = time.time()

        task_prompt = (
            f"请对退货申请 #{apply_id} 进行审核。"
            f"先调用 getApplyDetail 了解情况，然后自主决定需要做哪些检查、以什么顺序做。"
        )

        config_dict = {"configurable": {"thread_id": f"audit_{session_id}_{apply_id}"}}

        try:
            result = await self.agent.ainvoke(
                {"messages": [HumanMessage(content=task_prompt)]},
                config=config_dict,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            messages = result.get("messages", [])
            report = ""
            if messages:
                last_msg = messages[-1]
                report = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

            logger.info(f"[Audit-Metrics] applyId={apply_id} elapsed={elapsed_ms}ms report_len={len(report)}")

            return {
                "success": True,
                "apply_id": apply_id,
                "report": report,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"[Audit-Error] applyId={apply_id} elapsed={elapsed_ms}ms error={e}")
            return {
                "success": False,
                "apply_id": apply_id,
                "error": str(e),
                "elapsed_ms": elapsed_ms,
            }

    async def audit_stream(
        self,
        apply_id: int,
        session_id: str = "default",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式退货审核"""
        result = await self.audit(apply_id, session_id)

        if result.get("success"):
            report = result.get("report", "")
            chunk_size = 50
            for i in range(0, len(report), chunk_size):
                yield {"type": "content", "data": report[i:i + chunk_size]}
        else:
            yield {"type": "error", "data": result.get("error", "审核失败")}

        yield {"type": "complete"}

    # ==================== 拒绝计数管理 ====================

    def update_rejection_count(self, member_username: str, passed: bool):
        """更新用户连续拒绝次数"""
        with self._rejection_lock:
            if passed:
                self.rejection_count[member_username] = 0
                logger.info(f"用户 {member_username} 审核通过, 拒绝计数重置为0")
            else:
                current = self.rejection_count.get(member_username, 0)
                self.rejection_count[member_username] = current + 1
                logger.info(f"用户 {member_username} 审核拒绝, 连续拒绝次数: {current + 1}")

    def get_rejection_count(self, member_username: str) -> int:
        """获取用户连续拒绝次数"""
        return self.rejection_count.get(member_username, 0)

    # ==================== 缓存管理 ====================

    def get_cached_analysis(self, text: str) -> Optional[str]:
        """从 LRU 缓存获取分析结果"""
        return self.analyze_cache.get(text)

    def put_cached_analysis(self, text: str, result: str):
        """存入 LRU 缓存"""
        self.analyze_cache.put(text, result)


# 全局单例
return_agent_service = ReturnAgentService()
