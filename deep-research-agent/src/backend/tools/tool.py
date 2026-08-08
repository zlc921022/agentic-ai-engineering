from abc import abstractmethod, ABC
from typing import Any, Dict

from pydantic import BaseModel, ValidationError


class Tool(ABC):
    """工具抽象基类。

    SimpleAgent 的学习版工具调用协议最终会通过 ToolRegistry 找到 Tool，
    再调用 run({"input": ...}) 执行。
    """
    name: str
    description: str

    def __init__(self, name: str, description: str) -> None:
        """保存工具名称和说明。"""
        self.name = name
        self.description = description
        self.arguments_model: type[BaseModel] | None = None

    @abstractmethod
    def run(
            self,
            parameters: Dict[str, Any],
            *,
            context: object = None,
    ) -> Any:
        """执行工具逻辑。"""
        pass

    @abstractmethod
    def get_parameters(self) -> Dict[str, Any]:
        """返回工具参数说明。"""
        pass

    @abstractmethod
    def get_function_schema(self) -> Dict[str, Any]:
        """返回 OpenAI 兼容的 Function Tool Schema。

        Schema 同时是“告诉模型如何传参”的协议；真正执行前仍要由 Python 后端
        再校验一次，不能因为模型使用了 Function Calling 就信任其参数。
        """
        pass

    def validate_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """用工具声明的 Pydantic Model 校验并规范化模型参数。"""
        if self.arguments_model is None:
            return parameters
        try:
            validated = self.arguments_model.model_validate(parameters)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        return validated.model_dump()
