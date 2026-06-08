"""对话接口 — 支持两种模式：
1. 普通模式：RAG Agent（LangGraph prebuilt agent）
2. 客服模式：SupervisorAgent（4 子 Agent 路由）

对标 Java ChatController.java 的所有接口
"""

import json
import uuid
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from app.services.chat_service import chat_service
# rag_agent_service 懒加载——依赖 Milvus + DashScope API Key

router = APIRouter()

# 会话内存存储（对标 Java ChatController.SessionInfo）
_sessions: Dict[str, Dict[str, Any]] = {}
MAX_WINDOW_SIZE = 6  # 最大历史消息对数


def _get_or_create_session(session_id: str, product_name: str = "", product_id: int = 0) -> Dict[str, Any]:
    """获取或创建会话，首次绑定的商品信息持久存储"""
    if not session_id:
        session_id = str(uuid.uuid4())
    if session_id not in _sessions:
        _sessions[session_id] = {
            "sessionId": session_id,
            "history": [],
            "productName": product_name or "",
            "productId": product_id or 0,
            "createTime": int(__import__("time").time() * 1000),
        }
    else:
        # 首次绑定时写入商品信息（只写一次，后续不覆盖）
        s = _sessions[session_id]
        if not s.get("productName") and product_name:
            s["productName"] = product_name
        if not s.get("productId") and product_id:
            s["productId"] = product_id
    return _sessions[session_id]


def _add_message_pair(session: Dict, question: str, answer: str):
    """添加一对消息到会话历史"""
    history = session["history"]
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    # 保持窗口大小
    max_msgs = MAX_WINDOW_SIZE * 2
    while len(history) > max_msgs:
        history.pop(0)
        if history:
            history.pop(0)


def _parse_body(raw: Dict[str, Any]) -> Dict[str, Any]:
    """解析请求体 — 兼容 ContextEnvelope 和旧 ChatRequest 格式

    Returns:
        {session_id, question, product_name, context_summary}
    """
    session_id = raw.get("sessionId") or raw.get("Id") or raw.get("id") or str(uuid.uuid4())
    question = ""
    product_name = raw.get("productName") or ""
    product_id = 0
    context_summary = ""

    # ContextEnvelope 格式
    if "user" in raw or "message" in raw:
        user_map = raw.get("user") or {}
        product_map = raw.get("product") or {}
        msg_map = raw.get("message") or {}

        question = msg_map.get("content", raw.get("Question", ""))
        product_name = product_map.get("productName", raw.get("productName", ""))
        history_raw = raw.get("history")

        user_id = user_map.get("userId", 0)
        username = user_map.get("username", "")
        product_id = product_map.get("productId", 0)
        context_summary = f"用户ID={user_id}({username}) 商品ID={product_id}({product_name})"

        # 有 DB 历史 → 替换内存历史
        if history_raw and isinstance(history_raw, list):
            session = _get_or_create_session(session_id)
            session["history"] = [
                {"role": h.get("role", "user"), "content": h.get("content", "")}
                for h in history_raw if isinstance(h, dict)
            ]
    else:
        # 旧格式
        question = raw.get("Question") or raw.get("question") or ""
        product_name = raw.get("productName") or ""

    return {
        "session_id": session_id,
        "question": question,
        "product_name": product_name,
        "product_id": product_id,
        "context_summary": context_summary,
    }


@router.post("/chat")
async def chat(request: Request):
    """普通对话接口 — 使用客服 SupervisorAgent

    兼容两种请求格式：
    - ContextEnvelope: {"user":{...}, "product":{...}, "message":{"content":"..."}, "sessionId":"..."}
    - ChatRequest: {"Id":"...", "Question":"...", "productName":"..."}

    响应格式对标 Java ChatController:
    {"code":200, "message":"success", "data":{"success":true, "answer":"...", "errorMessage":null}}
    """
    try:
        body = await request.json()
        info = _parse_body(body)
        session_id = info["session_id"]
        question = info["question"]
        product_name = info["product_name"]
        context_summary = info["context_summary"]
        product_id = info.get("product_id", 0)

        if not question or not question.strip():
            return {
                "code": 200,
                "message": "success",
                "data": {"success": False, "answer": None, "errorMessage": "问题内容不能为空"},
            }

        # 会话层商品绑定：写入 + 恢复
        session = _get_or_create_session(session_id, product_name, product_id)
        if not product_name:
            product_name = session.get("productName", "")
        if not context_summary and session.get("productId"):
            context_summary = f"用户ID=? 商品ID={session['productId']}({product_name})"

        logger.info(f"[会话 {session_id}] 客服对话: product={product_name}")

        # 调用客服 SupervisorAgent
        answer = await chat_service.chat(
            question=question,
            session_id=session_id,
            product_name=product_name,
            context_summary=context_summary,
        )

        # 更新会话历史
        session = _get_or_create_session(session_id)
        _add_message_pair(session, question, answer)

        logger.info(f"[会话 {session_id}] 客服对话完成, 答案长度={len(answer)}")

        return {
            "code": 200,
            "message": "success",
            "data": {"success": True, "answer": answer, "errorMessage": None},
        }

    except Exception as e:
        logger.error(f"对话失败: {e}", exc_info=True)
        return {
            "code": 200,
            "message": "success",
            "data": {"success": False, "answer": None, "errorMessage": str(e)},
        }


@router.post("/chat_stream")
async def chat_stream(request: Request):
    """流式对话接口 — 使用客服 SupervisorAgent（SSE）

    SSE 事件格式:
    - {"type":"content","data":"..."} — 内容块
    - {"type":"done","data":null} — 完成
    - {"type":"error","data":"..."} — 错误
    """
    try:
        body = await request.json()
        info = _parse_body(body)
        session_id = info["session_id"]
        question = info["question"]
        product_name = info["product_name"]
        context_summary = info["context_summary"]
        product_id = info.get("product_id", 0)

        if not question or not question.strip():
            async def err_gen():
                yield {
                    "event": "message",
                    "data": json.dumps({"type": "error", "data": "问题内容不能为空"}, ensure_ascii=False),
                }
            return EventSourceResponse(err_gen())

        # 会话层商品绑定：写入 + 恢复
        session = _get_or_create_session(session_id, product_name, product_id)
        if not product_name:
            product_name = session.get("productName", "")
        if not context_summary and session.get("productId"):
            context_summary = f"用户ID=? 商品ID={session['productId']}({product_name})"

        logger.info(f"[会话 {session_id}] 客服流式对话: product={product_name}")

        answer_builder = []

        async def event_generator():
            try:
                async for chunk in chat_service.chat_stream(
                    question=question,
                    session_id=session_id,
                    product_name=product_name,
                    context_summary=context_summary,
                ):
                    chunk_type = chunk.get("type")
                    if chunk_type == "content":
                        data = chunk.get("data", "")
                        answer_builder.append(data)
                        yield {
                            "event": "message",
                            "data": json.dumps({"type": "content", "data": data}, ensure_ascii=False),
                        }
                    elif chunk_type == "complete":
                        yield {
                            "event": "message",
                            "data": json.dumps({"type": "done", "data": None}, ensure_ascii=False),
                        }
                    elif chunk_type == "error":
                        yield {
                            "event": "message",
                            "data": json.dumps({"type": "error", "data": chunk.get("data", "")}, ensure_ascii=False),
                        }

                # 更新会话历史
                full_answer = "".join(answer_builder)
                if full_answer:
                    session = _get_or_create_session(session_id)
                    _add_message_pair(session, question, full_answer)

            except Exception as e:
                logger.error(f"流式对话错误: {e}", exc_info=True)
                yield {
                    "event": "message",
                    "data": json.dumps({"type": "error", "data": str(e)}, ensure_ascii=False),
                }

        return EventSourceResponse(event_generator())

    except Exception as e:
        logger.error(f"流式对话请求解析失败: {e}", exc_info=True)
        async def err_gen():
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "data": str(e)}, ensure_ascii=False),
            }
        return EventSourceResponse(err_gen())


@router.post("/chat/rag")
async def chat_rag(request: Request):
    """RAG 模式对话（原版知识库对话，保留兼容）"""
    try:
        body = await request.json()
        info = _parse_body(body)
        session_id = info["session_id"]
        question = info["question"]

        if not question or not question.strip():
            return {
                "code": 500,
                "message": "error",
                "data": {"success": False, "answer": None, "errorMessage": "问题内容不能为空"},
            }

        logger.info(f"[会话 {session_id}] RAG 对话: {question}")
        from app.services.rag_agent_service import rag_agent_service
        answer = await rag_agent_service.query(question, session_id=session_id)

        return {
            "code": 200,
            "message": "success",
            "data": {"success": True, "answer": answer, "errorMessage": None},
        }

    except Exception as e:
        logger.error(f"RAG 对话错误: {e}", exc_info=True)
        return {
            "code": 500,
            "message": "error",
            "data": {"success": False, "answer": None, "errorMessage": str(e)},
        }


@router.post("/chat/clear")
async def clear_session(request: Request):
    """清空会话历史"""
    try:
        body = await request.json()
        session_id = body.get("sessionId") or body.get("Id") or body.get("id", "")

        if not session_id:
            return {"code": 500, "message": "error", "data": "会话ID不能为空"}

        if session_id in _sessions:
            _sessions[session_id]["history"] = []
            logger.info(f"会话 {session_id} 历史已清空")
            return {"code": 200, "message": "success", "data": "会话历史已清空"}
        else:
            return {"code": 200, "message": "success", "data": "会话不存在"}

    except Exception as e:
        logger.error(f"清空会话失败: {e}")
        return {"code": 500, "message": "error", "data": str(e)}


@router.post("/chat/context/sync")
async def sync_context(request: Request):
    """商家端回复后同步上下文（保持 Agent 会话视图与 DB 一致）"""
    try:
        body = await request.json()
        session_id = body.get("sessionId") or ""
        msg = body.get("message") or {}

        if not session_id:
            return {"code": 500, "message": "error", "data": "sessionId required"}

        session = _sessions.get(session_id)
        if session:
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            session["history"].append({"role": role, "content": content})
            max_msgs = MAX_WINDOW_SIZE * 2
            while len(session["history"]) > max_msgs:
                session["history"].pop(0)
            logger.info(f"商家回复已同步到 agent 会话: sessionId={session_id}")

        return {"code": 200, "message": "success", "data": "ok"}

    except Exception as e:
        logger.warning(f"同步上下文失败: {e}")
        return {"code": 500, "message": "error", "data": str(e)}


@router.get("/chat/session/{session_id}")
async def get_session_info(session_id: str):
    """查询会话信息"""
    try:
        session = _sessions.get(session_id)
        if session:
            history = session.get("history", [])
            return {
                "code": 200,
                "message": "success",
                "data": {
                    "sessionId": session_id,
                    "messagePairCount": len(history) // 2,
                    "createTime": session.get("createTime", 0),
                },
            }
        else:
            return {"code": 200, "message": "success", "data": None}

    except Exception as e:
        logger.error(f"获取会话信息失败: {e}")
        return {"code": 500, "message": "error", "data": str(e)}
