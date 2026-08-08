import json
from typing import Optional

from backend.llm.base_agent import BaseAgent
from backend.llm.client import QwenChatClient
from backend.llm.usage import usage_stage_scope
from backend.domain.message import Message
from backend.tools.tool_registry import ToolRegistry


class SimpleAgent(BaseAgent):
    """
    最小可默写版 Agent。

    核心思路只有四步：
    1. 保存角色设定 system_prompt；
    2. 把 system/history/user 拼成 prompt；
    3. 调用 LLM 得到 response；
    4. 把本轮 user 和 assistant 消息写回历史。

    工具调用是可选能力，不是主线能力。默认情况下它就是一个纯提示词 Agent，
    更适合 planner / summarizer / reporter 这类固定流程节点。
    """

    def __init__(
            self,
            name: str,
            llm: QwenChatClient,
            tool_registry: ToolRegistry,
            system_prompt: Optional[str] = None,
            enable_tool_calling: bool = False,
            max_tool_iterations: int = 3,
            **kwargs
    ):
        """初始化一个最小 Agent。

        参数重点：
        - name：阶段名，方便日志区分 planner / summary / reporter；
        - system_prompt：这个 Agent 的角色边界；
        - enable_tool_calling：是否允许模型通过 JSON 协议调用工具；
        - max_tool_iterations：工具调用最大轮数，防止死循环。
        """
        super().__init__(name, llm, tool_registry, **kwargs)

        # system_prompt 是 Agent 的角色和行为边界；不传时给一个通用助手兜底。
        self.system_prompt = (system_prompt or "你是一个有用的 AI 助手。").strip()

        # enable_tool_calling=False 时，SimpleAgent 只做一次 LLM 调用。
        # 打开后，模型可以输出 JSON 列表来请求一个或多个工具：
        # {"type": "tool_calls", "tool_calls": [{"tool_name": "search", "tool_input": "多模态模型"}]}
        self.enable_tool_calling = enable_tool_calling

        # 工具调用最多循环几轮。防止模型一直调用工具停不下来。
        self.max_tool_iterations = max_tool_iterations

    def run(self, input_text: str, max_tool_iterations: Optional[int] = None, **kwargs) -> str:
        """同步执行一次 Agent 调用，并返回最终文本。"""

        # 执行的时候可以透传提示词
        system_prompt = kwargs.get("system_prompt")
        if system_prompt:
            self.system_prompt = system_prompt

        # temperature / max_tokens 允许调用方覆盖；默认偏稳定，适合结构化输出。
        temperature = kwargs.pop("temperature", 0)
        max_tokens = kwargs.pop("max_tokens", 2048)
        iterations = max_tool_iterations if max_tool_iterations is not None else self.max_tool_iterations

        # messages 是统一的中间表示：system + 历史对话 + 当前用户输入。
        messages = self._build_messages(input_text)
        final_response = ""

        # 纯生成：循环第一轮就会 break。
        # 工具模式：每次模型输出 JSON tool_calls，就执行工具，并把结果追加回 messages。
        for iteration in range(iterations + 1):
            prompt = self._format_prompt(messages)
            # usage_stage_scope 只给旁路 Token 统计增加阶段标签，
            # 不改变 LLM 参数、返回值或工具调用判断。
            with usage_stage_scope(self.name):
                response = self.llm.complete(
                    prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            final_response = response

            # 不启用工具时，模型回复就是最终答案。
            if not self.enable_tool_calling:
                break

            # 启用工具时，只有 JSON tool_calls 才会触发工具。
            # 普通文本或其它 JSON 都会被当作最终回答。
            tool_calls = self._parse_tool_calls(response)
            if not tool_calls:
                break

            # 如果已经到最大工具轮数，就不要再执行新工具了；
            # 否则执行完工具后没有下一轮 LLM 来消化 Observation。
            if iteration >= iterations:
                break

            # 执行一个或多个工具调用，并把工具结果当成新的 user 消息喂回模型。
            # 这里不是 OpenAI 原生 tool call 协议，而是学习版 JSON 文本协议。
            tool_results = [
                self._execute_tool_call(tool_call["tool_name"], tool_call["tool_input"])
                for tool_call in tool_calls
            ]
            messages.append({
                "role": "user",
                "content": (
                    "工具执行结果：\n"
                    + "\n\n".join(tool_results)
                    + "\n\n请基于这些结果继续完成用户任务。"
                )
            })

        # Agent 记忆只保存用户输入和最终回答；中间工具过程不写入长期历史。
        self.add_message(Message("user", input_text))
        self.add_message(Message("assistant", final_response or ""))
        return final_response

    def stream_run(self, input_text: str, **kwargs):
        """流式执行。当前保持纯生成，不处理工具调用。"""

        temperature = kwargs.pop("temperature", 0)
        max_tokens = kwargs.pop("max_tokens", 2048)
        messages = self._build_messages(input_text)
        prompt = self._format_prompt(messages)

        full_response = ""

        # 边接收 chunk 边 yield 给调用方，同时拼出完整回答用于写入历史。
        with usage_stage_scope(self.name):
            for chunk in self.llm.stream(
                    prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
            ):
                full_response += chunk
                yield chunk

        self.add_message(Message("user", input_text))
        self.add_message(Message("assistant", full_response))

    def _build_messages(self, input_text: str) -> list[dict[str, str]]:
        """把系统提示词、历史消息、当前输入组装成 chat messages。"""

        # system 永远放第一条，决定这个 Agent 的角色。
        messages = [{"role": "system", "content": self._get_enhanced_system_prompt()}]

        # BaseAgent.messages 保存历史对话；这里按原顺序追加。
        for message in self.messages:
            messages.append({"role": message.role, "content": message.content})

        # 当前用户输入放最后，表示本轮要解决的问题。
        messages.append({"role": "user", "content": input_text})
        return messages

    def _get_enhanced_system_prompt(self) -> str:
        """根据是否启用工具，决定 system_prompt 是否追加工具说明。"""

        # 不启用工具时，直接返回原始 system_prompt，保持提示词最干净。
        if not self.enable_tool_calling:
            return self.system_prompt

        # 启用工具但工具注册表为空，也不强行追加工具说明。
        tools_description = self.tool_registry.get_tool_description()
        if not tools_description or tools_description == "没有工具可以调用":
            return self.system_prompt

        # 把工具列表和 JSON tool_calls 调用格式追加到 system prompt。
        # 不需要工具时，模型直接正常回答；只有需要工具时才输出 JSON。
        return (
            self.system_prompt
            + "\n\n可用工具：\n"
            + tools_description
            + "\n\n如果需要调用一个或多个工具，请只输出 JSON：\n"
            + '{"type":"tool_calls","tool_calls":[{"tool_name":"工具名","tool_input":"工具输入"}]}'
            + "\n工具结果会追加到对话中，然后你再继续完成任务。"
        )

    @staticmethod
    def _format_prompt(messages: list[dict[str, str]]) -> str:
        """把 chat messages 转成 QwenChatClient.complete 接收的单段 prompt。"""

        # 当前 QwenChatClient.complete 只收一个 prompt 字符串，
        # 所以这里手动把 role/content 序列化成清晰的对话文本。
        role_names = {
            "system": "System",
            "user": "User",
            "assistant": "Assistant",
            "tool": "Tool",
        }
        return "\n\n".join(
            f"{role_names.get(message['role'], message['role'])}:\n{message['content']}"
            for message in messages
        )

    @staticmethod
    def _parse_tool_calls(text: str) -> list[dict[str, str]]:
        """
        尝试把模型输出解析成一批工具调用。

        只有这种 JSON 会被当成工具调用：
        {
          "type": "tool_calls",
          "tool_calls": [
            {"tool_name": "search", "tool_input": "多模态模型"}
          ]
        }

        如果模型输出不是 JSON，或者 type 不是 tool_calls，就返回空列表。
        """

        try:
            data = json.loads(SimpleAgent._clean_json_text(text))
        except json.JSONDecodeError:
            return []

        if not isinstance(data, dict):
            return []

        if data.get("type") != "tool_calls":
            return []

        raw_tool_calls = data.get("tool_calls")
        if not isinstance(raw_tool_calls, list):
            return []

        tool_calls = []
        for item in raw_tool_calls:
            if not isinstance(item, dict):
                continue

            tool_name = str(item.get("tool_name") or "").strip()
            if not tool_name:
                continue

            tool_calls.append({
                "tool_name": tool_name,
                "tool_input": str(item.get("tool_input") or ""),
            })

        return tool_calls


    @staticmethod
    def _clean_json_text(text: str) -> str:
        """去掉模型可能包上的 ```json 代码块外壳。"""

        cleaned = text.strip()
        if not cleaned.startswith("```"):
            return cleaned

        lines = cleaned.splitlines()
        if lines and len(lines) > 0 and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    def _execute_tool_call(self, tool_name: str, tool_input: str) -> str:
        """通过 ToolRegistry 执行工具，并包装成模型可读的 Observation 文本。"""

        result = self.tool_registry.execute_tool(tool_name, tool_input)
        return f"工具 {tool_name} 执行结果：\n{result}"
