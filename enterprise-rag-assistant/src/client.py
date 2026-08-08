from typing import Iterable

from langchain_community.embeddings import DashScopeEmbeddings
from openai import OpenAI

from src.config import Config


class QwenChatClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    def complete(self,
                 prompt: str,
                 *,
                 temperature: float = 1.0,
                 top_p: float = 0.9,
                 max_tokens: int = 2048) -> str:
        resp = self.client.chat.completions.create(
            model=self.config.chat_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    def stream(self,
               prompt: str,
               *,
               temperature: float = 1.0,
               top_p: float = 0.9,
               max_tokens: int = 2048) -> Iterable[str]:
        resp = self.client.chat.completions.create(
            model=self.config.chat_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=True
        )
        for chunk in resp:
            text = chunk.choices[0].delta.content
            if text:
                yield text


class DashScopeEmbeddingClient:
    def __init__(self, config: Config):
        self.config = config
        self.embedding = DashScopeEmbeddings(
            model=config.embedding_model,
            dashscope_api_key=config.api_key,
        )

    def embed_documents(self, texts):
        return self.embedding.embed_documents(texts)

    def embed_query(self, text):
        return self.embedding.embed_query(text)

    def get_embedding_function(self):
        return self


if __name__ == "__main__":
    chat_client = QwenChatClient(Config())
    print(chat_client.complete(prompt="你好啊"))
    print("*" * 50)
    embedding = DashScopeEmbeddingClient(Config())
    print()
    embedding.embed_query(text="大家好")
