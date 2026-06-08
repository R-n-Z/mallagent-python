"""退货审核 API 接口（对标 Java ReturnAuditController.java）"""

import json
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from app.services.return_agent_service import return_agent_service

router = APIRouter()


@router.post("/return/audit")
async def return_audit(request: Request):
    """退货审核接口 — 单 ReactAgent 自动审核

    请求格式: {"applyId": 123, "sessionId": "..."}
    响应格式:
    {
        "code": 200,
        "message": "success",
        "data": {
            "success": true,
            "apply_id": 123,
            "report": "...",
            "elapsed_ms": 5000
        }
    }
    """
    try:
        body = await request.json()
        apply_id = body.get("applyId", 0)
        session_id = body.get("sessionId", "default")

        if not apply_id:
            return {
                "code": 500,
                "message": "error",
                "data": {"success": False, "error": "applyId 不能为空"},
            }

        result = await return_agent_service.audit(apply_id, session_id)

        return {
            "code": 200,
            "message": "success",
            "data": result,
        }

    except Exception as e:
        logger.error(f"退货审核失败: {e}", exc_info=True)
        return {
            "code": 500,
            "message": "error",
            "data": {"success": False, "error": str(e)},
        }


@router.post("/return/audit_stream")
async def return_audit_stream(request: Request):
    """退货审核流式接口（SSE）

    请求格式: {"applyId": 123, "sessionId": "..."}
    """
    try:
        body = await request.json()
        apply_id = body.get("applyId", 0)
        session_id = body.get("sessionId", "default")

        if not apply_id:
            async def error_gen():
                yield {
                    "event": "message",
                    "data": json.dumps({"type": "error", "data": "applyId 不能为空"}, ensure_ascii=False),
                }
            return EventSourceResponse(error_gen())

        async def event_generator():
            async for chunk in return_agent_service.audit_stream(apply_id, session_id):
                chunk_type = chunk.get("type")
                if chunk_type == "content":
                    yield {
                        "event": "message",
                        "data": json.dumps({"type": "content", "data": chunk.get("data", "")}, ensure_ascii=False),
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

        return EventSourceResponse(event_generator())

    except Exception as e:
        logger.error(f"退货审核流式请求失败: {e}", exc_info=True)
        async def error_gen():
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "data": str(e)}, ensure_ascii=False),
            }
        return EventSourceResponse(error_gen())


@router.get("/return/rejection_count/{username}")
async def get_rejection_count(username: str):
    """查询用户连续拒绝次数"""
    count = return_agent_service.get_rejection_count(username)
    return {
        "code": 200,
        "message": "success",
        "data": {"username": username, "consecutiveRejections": count},
    }
