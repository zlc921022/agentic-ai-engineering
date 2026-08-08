import hashlib
from pathlib import Path
from typing import List, Dict

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


class DataLoader:
    """负责读取企业文档并切分为块。
       这里采用“段落优先 + 固定长度兜底”的方式切分，
       对中文规则类文档比较友好。
    """

    def __init__(self, chunk_size: int = 700, chunk_overlap: int = 80):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=[
                "\n\n",
                "\n",
                "。",
                "；",
                "，",
                " ",
                "",
            ],
        )

    def _split_text(self, text: str) -> List[str]:
        return self.splitter.split_text(text)

    def _list_files(self, data_dir: Path) -> List[Path]:
        files = []
        for file in ["*.txt", "*.md"]:
            files.extend(data_dir.glob(file))
            return files

    def _directory_signature(self, data_dir: Path) -> Dict[str, str]:
        """给目录生成签名，便于判断索引是否需要重建。"""
        signature = {}
        for file in self._list_files(data_dir):
            md5 = hashlib.md5()
            md5.update(file.read_bytes())
            signature[str(file.name)] = md5.hexdigest()
        return signature

    def _load_documents(self, data_dir: Path, source_type: str) -> List[Document]:
        """把目录下文件加载为 Document 列表（已分块）。"""
        documents = []
        for file in self._list_files(data_dir):
            content = file.read_text(encoding="utf-8")
            chunks = self._split_text(content)
            for idx, chunk in enumerate(chunks, start=1):
                documents.append(
                    Document(
                        page_content=chunk,
                        metadata={
                            "source": file.name,
                            "source_type": source_type,
                            "chunk_id": idx
                        }
                    )
                )
        return documents
