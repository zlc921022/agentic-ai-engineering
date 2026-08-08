from dataclasses import dataclass
from typing import List

from langchain_core.documents import Document


@dataclass
class RetrievalResult:
    """检索结果统一结构。"""
    strategy: str
    docs: List[Document]
    debug_note: str
