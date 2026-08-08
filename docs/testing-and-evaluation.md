# 测试、评估与回归策略

## 分层验证

| 层级 | Deep Research Agent | Enterprise RAG Assistant |
| --- | --- | --- |
| 单元测试 | 事件顺序、搜索、来源评分、Evaluator、超时与失败隔离 | 检索策略、Self-RAG 状态图、真实文档 smoke test |
| 离线 Agent Eval | Fake LLM / Search 验证 Tool Call、参数 Schema、回退路径 | 固定问题与参考答案构造 Ragas 数据集 |
| 在线质量评估 | 固定问题集统计成功率、引用、来源、Trace、Token 与阶段耗时 | RAG Triad 诊断答案相关性、上下文相关性与忠实度 |
| 回归门禁 | 绝对阈值与基线对比，失败返回非零退出码 | Hybrid 与 LangGraph Agent 策略对比 |
| 性能测试 | Locust 1/2/4 并发阶梯压测，观察 P50/P95/P99 与失败率 | 通过 UI 调试轨迹定位检索与多轮模型调用耗时 |

## 无模型密钥验证

```bash
cd deep-research-agent
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python benchmarks/agent_eval.py

cd ../enterprise-rag-assistant
.venv/bin/python -m unittest discover -s tests -v
```

## 真实链路评估

真实评估会调用模型和搜索服务，可能产生费用。建议使用固定数据集、固定模型参数和明确基线，并保留运行配置以保证结果可比较。

详细指标：

- [Deep Research Benchmark](../deep-research-agent/benchmarks/README.md)
- [Deep Research 并发压测](../deep-research-agent/load_tests/README.md)
- [Enterprise RAG 评估与调试](../enterprise-rag-assistant/docs/evaluation-and-debugging.md)
