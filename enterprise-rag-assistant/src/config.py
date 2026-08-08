# 负责集中管理路径、模型名、API Key 和目录校验。以后你换模型或换数据目录，优先看这里
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    """应用配置。
    说明：
    - base_dir: 项目根目录
    - data_rule_dir: 规章制度文档目录
    - data_business_dir: 经营/投融资文档目录
    - chroma_dir: Chroma 持久化目录
    - manifest_file: 文档签名清单，用于判断是否需要重建索引
    - dashscope_api_key: 阿里云百炼 API Key
    """
    base_dir = Path(__file__).resolve().parent.parent
    data_rule_dir = base_dir / "data" / "rules"
    data_business_dir = base_dir / "data" / "business"
    storage_dir = base_dir / "storage"
    chroma_dir = storage_dir / "chroma"
    manifest_file = storage_dir / "manifest.json"

    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/",
    )

    chat_model: str = os.environ.get("CHAT_MODEL", "qwen3-max")
    embedding_model: str = os.environ.get("EMBEDDING_MODEL", "text-embedding-v4")

    def ensure_dirs(self):
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)

    def check(self):
        if not self.data_rule_dir.exists():
            print("规则目录不存在")
        if not self.data_business_dir.exists():
            print("经营目录不存在")
        if not self.api_key:
            print("api key 不存在")


if __name__ == "__main__":
    settings = Config()
    print(settings.api_key)
    print(settings.base_url)
    print(settings.chat_model)
    print(settings.embedding_model)
