# Deep Research 轻量回归评测

这套工具完全独立于业务主流程。它不导入 Agent 或搜索服务代码，只通过已经存在的 `/api/research/stream` SSE 接口观察一次完整运行。

目标不是追求绝对高分，而是回答一个更实用的问题：本次改动相对上一次，是否让固定问题集的运行结果变好，或者引入了明显回归。

## 数据流

```text
cases.json
  -> GET /api/research/stream
  -> 持续保存 SSE 事件
  -> run_id / seq / timestamp
  -> Trace 完整性与阶段耗时
  -> search_observation / Tool Call / 规则回退
  -> workflow_done.payload.result
  -> tasks / search_results / evaluator / llm_usage
  -> 单题指标
  -> metrics.json
  -> 与上一次可比运行生成 reports/latest.md
```

代码里最值得看的两个函数：

- `run_case()`：边读取 SSE，边保存事件，并在 `workflow_done` 中取得最终 result。
- `extract_case_metrics()`：把 result 中的任务、来源、总结、报告和 evaluator 压缩成基础指标。
- `SseTraceAnalyzer`：复用现有 `run_id`，根据 SSE 时间戳计算阶段耗时。

## 运行

先启动业务后端：

```bash
cd deep-research-agent
.venv/bin/python -m uvicorn backend.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

另开终端运行全部固定问题：

```bash
cd deep-research-agent
python benchmarks/runner.py
```

指定搜索后端：

```bash
python benchmarks/runner.py --backend duckduckgo
```

只调试一个 case：

```bash
python benchmarks/runner.py --case rag_hallucination
```

`--case` 运行的局部结果只会与 case 集合和 backend 都相同的历史运行比较，不会污染完整六题的版本对比。

## 产物

```text
benchmarks/
├── cases.json
├── runs/
│   └── 2026-06-18_153000/
│       ├── metrics.json
│       ├── rag_hallucination.json
│       ├── rag_hallucination_events.jsonl
│       ├── rag_hallucination_report.md
│       └── ...
└── reports/
    └── latest.md
```

单题 JSON 保存请求信息、基础指标和完整最终 result；JSONL 保存原始 SSE 消息；Markdown 保存最终报告。即使某题中途失败，也会保留已经收到的事件和失败指标。

基础指标包括：

- 是否收到带最终 result 的 `workflow_done`；
- 总耗时；
- Trace 完整率和事件序号缺口；
- Planner、Search、Summary、Report、Reflection 的阶段耗时；
- 总耗时和阶段耗时的 P50/P95/P99；
- 任务数和完成任务数；
- 来源数和去重域名数；
- 任务总结平均字符数；
- 报告字符数；
- evaluator 总分和 warning 数。
- 模型请求次数、输入/输出/总 Token 和分阶段 Usage；
- 配置模型单价后的估算成本；
- Tool Call 参数正确率、执行成功率、补检索成功率和规则回退率。

`runs/` 和 `reports/latest.md` 默认不提交 Git，只作为本地回归记录。固定问题集和评测代码会正常纳入版本管理。

## 离线 Agent 固定评测

`agent_cases.json` 不访问真实模型和搜索服务，使用 Fake LLM/Search 验证正式
Function Calling 和补检索代码。它覆盖：

- 强制 Tool Call 协议遵从；
- Tool Call 参数 Schema；
- 模型不能修改 backend 等可信运行参数；
- 非法 JSON；
- 重复工具调用抑制；
- 工具超时标准化；
- Function Calling 补检索成功；
- Function Calling 失败后的规则回退。

运行：

```bash
.venv/bin/python benchmarks/agent_eval.py
```

任何 case 不符合固定期望时，命令返回非零退出码，因此可以直接接入 CI。
机器可读报告默认写入：

```text
benchmarks/reports/agent_eval_latest.json
```

## 回归门禁

真实六题 Benchmark 运行完成后，可以检查绝对质量阈值：

```bash
.venv/bin/python benchmarks/regression_gate.py \
  benchmarks/runs/<run_id>/metrics.json
```

与一份明确的基线比较：

```bash
.venv/bin/python benchmarks/regression_gate.py \
  benchmarks/runs/<current_run_id>/metrics.json \
  --baseline benchmarks/runs/<baseline_run_id>/metrics.json
```

默认阈值在 `regression_thresholds.json`，包括成功率、Evaluator 分数、硬错误、
Trace 完整率、P95 延迟增长、Tool 参数正确率、补检索/回退率，以及配置价格后
的 Token/成本增长。没有真实 Tool Call 或成本样本时，对应门禁会安全跳过。
门禁失败返回退出码 `1`，输入文件错误返回 `2`。

## 并发压测与 CI

- Locust 脚本和阶梯压测说明位于 `load_tests/`；
- 普通 Push/PR 的 CI 只运行单元测试与离线 Agent 固定评测，不使用 API Key；
- 真实六题 Benchmark 只能从 GitHub Actions 手动触发，避免每次提交产生模型费用。

运行时观测只读取模型已经返回的 `usage`，并把补检索执行结果压缩进现有 SSE。
它不改变模型参数、搜索质量判断、工具参数校验和规则回退逻辑。Token 单价默认
为 0，此时只输出精确 Token；配置输入/输出单价后才输出估算成本。
