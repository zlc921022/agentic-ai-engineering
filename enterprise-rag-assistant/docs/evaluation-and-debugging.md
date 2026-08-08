# 评估与调试

项目里有两类评估/调试方式：

1. 在线调试：Gradio 页面右侧展示 route、strategy、debug、context。
2. 离线评估：RAG Triad 和 Ragas。

## UI 调试信息

UI 代码位置：

- `src/ui_app.py::_chat()`

每次问答会展示：

| 字段 | 含义 |
| --- | --- |
| `route` | service 或 Agent 判定的路线，如 `rule`、`business`、`rules` |
| `implementation` | UI 选择的实现：`langchain`、`llamaindex`、`langgraph` |
| `strategy` | 实际使用的 `RetrievalStrategy` |
| `debug` | 检索策略或 Agent 节点轨迹 |
| `context` | 实际喂给 LLM 的上下文 |
| `triad_report` | 开启 RAG Triad 后的评估报告 |

调试时最重要的是看三件事：

```text
strategy 是否符合 UI 选择
debug 是否命中了预期链路
context 是否真的能支撑 answer
```

## RAG Triad

代码位置：

- `src/rag_triad.py::RAGTriadEvaluator`
- `src/advanced_rag_types.py::TriadMetricResult`
- `src/advanced_rag_types.py::RAGTriadReport`
- service 入口：`src/rag_service.py::_maybe_evaluate_triad()`

RAG Triad 拆成三个指标：

| 指标 | 评估问题 | 主要定位 |
| --- | --- | --- |
| Answer Relevance | 答案是否回应了用户问题 | 表达/回答方向问题 |
| Context Relevance | 检索上下文是否和问题相关 | 检索召回问题 |
| Groundedness | 答案是否被上下文支撑 | 幻觉/编造问题 |

开启方式：

- UI 勾选 `启用 RAG Triad 评估`
- 或构造 `RetrievalOptions(enable_triad_eval=True)`

注意：RAG Triad 会额外调用 LLM，速度会明显变慢，适合调试和写项目复盘，不建议普通问答默认开启。

## Ragas 离线评估

代码位置：

- `src/evaluator.py`
- `run_eval.py`

`src/evaluator.py` 内置了样例问题，并通过 `run_eval_with_ragas()` 生成 Ragas 所需数据：

```text
user_input
response
retrieved_contexts
reference
```

默认示例会对比：

- `RetrievalStrategy.HYBRID`
- `RetrievalStrategy.LANGGRAPH_AGENT`

运行方式：

```bash
.venv/bin/python -m src.evaluator
```

Ragas 更适合批量对比策略，RAG Triad 更适合单次问答调试。

## 浏览器验证建议

推荐测试问题：

```text
我连续请病假 3 天，返岗后需要补什么材料？审批链路会不会追加部门负责人？
```

预期结果：

- 应命中 `leave_policy.txt`。
- 应回答返岗后 2 个工作日内补系统申请和医院证明材料。
- 应回答连续病假超过 2 天需要就诊证明或电子病历截图。
- 应回答请假达到 3 个工作日及以上会追加部门负责人审批。

如果 Top K 较大，引用列表可能带出弱相关文档，比如 `expense_policy.txt` 或 `company_handbook.txt`。这通常是召回展示不够干净，不代表答案一定错误。判断时优先看答案是否被核心上下文支撑。

## 常见问题

### 结果很慢

常见原因：

- `langgraph_agent` 会调用多次 LLM：plan、generate、reflect，必要时 revise。
- `enable_triad_eval=True` 会额外调用多次评估 prompt。
- LlamaIndex 某些策略如 `llama_graph`、`llama_rerank`、`llama_recursive` 本身成本更高。

排查方式：

1. 关闭 RAG Triad。
2. 降低 Top K。
3. 先用 `plain` 或 `hybrid` 做 baseline。
4. 再切换到 Agent 或 LlamaIndex 策略对比。

### 引用列表不干净

原因通常是 service 层把所有命中 docs 都列成引用，但最终答案可能只引用其中一部分。

改进方向：

- 降低 Top K。
- 增加 context relevance filter。
- 让生成节点返回“实际使用的 source”，再由 service 过滤 references。

### LangGraph Agent 结果里 route 是 `rules`

这是正常的。Agent 内部 route 使用：

```text
rules
business
both
```

普通 service route 里有时使用：

```text
rule
business
```

两者语义相近，但来源不同：一个来自 Agent plan，一个来自 service router。
