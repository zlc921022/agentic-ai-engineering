# 整体架构与设计取舍

## 仓库边界

两个子项目共享“Agent 工作流可观测、结果可评估、失败可降级”的工程原则，但保持独立依赖与运行时：

- `deep-research-agent` 面向开放域研究，核心难点是多阶段编排、外部检索质量、引用可信度与长链路稳定性。
- `enterprise-rag-assistant` 面向受控知识库，核心难点是知识路由、召回策略、上下文质量与答案忠实度。

## 共同设计原则

1. **编排与能力解耦**：工作流节点只负责状态推进，检索、生成、评估以独立服务承载。
2. **确定性约束模型能力**：工具参数、引用表、证据表和质量门由代码控制，模型负责语义判断。
3. **失败可降级**：补检索、单任务、评估器失败均有明确回退或隔离路径。
4. **质量可测量**：将单元测试、离线评估、真实回归与压力测试分层，避免用单次演示代替工程验证。
5. **可观测优先**：保留阶段事件、策略、命中上下文、引用和评估结果，支持定位检索、生成或编排问题。

## 详细设计

- [Deep Research 核心流程](../deep-research-agent/docs/core-workflow.md)
- [Enterprise RAG 总体架构](../enterprise-rag-assistant/docs/architecture.md)
- [Enterprise LangGraph Agent](../enterprise-rag-assistant/docs/langgraph-agent.md)
