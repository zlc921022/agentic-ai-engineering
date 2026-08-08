# 检索工具类
import json
import re
from typing import List, Sequence, Dict, Any

import jieba
from langchain_core.documents import Document


def docs_to_context(docs: list) -> str:
    """把命中文档拼成 prompt 上下文。"""
    lines = []
    for i, doc in enumerate(docs):
        source = doc.metadata.get("file_name", doc.metadata.get("source", "unknown"))
        lines.append(f"上下文{i + 1} (来源: {source}): {doc.page_content}")
    return "\n".join(lines)


def _jieba_preprocess(text: str) -> List[str]:
    """BM25 中文分词。"""
    return list(jieba.cut(text))


def _dedupe_docs(docs: List[Document]) -> List[Document]:
    """按文本去重，避免同一段文档重复出现。"""
    seen = set()
    new_docs = []
    for doc in docs:
        key = doc.page_content
        if key in seen:
            continue
        seen.add(key)
        new_docs.append(doc)
    return new_docs


def parse_score(text: str) -> int:
    match = re.search(r"\d+", text)
    if not match:
        return 0
    score = int(match.group())
    return max(0, min(score, 100))


def parse_index(ids: str) -> List[int]:
    # "最相关的是：2, 4, 10"
    # 输出 ["2", "4", "10"]
    nums = re.findall(f"\\d+", ids)
    indexes = []
    seen = set()
    for num in nums:
        idx = int(num)
        if idx in seen:
            continue
        seen.add(idx)
        indexes.append(idx)
    return indexes


def parse_lines(text: str) -> List[str]:
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = line.strip("-• \t")
        lines.append(line)
    return lines


def _is_yes(text: str) -> bool:
    """把 LLM 的 yes/no 判断转成 bool。"""
    text = (text or "").strip().lower()
    return text.startswith("yes") or text.startswith("是")


def _collect_references(docs: Sequence[Document]) -> List[str]:
    refs = []
    for doc in docs:
        source = doc.metadata.get("source", doc.metadata.get("file_name", "unknown"))
        refs.append(str(source))
    seen = set()
    uniq = []
    for item in refs:
        if item in seen:
            continue
        seen.add(item)
        uniq.append(item)
    return uniq


def _missing_dependency_message(package: str) -> str:
    """统一 LlamaIndex 可选依赖缺失提示。"""
    return (
        f"缺少可选依赖 `{package}`。请先安装 LlamaIndex 高级 RAG 对照依赖，"
        "或者继续使用项目原生版 `retrieval_enhance.py` / `advanced_retrieval.py`。"
    )

def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {}
