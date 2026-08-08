# Deep Research Assistant 面试题与参考答案

这份文档用于复习项目和准备面试表达。目标不是背代码，而是能围绕
`DeepResearchAgent.run_stream()` 这条主线讲清楚：项目解决什么问题、核心流程如何流转、
关键工程设计是什么、遇到失败如何兜底，以及后续如何扩展。

建议复习方式：

- 第一遍只看问题，尝试自己回答；
- 第二遍对照参考答案；
- 遇到不确定的点，再回到对应代码或 `core-workflow.md` 查。

## 一、项目定位与整体架构

### 1. 你怎么用 1 分钟介绍这个项目？

这是一个工程化的 Deep Research Agent MVP。用户输入一个复杂研究主题后，系统会先用 Planner 拆成多个子研究任务，然后并发执行每个任务的 `search -> summary`，再由 Reporter 汇总生成最终研究报告。报告生成后，系统会做规则质检和可选的 LLM Judge 语义质检，如果质量不达标，会触发一次 Reflection 修正报告并复检。整个过程通过 SSE 事件流实时推给前端，并保存任务笔记和报告笔记。

它的重点不是简单的 RAG 问答，而是“研究流程工程化”：任务规划、证据治理、引用一致性、质量评估、反思修正、运行可观测和失败隔离。

### 2. 它和普通 RAG Demo 最大区别是什么？

普通 RAG Demo 通常是“检索几条资料，然后一次性让模型总结”。这个项目多了几个工程化层次：

- 先规划多个研究任务，而不是直接检索；
- 多任务并发执行，提高整体耗时表现；
- 搜索结果会做来源质量治理、去重、评分和补检索；
- 每条来源分配稳定的 `Tn-Sn` 引用 ID；
- 最终报告的参考文献和证据表由程序组装，减少模型编造引用；
- 有规则 Evaluator 和可选 LLM Judge；
- 质检不通过时触发一次报告反思修正；
- 全流程通过 SSE 暴露阶段事件，便于前端展示和调试。

### 3. 项目的核心调用链是什么？

核心链路是：

```text
DeepResearchAgent.run_stream()
  -> run_plan()
  -> TaskExecutor.execute_tasks_stream()
      -> SearchService.run_search()
      -> SummaryService.stream_summary()
  -> run_report()
      -> ReportService.stream_report()
      -> ReportService.assemble_report()
  -> run_evaluator()
      -> ReportEvaluatorService.run()
      -> ReportJudgeService.run() 可选
  -> run_report_reflection()
      -> ReportReflectionService.decide()
      -> ReportReflectionService.revise_report() 可选
  -> workflow_done
```

### 4. 这个项目里最重要的几个对象是什么？

- `ResearchState`：一次研究运行的内存状态，保存 topic、tasks、report、evaluator、reflection、errors。
- `TodoItem`：Planner 生成的子任务，后续会逐步写入搜索结果、来源摘要、任务总结和状态。
- `SearchResult`：单个任务搜索阶段的标准输出，既包含结构化来源，也包含给总结模型用的长上下文。
- `EventEmitter`：给事件补 run_id 和递增 seq。
- `ResearchEventBuilder`：集中维护 SSE 事件协议。
- `TaskExecutor`：负责并发执行多个子任务。

### 5. 为什么说 `DeepResearchAgent.run_stream()` 是最重要的入口？

因为它把一次研究的所有阶段串起来，并且每个阶段完成后都会 `yield` 标准事件。它既是主业务流程，也是前端运行记录的事件来源。理解了 `run_stream()`，就能理解系统什么时候规划、什么时候并发执行、什么时候生成报告、什么时候质检、什么时候反思、最后怎么返回结果。

## 二、Planner 与任务模型

### 6. Planner 阶段做了什么？

Planner 阶段把用户输入的 topic 拆成多个结构化子任务。每个任务是一个 `TodoItem`，包含：

- `id`：任务编号；
- `title`：任务标题；
- `intent`：研究意图；
- `query`：可以直接用于搜索的查询词；
- `status`：任务执行状态。

代码主线是 `DeepResearchAgent.run_plan()` 调用 `PlanerService.run_plan()`，然后通过 `parse_plan()` 把 LLM 输出解析成任务列表。

### 7. 为什么 Planner 输出要解析成 `TodoItem`，而不是直接用字符串？

因为后续任务执行、事件流、笔记、报告引用和前端展示都需要稳定结构。`TodoItem` 让每个任务有明确生命周期：

```text
pending -> searching -> summarizing -> completed / failed
```

同时，它也承载后续写回的 `search_results`、`source_summary`、`summary` 和 `notices`。

### 8. 如果 Planner 没有生成任务怎么办？

`run_plan()` 会判断 `state.tasks` 是否为空。如果为空，会向 `state.errors` 写入 planner 错误，并通过 `ResultBuilder.build_error_report()` 生成兜底报告，然后发出 `planner_failed` 和 `workflow_failed` 事件，流程停止。

这体现了关键阶段失败时的“可解释失败”，而不是让后续阶段基于空任务继续运行。

## 三、并发任务执行

### 9. `TaskExecutor` 的职责是什么？

`TaskExecutor` 只负责“任务怎么跑”，不负责规划、报告和质检。它接收 `state.tasks`，使用线程池并发执行多个任务；每个任务内部按照固定顺序执行：

```text
search -> summary -> note update -> task_done
```

它还负责把 worker 线程产生的事件放入队列，由主线程统一消费并返回给 SSE。

### 10. 为什么多任务可以并发，但单任务内部要串行？

不同子任务之间互相独立，可以并发搜索和总结，提高整体速度。但单个任务内部有依赖关系：必须先搜索拿到来源上下文，才能总结。因此单任务内部保持 `search -> summary` 串行。

这种设计简单稳定，也符合数据依赖。

### 11. 为什么 worker 线程不直接 `yield` SSE 事件？

因为多个线程同时 `yield` 会让响应流难以控制，事件顺序也容易混乱。当前设计是：

```text
worker thread -> event_queue.put(event)
main thread   -> event_queue.get() -> yield event
```

这样 SSE 输出只有一个消费端，事件更稳定，也更容易过滤内部控制事件。

### 12. `event_lock` 的作用是什么？

`EventEmitter.emit()` 会递增 `seq`。多任务并发时，如果多个 worker 同时调用 `emit()`，可能出现 seq 竞争。`TaskExecutor._enqueue_event()` 用 `event_lock` 包住事件构造，保证事件序号在并发场景下仍然稳定递增。

### 13. `__task_done__` 是什么？

它是内部控制事件，只用于主线程统计已经完成的 worker 数量。`_consume_task_event()` 收到它后只增加 finished 计数，不会把它 `yield` 给前端。

这样前端只看到业务事件，不会暴露内部线程控制细节。

### 14. 某个任务失败会影响其他任务吗？

不会。单个任务失败会进入 `_handle_task_error()`，把该任务状态标记为 `failed`，写入 `state.errors`，并发出 `task_status failed` 和 `task_failed` 事件。其他任务仍然继续执行。

最终报告阶段只使用 `status == "completed"` 的任务；如果只有部分任务失败，报告仍然可以生成，并在末尾追加执行限制说明。

## 四、搜索与总结

### 15. `SearchService.run_search()` 主流程是什么？

主流程可以概括为：

```text
原始 query
  -> build_query_variants()
  -> run_query_variants()
  -> SourceQualityService 过滤评分
  -> SearchQualityRetryService 判断是否需要补检索
      -> rule：确定性 query rewrite
      -> function_calling：LLM 生成 tool_calls，Python 执行 supplemental_search
  -> attach_source_ids()
  -> build_sources_summary()
  -> build_research_context()
  -> SearchResult
```

第一遍理解时，重点看输入输出，不需要背评分规则。

### 16. 搜索阶段为什么要区分 `source_summary` 和 `search_results_text`？

它们服务的对象不同：

- `source_summary` 是给前端看的短来源摘要；
- `search_results_text` 是给 `SummaryService` 的长研究上下文。

这样可以避免前端展示过重，同时给总结模型保留足够材料。

### 17. `attach_source_ids()` 为什么重要？

它给每条最终保留的来源分配稳定 ID，比如：

```text
T1-S1
T1-S2
T2-S1
```

这些 ID 会贯穿任务总结、最终报告正文、参考文献、证据表和 Evaluator。没有稳定来源 ID，就很难做引用一致性校验。

### 18. 第一遍为什么可以不细看 `SourceQualityService`？

因为它属于搜索结果治理细节。主流程只需要知道它负责去重、评分、筛选、控制域名多样性。等遇到“为什么某个来源被过滤”或“搜索结果质量不好”时，再细看 `score_item()`、`select_diverse_results()` 等规则。

### 19. `SummaryService.stream_summary()` 做了什么？

它根据 `SearchResult` 构造任务总结 prompt，然后创建独立的 summary agent，流式生成任务总结。每个 chunk 会通过 `llm_delta` 事件推给前端，最终累计成完整 `task.summary`。

每个任务使用独立 summary agent，是为了避免不同任务之间的 LLM message history 串扰。

## 五、报告生成与引用治理

### 20. `ReportService.stream_report()` 的核心职责是什么？

它把所有完成任务的总结和来源目录交给 reporter agent，让 LLM 流式生成最终报告正文。生成结束后，通过 `get_report()` 调用 `assemble_report()`，把报告正文、参考文献和证据表组装成最终报告。

### 21. 为什么说 `assemble_report()` 是报告阶段的关键？

因为它把不稳定的 LLM 正文输出转成更稳定的最终报告：

```text
LLM 原始报告
  -> strip_generated_appendices()
  -> extract_used_source_ids()
  -> build_references()
  -> build_evidence_table()
  -> final report
```

设计要点是：LLM 只写正文，参考文献和证据表由程序根据正文实际引用的 `Tn-Sn` 自动生成。

### 22. 为什么不让 LLM 自己生成参考文献和证据表？

因为 LLM 可能会：

- 编造不存在的来源；
- 改写 source_id；
- 正文引用和参考文献不一致；
- 证据表漏掉或多出来源；
- 把来源标题、链接写错。

程序组装参考文献和证据表，可以让引用契约更稳定，也方便 Evaluator 做确定性校验。

### 23. 如果报告正文引用了不存在的 `T9-S9` 怎么办？

`ReportService.build_references()` 和 `build_evidence_table()` 不会伪造不存在的来源。它们只会为真实存在于任务搜索结果里的 source_id 生成条目。

后续 `ReportEvaluatorService.run()` 会发现正文引用没有出现在证据表或参考文献中，并给出硬错误。

## 六、Evaluator、LLM Judge 与 Reflection

### 24. `DeepResearchAgent.run_evaluator()` 做了什么？

它调用 `evaluate()`，把结果写入 `state.evaluator`，然后发出 `evaluator_done` 事件。`state.evaluator` 是前端质检器和反思修正阶段的重要输入。

### 25. 规则 Evaluator 主要检查什么？

规则 Evaluator 是确定性检查，主要关注：

- 是否存在证据表；
- 正文引用是否能在证据表中找到；
- 正文引用是否列入参考文献；
- 是否出现旧式 `[1]` 引用；
- weak 来源是否支撑过强或过具体的结论；
- 引用准确率、引用召回率、弱来源比例、一手来源比例、域名集中度等指标。

第一遍可以不背规则细节，但要知道它产出评分和 warnings。

### 26. LLM Judge 和规则 Evaluator 的区别是什么？

规则 Evaluator 擅长机器可验证的硬约束，比如引用是否存在、证据表是否完整。LLM Judge 擅长语义判断，比如：

- 是否回答了研究主题；
- 逻辑是否连贯；
- 工程建议是否具体；
- 风险边界是否充分；
- 是否存在空泛或过度断言。

两者互补：规则质检稳定，LLM Judge 补充语义判断。

### 27. 为什么 `ReportJudgeService._build_judge_prompt()` 不直接把完整 `rule_evaluator` 给模型？

技术上可以直接传，但不建议。代码使用 `_compact_rule_evaluator()` 有几个原因：

- 控制 prompt 长度；
- 只暴露 Judge 真正需要的关键指标；
- 减少无关字段噪声，避免模型被内部细节带偏；
- 稳定 Judge prompt 输入契约，后续规则 Evaluator 增加字段也不影响 Judge。

所以完整 `rule_evaluator` 是内部结果，压缩后的 evaluator 是给 LLM Judge 的摘要。

### 28. `json.dumps(..., ensure_ascii=False, indent=2)` 在 Judge prompt 里做什么？

它把 Python 字典转成格式化 JSON 字符串，方便塞进 prompt 给模型读。

- `ensure_ascii=False`：中文不转成 Unicode escape；
- `indent=2`：格式更清楚；
- 输出结果是字符串，不再是 Python dict。

### 29. Reflection 什么时候触发？

`ReportReflectionService.decide()` 会根据 evaluator 判断是否需要修正。常见触发条件包括：

- 综合评分低；
- 存在硬错误；
- 引用准确率低；
- 引用召回率低；
- weak 来源比例过高；
- LLM Judge 判定 fail 或给出修正建议。

当前策略是最多修正一次，避免无限反思带来成本和不稳定。

### 30. Reflection 修报告时会不会破坏引用和证据表？

修正报告后仍然会调用 `ReportService.assemble_report()` 重新组装参考文献和证据表。因此反思阶段不会直接信任 LLM 生成的附录，仍然保持程序化引用治理。

## 七、API、SSE 与超时控制

### 31. 为什么 API 可以放在最后看？

因为 API 只是把内部主流程包装成 HTTP/SSE。先理解 `run_stream()` 的内部阶段，再看 `stream_research()` 和 `ResearchSseStreamer.stream()`，会更容易理解“这些事件为什么这么传给前端”。

### 32. `ResearchSseStreamer.stream()` 解决了什么问题？

它把 `DeepResearchAgent.run_stream()` 产生的 dict 事件包装成浏览器 EventSource 能消费的 SSE 字符串，同时处理：

- producer 线程执行 agent；
- event_queue 跨线程传递事件；
- 心跳 `: ping`；
- workflow 总超时；
- API 层异常统一包装；
- 收到终止事件后停止流。

### 33. 为什么 SSE 层需要 producer 线程和队列？

因为 agent 执行过程可能长时间阻塞在搜索或 LLM 调用里。如果直接在 SSE generator 里跑 agent，心跳和总超时处理不灵活。使用 producer 线程后：

```text
producer thread -> 运行 agent，把事件放入 queue
SSE thread      -> 从 queue 取事件，负责心跳和超时
```

这样传输层和业务层解耦，连接也更稳定。

### 34. `finished = object()` 的作用是什么？

它是一个唯一的结束标记。producer 线程结束后把 `finished` 放入队列，SSE 消费端通过 `item is finished` 判断 agent 已经正常结束。

不用字符串是为了避免和业务事件冲突。

### 35. `stop_requested = threading.Event()` 是强制杀线程吗？

不是。它是协作式停止信号。SSE 侧超时或收到终止事件后会调用 `stop_requested.set()`，producer 线程在循环中检查 `is_set()` 后主动退出。

如果 producer 正卡在搜索或 LLM 请求里，它不会立刻被强杀，要等底层调用返回后才有机会检查停止信号。

### 36. 为什么用 `time.monotonic()` 计算超时？

因为 `time.monotonic()` 是单调递增时钟，适合计算耗时，不受系统时间校准影响。`time.time()` 是墙上时间，可能因为系统同步时间而前后跳，不适合做超时计算。

## 八、配置、失败处理与测试

### 37. 项目有哪些重要配置？

常见关键配置包括：

- `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`CHAT_MODEL`；
- `DEFAULT_SEARCH_BACKEND`；
- `SEARCH_MAX_RESULTS`；
- `ENABLE_MULTI_QUERY_SEARCH`；
- `ENABLE_SEARCH_QUALITY_RETRY`；
- `SEARCH_RETRY_MODE`；
- `FUNCTION_CALLING_MAX_STEPS`；
- `TASK_MAX_WORKERS`；
- `WORKFLOW_TIMEOUT_SECONDS`；
- `SSE_HEARTBEAT_SECONDS`；
- `ENABLE_LLM_JUDGE`；
- `NOTES_ENABLED`。

这些配置集中在 `Config`，通过环境变量读取，并提供安全默认值。

### 38. 如果所有任务都失败，系统怎么处理？

`run_report()` 会检查 completed tasks。如果没有任何完成任务，就不会让 Reporter 基于空内容硬编报告，而是调用 `_handle_all_tasks_failed()` 生成错误报告，并发出 `report_failed` 和 `workflow_failed`。

这是防止模型“无材料编造”的重要兜底。

### 39. 如果只有部分任务失败，系统怎么处理？

报告仍然基于完成任务生成。失败任务会记录到 `state.errors`，最终通过 `ResultBuilder.append_task_failure_warning()` 追加到报告末尾的“执行限制”中，明确告诉用户哪些任务没有纳入最终报告。

### 40. 这个项目的测试重点是什么？

测试主要覆盖：

- API/SSE 事件契约、心跳和 workflow 超时；
- LLM client 流式 idle timeout；
- TaskExecutor 并发事件顺序、失败隔离和内部事件过滤；
- 搜索工具后端降级和 timeout 参数传递；
- 搜索服务多 query；
- 来源质量评分和域名多样性；
- 报告 Evaluator 引用和证据表规则；
- notes 索引；
- benchmark runner 的事件解析和指标提取。

面试时可以强调：这个项目不是只做 happy path，也验证了并发、超时、失败隔离和引用质量这些工程边界。

## 九、设计取舍与扩展

### 41. 这个项目目前最大的设计取舍是什么？

为了保持 MVP 稳定，很多地方采用“安全默认值 + 可选增强 + 一次性闭环”，比如：

- 搜索补检索默认使用确定性规则，可配置为 Function Calling，并保留规则回退；
- 来源质量评分先用可解释规则；
- Reflection 最多修正一次；
- API 超时后不强杀后台线程，而是依赖底层 timeout 和协作式停止。

这些取舍降低复杂度，同时保留后续扩展点。

### 42. 如果要继续优化搜索质量，你会怎么做？

当前已经支持规则补检索和可插拔 Function Calling，可以继续从几个方向扩展：

- 评估 Function Calling 生成 query 的相关性、互补性和工具调用成功率；
- 增加补检索调用审计与更细粒度超时指标；
- 增加垂直领域来源白名单；
- 对全文抓取失败做更细粒度降级；
- 引入 embedding/rerank，提高相关性排序；
- 把来源质量规则配置化，方便不同场景调整权重；
- 在前端暴露更多来源质量原因，辅助调试。

### 43. 如果要优化报告质量，你会怎么做？

可以优化：

- Reporter prompt，让报告结构更稳定；
- 更严格要求每个关键结论都带引用；
- 增加段落级引用覆盖率检查；
- 让 Reflection 针对具体 warning 做局部修复；
- 保存初稿和修订稿 diff；
- 对 LLM Judge 增加维度权重或多模型交叉判断。

### 44. 如果要支持真正取消正在运行的研究任务，应该怎么改？

现在 `stop_requested` 是协作式信号，不强杀底层请求。要做真正取消，可以考虑：

- 给搜索和 LLM client 支持 cancellation token；
- 在 `TaskExecutor` worker 内定期检查取消信号；
- 将 per-run context 增加 cancel state；
- API 层提供取消接口；
- 对已取消任务发出 `workflow_cancelled` 或 `task_cancelled` 事件；
- 确保 notes 和 state 能记录 cancelled 状态。

### 45. 你认为项目里最能体现工程能力的点是什么？

可以重点讲三点：

- **可观测性**：全流程事件化，前端能看到 planner、search、summary、report、evaluator、reflection 的进度。
- **质量闭环**：报告不是生成完就结束，而是经过规则质检、可选 LLM Judge 和一次反思修正。
- **失败隔离**：单任务失败不影响其他任务；所有任务失败才终止报告；SSE 层有心跳、超时和统一异常事件。

### 46. Function Calling 补检索的完整调用链是什么？

调用链可以概括为：

```text
SearchQualityRetryService 判断首次来源质量不足
  -> FunctionCallingAgent 获取 supplemental_search Schema
  -> LLM 生成 tool_calls，不执行搜索
  -> ToolRegistry.execute_function() 校验参数并定位工具
  -> SupplementalSearchTool.run() 注入可信运行参数
  -> SearchTool.run() 调用真实搜索后端
  -> SearchService 合并、去重并重新评分
```

职责边界是：LLM 决定“补搜什么”，`ToolRegistry` 保证调用合法，
`SupplementalSearchTool` 做 Function Calling 到原搜索能力的适配，
`SearchTool` 才负责真正搜索。模型不能指定 backend、超时或最大结果数。

Function Calling 调用失败或没有返回可用结果时，系统会自动使用原有确定性规则
query 重试，不会直接中断研究任务。默认 `SEARCH_RETRY_MODE=rule`，因此该能力
可以按环境逐步启用。

## 十、复习检查清单

如果你能不看代码回答下面这些问题，说明主流程已经掌握得比较稳：

- `topic` 在哪里变成 `TodoItem[]`？
- 多任务并发在哪里实现？
- 单个任务为什么必须先 search 再 summary？
- `task.search_results` 和 `search_results_text` 区别是什么？
- `T1-S1` 这种 source_id 在哪里生成，为什么重要？
- 为什么参考文献和证据表不交给 LLM 自由生成？
- `state.evaluator` 主要包含什么信息？
- Reflection 触发条件有哪些？
- SSE 层为什么要 event queue？
- workflow 超时和 LLM idle timeout 分别解决什么问题？
- LLM、ToolRegistry、SupplementalSearchTool 和 SearchTool 在补检索中分别负责什么？
