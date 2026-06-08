"""客服 FAQ 知识库工具

对标 Java FaqTools.java — 使用 Milvus 向量搜索从 FAQ 集合中检索匹配的答案
"""

import json
from langchain_core.tools import tool
from loguru import logger

from app.config import config
from app.core.milvus_client import milvus_manager


FAQ_COLLECTION = "faq"


@tool
def search_faq(query: str) -> str:
    """搜索客服常见问题知识库(FAQ)。当用户询问商品、物流、退换货、支付、售后等常见问题时使用此工具。
    返回最匹配的问题和答案。如果匹配分数低于阈值，表示知识库中没有相关答案，需要人工客服处理。

    Args:
        query: 用户提出的问题
    """
    try:
        logger.info(f"[FaqTools] 搜索FAQ: {query}")

        # 1. 生成查询向量
        from app.services.vector_embedding_service import embedding_service
        query_vector = embedding_service.generate_query_vector(query)

        # 2. Milvus 向量搜索
        from pymilvus import Collection
        col = Collection(name=FAQ_COLLECTION, using=milvus_manager.alias)
        col.load()

        search_params = {
            "metric_type": "L2",
            "params": {"ef": 64},
        }

        results = col.search(
            data=[query_vector],
            anns_field="vector",
            param=search_params,
            limit=config.rag_top_k,
            output_fields=["id", "content", "metadata"],
        )

        # 3. 解析结果
        items = []
        for hits in results:
            for hit in hits:
                item = {
                    "question": hit.entity.get("content", ""),
                    "score": float(hit.score),
                }

                # 从 metadata 中提取 answer 和 category
                meta_raw = hit.entity.get("metadata")
                if meta_raw:
                    try:
                        meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
                        item["answer"] = meta.get("answer", "暂无答案")
                        item["category"] = meta.get("category", "")
                    except (json.JSONDecodeError, TypeError):
                        pass
                items.append(item)

        response = {
            "status": "success",
            "query": query,
            "results": items,
        }

        logger.info(f"[FaqTools] 找到 {len(items)} 个匹配")
        return json.dumps(response, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[FaqTools] 搜索失败: {e}")
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
