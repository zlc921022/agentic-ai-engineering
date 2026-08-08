"""Advanced RAG 检索策略。
对应短课里的两个核心高级检索方法：

1. Sentence-window retrieval
   - 检索粒度：句子
   - 生成上下文：命中句子的前后窗口

2. Auto-merging retrieval
   - 检索粒度：子块
   - 生成上下文：当同一父块命中足够多子块时，自动合并回父块

这里不用 LlamaIndex，而是用项目已有的 LangChain Document + Chroma
实现同样的思想，避免为了一个短课额外引入一整套框架。
"""
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict

from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.client import DashScopeEmbeddingClient
from src.index_manager import ChromaIndexManager
from src.retrieval_util import _dedupe_docs


def _stash_id(*parts):
    text = "::".join(str(part) for part in parts)
    return hashlib.md5(text.encode(encoding="utf-8")).hexdigest()


@dataclass
class SentenceWindowConfig:
    #  句子前后取几个上下文存储
    window_size: int = 2
    top_max_size: int = 8
    collection_name = "employee_rules_sentence_window"


class ChineseSentenceSplitter:
    """面向中文制度文本的轻量句子切分器。
    课程里的 SentenceWindowNodeParser 会把文档切成句子节点。
    这里用正则实现相同意图：优先按中文句号、问号、感叹号、分号、
    换行来切；如果某一句仍然过长，再按固定长度兜底切。
    """
    SENTENCE_PATTERN = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")

    def __init__(self, max_sentence_chars: int = 240):
        self.max_sentence_chars = max_sentence_chars

    def split(self, text: str) -> List[str]:
        # 去除空格，换行等符号
        cleands = re.sub(r"\s+", " ", text or "").strip()
        # 匹配正则表达式的数据存到列表中
        match_texts = [
            match.group().strip()
            for match in self.SENTENCE_PATTERN.finditer(cleands)
            if match.group().strip()
        ]
        # 最终返回值 句子的集合
        sentences = []
        for sentence in match_texts:
            if len(sentence) <= self.max_sentence_chars:
                sentences.append(sentence)
                continue
            # 步伐
            step = self.max_sentence_chars
            # len 1000 step 240 start 0,240,480
            for start in range(0, len(sentence), step):
                end = start + step
                sentences.append(sentence[start: end])
                # 如果右边
                if end >= len(sentence):
                    break
        return sentences


class SentenceWindowRetriever:
    """
    存句子，metadata里面存上下文，然后检索返回把上下文取出来
    """

    def __init__(self,
                 index_manager: ChromaIndexManager,
                 embedding_client: DashScopeEmbeddingClient,
                 config: SentenceWindowConfig):
        self.index_manager = index_manager
        self.embedding_client = embedding_client
        self.config = config
        self.splitter = ChineseSentenceSplitter()
        self._store = self.get_store()

    def get_store(self):
        return Chroma(
            collection_name=self.config.collection_name,
            embedding_function=self.embedding_client.get_embedding_function(),
            client=self.index_manager.client
        )

    def _collection_has_data(self) -> bool:
        try:
            return self.index_manager.client.get_collection(self.config.collection_name).count() > 0
        except Exception as e:
            print(e)
            return False

    def _build_index(self, force: bool = False):
        if not force and self._collection_has_data():
            self._store = self.get_store()
            return

        try:
            self.index_manager.client.delete_collection(self.config.collection_name)
        except Exception as e:
            print(e)
            pass

        self._store = self.get_store()
        # 所有父文档
        base_docs = self.index_manager._all_rule_documents()
        # 最终入库的数据
        docs = []
        ids = []
        for base_idx, base_doc in enumerate(base_docs):
            # 得到句子
            sentences = self.splitter.split(base_doc.page_content)
            # 遍历句子
            for sentence_idx, sentence in enumerate(sentences):
                # window_size 2 左边最小是0，不能为负数
                left = max(0, sentence_idx - self.config.window_size)
                # 右边最大不能超过len,+1 代表取左不取右
                right = min(len(sentences), sentence_idx + self.config.window_size + 1)
                # 截取 sentences 这一段的值作为 window_text 当前句子在 sentences 列表里的前后几句
                window_text = "".join(sentences[left:right])

                metadata = dict(base_doc.metadata or {})
                metadata.update(
                    {
                        "retrieve": "sentence-window",
                        "window": window_text,
                    }
                )
                # 数据入库存的是句子
                docs.append(Document(
                    page_content=sentence,
                    metadata=metadata,
                ))

                ids.append(
                    _stash_id(
                        "sentence-window",
                        base_idx,
                        sentence,
                        sentence_idx
                    )
                )
        if docs:
            self._store.add_documents(docs, ids=ids)

    def retrieve(self, query: str, k: int = 4) -> List[Document]:
        self._build_index(force=False)
        if self._store is None:
            return []
        # 检索得到的句子文档
        sentence_docs = self._store.similarity_search(
            query=query,
            k=max(k, self.config.top_max_size)
        )

        # 返回结果
        docs = []

        for sentence_idx, sentence_doc in enumerate(sentence_docs):
            metadata = dict(sentence_doc.metadata or {})
            # 获取存进去的上下文
            window_text = metadata.get("window", sentence_doc.page_content)
            # 最终检索拿到的是带句子上下文的文档
            docs.append(
                Document(
                    page_content=window_text,
                    metadata=metadata,
                )
            )

        return _dedupe_docs(docs)[:k]


@dataclass
class AutoMergingConfig:
    """Auto-merging 检索配置。"""

    # 每个子块的最大字符数。
    # 建索引时会把一个父文档切成多个 child chunk：
    # - 越小：检索粒度越细，命中更精准
    # - 越大：上下文更完整，但检索粒度更粗
    child_size: int = 220

    # 相邻子块之间重叠的字符数。
    # 作用是避免关键信息刚好卡在切分边界，被两个子块拆散。
    # 例如 child_size=220、child_overlap=40 时，
    # 下一个子块会从上一个子块结束前约 40 个字符的位置开始。
    child_overlap: int = 40

    # 向量检索时先召回多少个子块。
    # 这不是最终返回给 LLM 的数量；先多查一些，再根据 parent_id
    # 判断是否需要把多个子块合并回父块。
    similarity_top_k: int = 12

    # 同一个父文档下面至少命中多少个不同子块，才允许合并回父文档。
    # 如果只命中 1 个子块，通常说明证据覆盖还不够，不急着返回整段父文档。
    min_children_to_merge: int = 2

    # 命中子块比例阈值。
    # 计算方式：命中的不同 child_id 数量 / 这个父文档的总 child 数量。
    # 例如一个父文档有 6 个子块，命中 3 个，比例是 0.5；
    # 0.5 >= 0.35 时，就会合并并返回父文档。
    merge_ratio: float = 0.35

    # Chroma 集合名。
    # Auto-merging 单独建一个集合，里面只存 child chunk，
    # 不和普通规则库、sentence-window 索引混在一起。
    collection_name: str = "employee_rules_auto_merging"


class AutoMergingRetriever:
    """
    切成小块，然后数据库存小块，最终合并的时候判断父块下命中的子块是否合并决定返回父块还是子块
    """

    def __init__(self,
                 index_manager: ChromaIndexManager,
                 embedding_client: DashScopeEmbeddingClient,
                 config: AutoMergingConfig):
        self.index_manager = index_manager
        self.embedding_client = embedding_client
        self.config = config
        self._store = self.get_store()
        self._parent_docs: Dict[str, Document] = {}

    def get_store(self):
        return Chroma(
            collection_name=self.config.collection_name,
            embedding_function=self.embedding_client.get_embedding_function(),
            client=self.index_manager.client
        )

    def _collection_has_data(self) -> bool:
        try:
            return self.index_manager.client.get_collection(self.config.collection_name).count() > 0
        except Exception as e:
            print(e)
            return False

    def _split_chunk(self, text: str) -> List[str]:
        # 切成的子块
        chunks = []
        step = max(1, self.config.child_size - self.config.child_overlap)
        # start 0 len 1000, step 180  start 0,180,360
        for start in range(0, len(text), step):
            # end 0 + 220 180 + 220
            end = min(start + self.config.child_size, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
        return chunks

    def _prepare_parent_docs(self):
        self._parent_docs = {}
        base_docs = self.index_manager._all_rule_documents()
        for base_idx, base_doc in enumerate(base_docs):
            metadata = dict(base_doc.metadata or {})
            source = metadata.get("source", "")
            parent_chunk_id = metadata.get("chunk_id", "")
            parent_id = _stash_id(
                source,
                base_idx,
                parent_chunk_id
            )
            metadata.update(
                {
                    "retrieve": "parent-merging",
                    "parent_id": parent_id
                }
            )
            self._parent_docs[parent_id] = Document(
                page_content=base_doc.page_content,
                metadata=metadata
            )
        return base_docs

    # 是否要合并父文档
    def _should_merge(self, child_hits: List[Document]) -> bool:
        if (len(child_hits)) < self.config.min_children_to_merge:
            return False
        child_count = int(child_hits[0].metadata.get("child_count") or 1)
        child_hit_len = {hit.metadata.get("child_id") for hit in child_hits}
        return len(child_hit_len) / child_count >= self.config.merge_ratio

    def _build_index(self, force: bool = False):
        base_docs = self._prepare_parent_docs()
        if not force and self._collection_has_data():
            self._store = self.get_store()
            return

        try:
            self.index_manager.client.delete_collection(self.config.collection_name)
        except Exception as e:
            print(e)
            pass

        self._store = self.get_store()
        # base_docs = self.index_manager._all_rule_documents()

        # 最终入库数据
        child_docs = []
        ids = []

        for base_idx, base_doc in enumerate(base_docs):
            # 切割得到子块
            child_chunks = self._split_chunk(base_doc.page_content)
            # 遍历子块
            for chunk_idx, chunk in enumerate(child_chunks):
                metadata = dict(base_doc.metadata or {})
                source = metadata.get("source", "")
                parent_chunk_id = metadata.get("chunk_id", "")
                parent_id = _stash_id(
                    source,
                    base_idx,
                    parent_chunk_id
                )
                metadata.update(
                    {
                        "retrieve": "child-merging",
                        "parent_id": parent_id,
                        "child_id": chunk_idx,
                        "child_content": chunk,
                        # 记录子块数量，用于后面计算是否合并父块
                        "child_count": len(child_chunks)
                    }
                )
                child_docs.append(
                    Document(
                        page_content=chunk,
                        metadata=metadata
                    )
                )
                ids.append(
                    _stash_id(
                        "auto-merging",
                        parent_chunk_id,
                        parent_id,
                        chunk_idx,
                        chunk
                    )
                )
        if child_docs:
            self._store.add_documents(child_docs, ids=ids)

    def retrieve(self, query: str, k: int = 4) -> List[Document]:

        self._build_index(force=False)
        if self._store is None:
            return []
        # 得到所有子块文档
        child_docs = self._store.similarity_search(
            query=query,
            k=max(k, self.config.similarity_top_k),
        )

        # 得到分组之后的数据
        grouped_docs: Dict[str, List[Document]] = defaultdict(list)
        # 以parent_id 分组
        for child_doc in child_docs:
            metadata = dict(child_doc.metadata or {})
            parent_id = str(metadata.get("parent_id", ""))
            grouped_docs[parent_id].append(child_doc)

        # 最终返回结果
        docs = []

        for parent_id, child_docs in grouped_docs.items():
            # 通过子块拿到 parent_id，然后通过_parent_docs拿到对应父文档
            parent_doc = self._parent_docs.get(parent_id)
            # 应该合并父文档，那就用父文档的page_content
            if parent_doc is not None and self._should_merge(child_docs):
                metadata = dict(parent_doc.metadata or {})
                docs.append(
                    Document(
                        page_content=parent_doc.page_content,
                        metadata=metadata
                    )
                )
            else:
                for child_doc in child_docs:
                    metadata = dict(child_doc.metadata or {})
                    docs.append(
                        Document(
                            page_content=child_doc.page_content,
                            metadata=metadata
                        )
                    )
        return _dedupe_docs(docs)[:k]
