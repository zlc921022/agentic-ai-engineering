from abc import abstractmethod, ABC
from typing import List

from backend.llm.client import QwenChatClient
from backend.domain.message import Message
from backend.tools.tool_registry import ToolRegistry


class BaseAgent(ABC):
    """Agent 基类，抽象出最小的消息历史和 run 接口。

    SimpleAgent、未来可能的 ReActAgent 或 ToolCallingAgent 都可以继承它。
    这里不关心具体提示词怎么拼，只约定每个 Agent 都有 name、llm、
    tool_registry 和 messages。
    """

    def __init__(
            self,
            name: str,
            llm: QwenChatClient,
            tool_registry: ToolRegistry,
            **kwargs
    ):
        """保存 Agent 名称、LLM 客户端、工具注册表和消息历史。"""
        self.name = name
        self.llm = llm
        self.tool_registry = tool_registry
        self.messages : List[Message] = []

    def add_message(self, message: Message):
        """追加一条历史消息。"""
        self.messages.append(message)

    def clear_messages(self):
        """清空历史消息，适合 planner/judge/reflection 这种一次性阶段。"""
        self.messages.clear()

    def get_messages(self) -> List[Message]:
        """返回历史消息副本，避免调用方直接修改内部列表。"""
        return self.messages.copy()

    def __str__(self):
        """输出便于日志查看的 Agent 描述。"""
        return f"name: {self.name}, provider: {self.llm.config.chat_model}"

    def __repr__(self) -> str:
        """调试时复用 __str__ 展示。"""
        return self.__str__()

    @abstractmethod
    def run(self, input_text: str, max_tool_iterations: int = 3, **kwargs):
        """执行一次 Agent 调用，子类必须实现。"""
        pass
