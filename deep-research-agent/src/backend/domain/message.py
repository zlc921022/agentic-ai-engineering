from dataclasses import dataclass


@dataclass
class Message:
    """Agent 历史消息。

    SimpleAgent 用它记录 user / assistant 消息，再在下一轮调用时拼回 prompt。
    """
    role: str
    content: str
