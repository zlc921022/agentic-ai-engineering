# Agentic AI Engineering

面向真实工程场景的 Agent 与 RAG 作品集，包含一套可评估的深度研究 Agent，以及一套支持多路知识检索与反思闭环的企业知识库助手。两个项目均提供可运行界面、完整测试和质量评估链路。

> 技术栈：Python · FastAPI · LangGraph · Function Calling · Chroma · LangChain · LlamaIndex · Ragas · Vue 3 · Gradio

## 项目导航

| 项目 | 定位 | 核心能力 | 详细文档 |
| --- | --- | --- | --- |
| [Deep Research Agent](deep-research-agent/) | 面向复杂问题的可信研究工作台 | 任务规划、并发检索、Function Calling 补检索、证据治理、质检与反思 | [项目说明](deep-research-agent/README.md) · [核心流程](deep-research-agent/docs/core-workflow.md) |
| [Enterprise RAG Assistant](enterprise-rag-assistant/) | 面向企业制度与经营资料的 Agentic RAG 助手 | 知识路由、混合检索、高级 RAG、LangGraph 编排、RAG Triad / Ragas 评估 | [项目说明](enterprise-rag-assistant/README.md) · [架构文档](enterprise-rag-assistant/docs/architecture.md) |

## Deep Research Agent

将一次研究请求拆解为可观测、可评估、可修正的 Agent 工作流；重点解决来源质量、引用漂移、并发事件流和模型输出不稳定等工程问题。

```mermaid
flowchart LR
    U["研究问题"] --> UI["Vue 研究工作台"]
    UI <-->|"SSE 事件流"| API["FastAPI"]
    API --> P["Planner<br/>任务规划"]
    P --> E["TaskExecutor<br/>多任务并发"]
    E --> S["多后端检索"]
    S --> Q{"来源质量门"}
    Q -->|"不达标"| F["Function Calling / Rule<br/>补检索与回退"]
    F --> S
    Q -->|"达标"| M["Summary + Reporter"]
    M --> V["规则质检 + LLM Judge"]
    V --> R{"需要修正?"}
    R -->|"是"| X["Reflection"]
    X --> V
    R -->|"否"| O["报告 + 证据表 + Trace"]
```

核心技术亮点：

- 以 Planner、并发 TaskExecutor、Reporter、Evaluator 和 Reflection 构建研究闭环，单任务失败不阻塞全局流程。
- 通过来源评分、域名多样性和质量门触发补检索；Function Calling 异常时自动回退确定性策略。
- 正文引用、参考文献与证据表由程序统一组装，降低引用漂移和不可追溯结论。
- SSE 全链路事件建模，配套离线 Agent Eval、固定问题集回归门禁与 Locust 阶梯压测。

![Deep Research Agent 工作台](docs/images/deep-research-workbench.png)

真实运行：并行完成 4 个研究任务、汇聚 20 条来源，引用质检得分 100。

## Enterprise RAG Assistant

围绕企业制度与经营资料构建多知识库问答系统，以统一服务层编排路由、检索、生成、引用和评估，并提供 LangGraph Agentic RAG 模式。

```mermaid
flowchart LR
    U["员工问题"] --> UI["Gradio 调试台"]
    UI --> A["EnterpriseAssistantService"]
    A --> G["LangGraph<br/>Plan → Retrieve → Generate → Reflect"]
    A --> T{"知识路由"}
    T --> K1["制度知识库"]
    T --> K2["经营知识库"]
    K1 --> C["Chroma 向量索引"]
    K2 --> C
    C --> H["Hybrid / Rerank / Query Transform"]
    C --> L["Sentence Window / Auto Merging / Self-RAG"]
    H --> GEN["答案生成与引用"]
    L --> GEN
    G --> GEN
    GEN --> E["RAG Triad / Ragas"]
    E --> UI
```

核心技术亮点：

- 基于 LangGraph 构建 `plan → retrieve → generate → reflect → revise` 状态图，支持制度、经营及跨库路由。
- 统一 Chroma、BM25 与向量召回，覆盖 Query Transformation、Rerank、多索引及上下文增强策略。
- 抽象 LangChain / LlamaIndex / LangGraph 三类实现，通过统一返回模型收敛答案、引用、上下文与调试轨迹。
- 引入 RAG Triad 在线诊断与 Ragas 离线评估，分离回答相关性、上下文相关性和忠实度问题。

![Enterprise RAG Assistant 调试台](docs/images/enterprise-rag-console.png)

真实运行：基于 LangGraph Agent 完成意图路由、知识检索、反思修订与证据引用。

## 本地启动

环境要求：Python 3.10+、Node.js 18+。两个子项目使用独立虚拟环境，避免依赖互相影响。

### 1. Deep Research Agent

```bash
cd deep-research-agent
python3.10 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env

cd src/frontend
npm ci
cd ../..
.venv/bin/python dev.py
```

打开 `http://127.0.0.1:5174`。未配置 Tavily / SerpApi 时，搜索会降级到 DuckDuckGo。

### 2. Enterprise RAG Assistant

```bash
cd enterprise-rag-assistant
python3.10 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env
.venv/bin/python app.py
```

打开 `http://127.0.0.1:7860`。首次启动会根据示例知识文档构建本地 Chroma 索引。

## 测试与评估

### Deep Research Agent

```bash
cd deep-research-agent
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python benchmarks/agent_eval.py

# 启动后端后执行真实固定问题集与回归门禁
.venv/bin/python benchmarks/runner.py --backend duckduckgo
.venv/bin/python benchmarks/regression_gate.py benchmarks/runs/<run_id>/metrics.json
```

### Enterprise RAG Assistant

```bash
cd enterprise-rag-assistant
.venv/bin/python -m unittest discover -s tests -v

# 需配置模型密钥：对比 Hybrid 与 LangGraph Agent 策略
.venv/bin/python run_eval.py
```

评估体系与指标定义见 [统一测试与评估说明](docs/testing-and-evaluation.md)。

## 文档

- [整体架构与设计取舍](docs/architecture.md)
- [测试、评估与回归策略](docs/testing-and-evaluation.md)
- [Deep Research Agent 完整文档](deep-research-agent/docs/README.md)
- [Enterprise RAG 检索策略](enterprise-rag-assistant/docs/rag-strategies.md)
- [Enterprise RAG 评估与调试](enterprise-rag-assistant/docs/evaluation-and-debugging.md)

## 安全说明

仓库不包含任何真实密钥、模型凭证、运行日志、研究产物或本地向量索引。请从 `.env.example` 创建本地 `.env`，切勿提交凭证。
