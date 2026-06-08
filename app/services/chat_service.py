"""客服多智能体服务（对标 Java ChatService.java）

SupervisorAgent + 4 子 Agent：售前 / 售后 / 升级 / 闲聊

架构：
- Supervisor: LLM 路由节点，根据用户问题和上下文选择子 Agent
- pre_sales_agent:  售前咨询（商品/价格/对比/推荐）
- post_sales_agent: 售后支持（退货/退款/物流/保修）
- escalation_agent: 人工升级（投诉/复杂问题）
- chitchat_agent:   闲聊处理（问候/感谢/无关话题）
"""

from typing import Annotated, Any, AsyncGenerator, Dict, Sequence, Optional
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain_qwq import ChatQwen
from typing_extensions import TypedDict
from loguru import logger

from app.config import config
from app.tools import (
    get_customer_service_tools,
    get_post_sales_tools,
    get_current_time,
)
from app.tools.faq_tools import search_faq
from app.utils.prompt_loader import load_prompt


# ==================== 状态定义 ====================

class ChatAgentState(TypedDict):
    """客服 Agent 状态"""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    next_agent: str  # 下一个要调用的 Agent 名称
    final_answer: str  # 最终回复


# ==================== 对话状态（多轮记忆） ====================

@dataclass
class ConversationState:
    """结构化对话状态 — 对标 Java ConversationState.java"""
    turn_count: int = 0
    last_intent: str = ""
    entities: list[str] = field(default_factory=list)
    last_user_message: str = ""
    last_assistant_message: str = ""

    def record_turn(self, user_msg: str, assistant_msg: str, intent: str = ""):
        self.turn_count += 1
        self.last_user_message = user_msg
        self.last_assistant_message = assistant_msg
        if intent:
            self.last_intent = intent

    def add_entity(self, entity: str):
        if entity not in self.entities:
            self.entities.append(entity)

    def to_prompt_context(self) -> str:
        parts = [f"对话轮次: {self.turn_count}"]
        if self.last_intent:
            parts.append(f"最近意图: {self.last_intent}")
        if self.entities:
            parts.append(f"提及实体: {', '.join(self.entities[-5:])}")
        return "\n".join(parts)


# ==================== 客服 Agent 服务 ====================

class ChatService:
    """客服多智能体服务"""

    def __init__(self):
        self.model = ChatQwen(
            model=config.rag_model,
            api_key=config.dashscope_api_key,
            api_base=config.dashscope_api_base,
            temperature=0.5,
        )
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()
        logger.info("客服 SupervisorAgent 初始化完成")

    # ==================== 子 Agent 构建 ====================

    def _build_pre_sales_agent(self):
        """售前咨询 Agent"""
        prompt = load_prompt("chat/pre_sales.md")
        return create_react_agent(
            model=self.model,
            tools=[search_faq],
            prompt=prompt,
            name="pre_sales_agent",
        )

    def _build_post_sales_agent(self):
        """售后支持 Agent"""
        prompt = load_prompt("chat/post_sales.md")
        return create_react_agent(
            model=self.model,
            tools=list(get_post_sales_tools()),
            prompt=prompt,
            name="post_sales_agent",
        )

    def _build_escalation_agent(self):
        """人工升级 Agent"""
        prompt = load_prompt("chat/escalation.md")
        return create_react_agent(
            model=self.model,
            tools=[],
            prompt=prompt,
            name="escalation_agent",
        )

    def _build_chitchat_agent(self):
        """闲聊处理 Agent"""
        prompt = load_prompt("chat/chitchat.md")
        return create_react_agent(
            model=self.model,
            tools=[get_current_time],
            prompt=prompt,
            name="chitchat_agent",
        )

    # ==================== 图构建 ====================

    def _build_graph(self):
        """构建 Supervisor 多 Agent 工作流"""
        workflow = StateGraph(ChatAgentState)

        # 添加 supervisor 路由节点
        workflow.add_node("supervisor", self._supervisor_node)
        workflow.add_node("pre_sales", self._make_agent_node("pre_sales", self._build_pre_sales_agent()))
        workflow.add_node("post_sales", self._make_agent_node("post_sales", self._build_post_sales_agent()))
        workflow.add_node("escalation", self._make_agent_node("escalation", self._build_escalation_agent()))
        workflow.add_node("chitchat", self._make_agent_node("chitchat", self._build_chitchat_agent()))

        workflow.set_entry_point("supervisor")

        # Supervisor 路由到子 Agent
        def route_to_agent(state: ChatAgentState) -> str:
            next_agent = state.get("next_agent", "chitchat")
            valid = {"pre_sales", "post_sales", "escalation", "chitchat"}
            return next_agent if next_agent in valid else "chitchat"

        workflow.add_conditional_edges("supervisor", route_to_agent, {
            "pre_sales": "pre_sales",
            "post_sales": "post_sales",
            "escalation": "escalation",
            "chitchat": "chitchat",
        })

        # 所有子 Agent 执行完后结束
        workflow.add_edge("pre_sales", END)
        workflow.add_edge("post_sales", END)
        workflow.add_edge("escalation", END)
        workflow.add_edge("chitchat", END)

        return workflow.compile(checkpointer=self.checkpointer)

    # ==================== Supervisor 节点 ====================

    async def _supervisor_node(self, state: ChatAgentState) -> Dict[str, Any]:
        """Supervisor 路由节点：分析用户意图并选择子 Agent"""
        messages = state.get("messages", [])
        if not messages:
            return {"next_agent": "chitchat"}

        # 获取最后一条用户消息
        last_user_msg = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_msg = msg.content
                break

        if not last_user_msg:
            return {"next_agent": "chitchat"}

        # 先用简单关键词判断路由（更快更稳定），再 fallback 到 LLM
        agent = self._quick_route(last_user_msg)
        if agent:
            logger.info(f"Supervisor 快速路由 → {agent}")
            return {"next_agent": agent}

        # LLM 语义路由
        logger.info("快速路由未命中，使用 LLM 语义路由")
        supervisor_prompt = load_prompt("chat/supervisor.md")

        route_llm = ChatQwen(
            model=config.rag_model,
            api_key=config.dashscope_api_key,
            api_base=config.dashscope_api_base,
            temperature=0,
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", supervisor_prompt),
            ("user", "请为以下用户消息选择最合适的Agent（只回复Agent名称）：\n\n{question}"),
        ])

        chain = prompt | route_llm
        try:
            result = await chain.ainvoke({"question": last_user_msg})
            result_text = result.content.strip().lower() if hasattr(result, "content") else str(result).strip().lower()

            for name in ["pre_sales", "post_sales", "escalation", "chitchat"]:
                if name in result_text:
                    logger.info(f"Supervisor LLM 路由 → {name}")
                    return {"next_agent": name}

            logger.info(f"Supervisor 无法确定路由，默认 escalation → 原始结果: {result_text[:100]}")
            return {"next_agent": "escalation"}
        except Exception as e:
            logger.error(f"Supervisor LLM 路由失败: {e}")
            return {"next_agent": "escalation"}

    def _quick_route(self, question: str) -> Optional[str]:
        """快速关键词路由（无 LLM 调用，<1ms）"""
        q = question.lower()

        # 售后关键词
        post_sales_keywords = [
            "退货", "退款", "换货", "物流", "快递", "保修", "维修",
            "订单", "发货", "收到", "坏了", "破损", "退换",
            "申请退", "售后", "催单", "改地址",
        ]
        for kw in post_sales_keywords:
            if kw in q:
                return "post_sales"

        # 售前关键词
        pre_sales_keywords = [
            "多少钱", "价格", "优惠", "折扣", "有货", "库存",
            "规格", "对比", "推荐", "哪个好", "怎么样",
            "品牌", "功能", "配置", "颜色", "尺寸",
        ]
        for kw in pre_sales_keywords:
            if kw in q:
                return "pre_sales"

        # 升级关键词
        escalation_keywords = [
            "投诉", "12315", "消协", "律师", "起诉", "打官司",
            "曝光", "举报", "维权", "工商", "媒体",
        ]
        for kw in escalation_keywords:
            if kw in q:
                return "escalation"

        # 闲聊关键词
        chitchat_keywords = ["你好", "谢谢", "再见", "早上好", "晚安", "在吗"]
        for kw in chitchat_keywords:
            if kw in q:
                return "chitchat"

        return None

    # ==================== Agent 节点包装 ====================

    def _make_agent_node(self, name: str, agent_graph):
        """包装 create_react_agent 的结果为图节点"""

        async def node(state: ChatAgentState) -> Dict[str, Any]:
            messages = state.get("messages", [])
            logger.info(f"[{name}] 开始处理, 消息数={len(messages)}")

            try:
                result = await agent_graph.ainvoke({"messages": messages})
                result_messages = result.get("messages", [])
                final_answer = ""

                if result_messages:
                    last_msg = result_messages[-1]
                    if hasattr(last_msg, "content"):
                        final_answer = last_msg.content
                    else:
                        final_answer = str(last_msg)

                logger.info(f"[{name}] 完成, 回复长度={len(final_answer)}")
                return {"final_answer": final_answer, "messages": result_messages}

            except Exception as e:
                logger.error(f"[{name}] 执行失败: {e}")
                return {"final_answer": f"NEED_HUMAN: 客服系统暂时繁忙，已转人工处理 (错误: {str(e)})"}

        return node

    # ==================== 公共接口 ====================

    async def chat(
        self,
        question: str,
        session_id: str = "default",
        product_name: str = "",
        context_summary: str = "",
    ) -> str:
        """非流式对话"""
        logger.info(f"[会话 {session_id}] 客服对话: {question}")

        # 构建消息（注入商品上下文）
        context_parts = []
        if product_name:
            context_parts.append(f"用户当前正在查看商品：「{product_name}」。用户说「这个」「它」时指的就是「{product_name}」。")
        if context_summary:
            context_parts.append(f"会话信息：{context_summary}")

        context_text = "\n".join(context_parts)
        user_message = f"{context_text}\n\n用户问题：{question}" if context_text else question

        initial_state = {
            "messages": [HumanMessage(content=user_message)],
            "next_agent": "",
            "final_answer": "",
        }

        config_dict = {"configurable": {"thread_id": session_id}}
        result = await self.graph.ainvoke(initial_state, config=config_dict)
        return result.get("final_answer", "NEED_HUMAN: 系统繁忙，请稍后再试")

    async def chat_stream(
        self,
        question: str,
        session_id: str = "default",
        product_name: str = "",
        context_summary: str = "",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式对话 (SSE)"""
        logger.info(f"[会话 {session_id}] 客服流式对话: {question}")

        # 先获取完整回复，再分块发送
        full_answer = await self.chat(question, session_id, product_name, context_summary)

        # 分块发送
        chunk_size = 50
        for i in range(0, len(full_answer), chunk_size):
            chunk = full_answer[i:i + chunk_size]
            yield {"type": "content", "data": chunk}

        yield {"type": "complete"}


# 全局单例
chat_service = ChatService()
