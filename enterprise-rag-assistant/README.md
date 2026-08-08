# Enterprise RAG Assistant

一套面向企业制度与经营资料的 Agentic RAG 助手：统一知识路由、高级检索、答案生成、引用治理与质量评估，并提供 LangChain、LlamaIndex 和 LangGraph 三类实现对照。

## 核心能力

- 双知识库路由：制度、经营或跨库检索。
- Hybrid Search、Query Transformation、Rerank、多索引、Sentence Window、Auto Merging 与 Self-RAG。
- LangGraph `plan → retrieve → generate → reflect → revise` 工作流。
- 统一 `AnswerPackage` 收敛回答、上下文、引用、策略与调试轨迹。
- RAG Triad 在线诊断与 Ragas 离线策略评估。

## 快速启动

```bash
python3.10 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example .env
.venv/bin/python -m enterprise_employee_assistant.app
```

访问 `http://127.0.0.1:7860`。

只预览界面、不调用模型或构建索引：

```bash
.venv/bin/python preview.py
```

## 测试与评估

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python run_eval.py
```

## 文档

- [总体架构](docs/architecture.md)
- [LangGraph Agent](docs/langgraph-agent.md)
- [RAG 检索策略](docs/rag-strategies.md)
- [评估与调试](docs/evaluation-and-debugging.md)
- [核心流程](docs/flows.md)
