"""Prompt 文件加载器

从 prompts/ 目录加载 Markdown 格式的 Prompt 模板，支持变量替换。
对标 Java 版 org.example.util.PromptLoader
"""

import os
from pathlib import Path
from typing import Dict
from loguru import logger

# Prompt 文件根目录（相对于项目根目录）
PROMPTS_ROOT = Path(__file__).parent.parent.parent / "prompts"


def load_prompt(relative_path: str, variables: Dict[str, str] | None = None) -> str:
    """加载 Prompt 模板并替换变量

    Args:
        relative_path: Prompt 文件相对路径（如 "chat/supervisor.md"）
        variables: 变量字典，{contextSummary: "...", productContext: "..."} 等

    Returns:
        替换变量后的完整 Prompt 文本
    """
    path = PROMPTS_ROOT / relative_path

    if not path.exists():
        logger.warning(f"Prompt 文件不存在: {path}，使用空字符串")
        return ""

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"读取 Prompt 文件失败: {path}, 错误: {e}")
        return ""

    # 变量替换（使用 Python 的 str.format_map，对缺失变量保留原文）
    if variables:
        content = _safe_format(content, variables)

    return content.strip()


def _safe_format(template: str, variables: Dict[str, str]) -> str:
    """安全的字符串格式化：只替换提供的变量，未提供的保留原文"""
    # 使用 string.Template 风格的替换，避免 KeyError
    for key, value in variables.items():
        placeholder = "{" + key + "}"
        template = template.replace(placeholder, str(value))
    return template


def load_prompt_raw(relative_path: str) -> str:
    """加载 Prompt 模板原始内容（不替换变量）"""
    path = PROMPTS_ROOT / relative_path
    if not path.exists():
        logger.warning(f"Prompt 文件不存在: {path}")
        return ""
    return path.read_text(encoding="utf-8").strip()


def list_prompts(subdir: str = "") -> list[str]:
    """列出指定子目录下的所有 Prompt 文件"""
    target = PROMPTS_ROOT / subdir if subdir else PROMPTS_ROOT
    if not target.exists():
        return []
    return [str(p.relative_to(PROMPTS_ROOT)) for p in target.rglob("*.md")]
