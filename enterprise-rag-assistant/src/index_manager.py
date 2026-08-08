# 知识库索引管理器
import json
from typing import List, Dict

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.client import DashScopeEmbeddingClient
from src.config import Config
from src.data_loader import DataLoader


class ChromaIndexManager:
    """管理规则库和经营库两个 Chroma 集合。
    你可以把它理解成“知识库管理员”：
    - 文档有变化时，负责重建索引
    - 问题来了时，负责把检索请求转给 Chroma
    """
    RULE_COLLECTION = "employee_rules"
    BUSINESS_COLLECTION = "business_insights"

    def __init__(self,
                 config: Config,
                 embedding_client: DashScopeEmbeddingClient,
                 data_loader: DataLoader):
        self.config = config
        self.embedding_client = embedding_client
        self.data_loader = data_loader

        self.client = chromadb.PersistentClient(config.chroma_dir)
        self.rule_store = self._get_store(self.RULE_COLLECTION)
        self.business_store = self._get_store(self.BUSINESS_COLLECTION)

    def _get_store(self, collection_name):
        return Chroma(
            collection_name=collection_name,
            embedding_function=self.embedding_client.get_embedding_function(),
            client=self.client,
        )

    def _load_manifest(self) -> Dict:
        if not self.config.manifest_file.exists():
            return {}
        try:
            content = self.config.manifest_file.read_text(encoding="utf-8")
            return json.loads(content)
        except Exception as e:
            print(e)
            return {}

    def _save_manifest(self, payload: Dict):
        try:
            self.config.manifest_file.write_text(
                data=json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            print(e)
            pass

    def _rebuild_collection(self, collection_name: str, docs: List[Document]) -> Chroma:
        self.reset_collection(collection_name)
        store = self._get_store(collection_name)
        if docs:
            ids = [f"{d.metadata['source']}-{d.metadata['chunk_id']}" for d in docs]
            store.add_documents(
                documents=docs,
                ids=ids,
            )
        return store

    def reset_collection(self, collection_name):
        try:
            self.client.delete_collection(collection_name)
        except Exception as e:
            print(e)
            pass

    def _search_rules(self, query, k: int = 4) -> List[Document]:
        return self.rule_store.similarity_search(query, k)

    def _search_rules_by_vector(self, vector, k: int = 4) -> List[Document]:
        return self.rule_store.similarity_search_by_vector(vector, k)

    def _search_business(self, query, k: int = 4) -> List[Document]:
        return self.business_store.similarity_search(query, k)

    def _all_rule_documents(self) -> List[Document]:
        """给 BM25 用：拉取规则库全部文档。
        BM25 不是直接读取 Chroma 的向量，而是需要完整文本列表来建立词项索引。
        所以这里要把规则库中的所有文本再取出来一次。
        """
        data = self.client.get_collection(self.RULE_COLLECTION).get(include=["metadatas", "documents"])
        docs = []
        for content, meta in zip(data.get("documents", []), data.get("metadatas", [])):
            docs.append(Document(
                page_content=content,
                metadata=meta,
            ))
        return docs

    def _ensure_indexes(self, force: bool = False):
        """按文档签名增量构建索引。"""
        manifest = self._load_manifest()
        rule_signature = self.data_loader._directory_signature(self.config.data_rule_dir)
        business_signature = self.data_loader._directory_signature(self.config.data_business_dir)

        changed = False
        # 只有当目录内容发生变化时，才重建索引。
        # 这样可以避免每次启动都重新向量化，节省时间和成本。
        if force or manifest.get("rule_signature") != rule_signature:
            docs = self.data_loader._load_documents(self.config.data_rule_dir, "rules")
            self.rule_store = self._rebuild_collection(self.RULE_COLLECTION, docs)
            manifest["rule_signature"] = rule_signature
            changed = True

        if force or manifest.get("business_signature") != business_signature:
            docs = self.data_loader._load_documents(self.config.data_business_dir, "business")
            self.business_store = self._rebuild_collection(self.BUSINESS_COLLECTION, docs)
            manifest["business_signature"] = business_signature
            changed = True

        if changed:
            self._save_manifest(manifest)


if __name__ == "__main__":

    config = Config()
    config.ensure_dirs()
    config.check()

    embedding_client = DashScopeEmbeddingClient(config)
    data_loader = DataLoader()

    manager = ChromaIndexManager(
        config=config,
        embedding_client=embedding_client,
        data_loader=data_loader,
    )

    print("1. 开始构建索引")
    manager._ensure_indexes(force=True)
    print("2. 索引构建完成")

    print("3. 测试规则库检索")
    docs = manager._search_rules("病假需要提交什么材料？", k=3)
    for doc in docs:
        print("来源:", doc.metadata)
        print("内容:", doc.page_content[:120])
        print("-" * 50)

    print("4. 测试经营库检索")
    docs = manager._search_business("公司季度经营情况怎么样？", k=3)
    for doc in docs:
        print("来源:", doc.metadata)
        print("内容:", doc.page_content[:120])
        print("-" * 50)

    print("5. 测试拉取全部规则文档")
    all_docs = manager._all_rule_documents()
    print("规则文档块数量:", len(all_docs))
