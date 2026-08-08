# Deep Research Agent

一套面向复杂问题的可信研究 Agent：通过任务规划、并发检索、来源治理、报告质检与反思闭环，生成带可追溯引用和证据表的研究报告。

## 核心能力

- Planner 拆解互补研究任务，TaskExecutor 保证任务并发、单任务内有序与失败隔离。
- 多后端搜索、来源质量评分、质量门与 Function Calling 补检索，失败自动回退规则策略。
- 程序化组装引用、参考文献和证据表，规则 Evaluator 与可选 LLM Judge 联合质检。
- FastAPI + SSE 输出全阶段事件，Vue 工作台展示报告、证据、Trace 和质检结果。
- 单元测试、离线 Agent Eval、真实问题集回归门禁与 Locust 阶梯压测。

## 快速启动

```bash
python3.10 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env
cd src/frontend && npm ci && cd ../..
.venv/bin/python dev.py
```

访问 `http://127.0.0.1:5174`。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python benchmarks/agent_eval.py
```

## 文档

- [完整项目文档](docs/README.md)
- [核心代码流程](docs/core-workflow.md)
- [Benchmark 与回归门禁](benchmarks/README.md)
- [并发压测](load_tests/README.md)
