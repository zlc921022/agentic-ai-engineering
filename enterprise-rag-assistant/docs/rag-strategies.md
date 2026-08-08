# RAG 常用策略说明

本页整理项目中已经实现的 RAG 策略。重点看三个问题：

1. 这个策略解决什么问题。
2. 核心思想是什么。
3. 在代码里从哪里进入。

策略枚举统一定义在：

- `src/rag_types.py::RetrievalStrategy`

策略分发主要在：

- `src/rag_service.py::EnterpriseAssistantService._retrieval_rules()`
- `src/rag_service.py::EnterpriseAssistantService.LLAMAINDEX_STRATEGY_METHODS`

## 策略总览

| 实现分组 | UI 选项 | 典型用途 |
| --- | --- | --- |
| LangChain/手写版 | `langchain` | 学习和展示常见 RAG 增强策略 |
| LlamaIndex 版 | `llamaindex` | 对照成熟框架里的检索器、索引和后处理器 |
| LangGraph Agent | `langgraph` | 学习 Agentic RAG 的状态图编排 |

## 基础与混合检索

| 策略 | 核心思想 | 代码位置 |
| --- | --- | --- |
| `plain` | 直接用用户问题做向量检索，作为所有策略的 baseline | `src/retrieval_enhance.py::plain_retrieve()` |
| `hybrid` | 同时使用 BM25 关键词检索和向量检索，再按权重融合 | `src/retrieval_enhance.py::hybrid_retrieve()` |
| `rerank` 控制项 | 先召回候选，再让 LLM 逐条或批量判断相关性，保留 top N | `src/retrieval_enhance.py::rerank()`，service 层统一触发 |

适合先从 `plain` 和 `hybrid` 对比学习：`plain` 看语义召回能力，`hybrid` 看关键词和语义互补。

## Query Transformation

| 策略 | 核心思想 | 代码位置 |
| --- | --- | --- |
| `query2doc` | 先让 LLM 生成一段“理想答案/假文档”，用这段文本去检索 | `src/retrieval_enhance.py::query2doc_retrieve()` |
| `hyde` | HyDE: 生成 hypothetical document，再用生成文本增强召回 | `src/retrieval_enhance.py::hyde_retrieve()` |
| `rewrite` | 先把用户问题改写成更适合检索的表达 | `src/retrieval_enhance.py::question_rewrite_retrieve()` |
| `step_back` | 从具体问题抽象出更高层问题，先找规则背景再回答 | `src/retrieval_enhance.py::step_back_retrieve()` |
| `sub_question` | 把复杂问题拆成多个子问题分别检索，再合并上下文 | `src/retrieval_enhance.py::sub_question_retrieve()` |

这组策略的共同点是：**不直接相信用户原问题就是最好的检索 query**。它们先改造 query，再检索。

## 多索引与结构化召回

| 策略 | 核心思想 | 代码位置 |
| --- | --- | --- |
| `parent_child` | 用小 chunk 检索提升命中精度，返回父文档保留完整上下文 | `src/multi_index_retriever.py::parent_child_retrieve()` |
| `summary_index` | 给文档建立摘要索引，适合总结型、概览型问题 | `src/multi_index_retriever.py::summary_retrieve()` |
| `hypothetical_question` | 为文档 chunk 生成可能被问到的问题，用问题索引增强匹配 | `src/multi_index_retriever.py::hypothetical_question_retrieve()` |
| `multi_index` | 多种索引并行召回，再去重合并 | `src/multi_index_retriever.py::multi_index_retrieve()` |

这组策略的核心是：**不要只建一种索引**。不同问题形态适合不同索引表达。

## 上下文增强策略

| 策略 | 核心思想 | 代码位置 |
| --- | --- | --- |
| `sentence_window` | 检索命中的句子，但返回其前后窗口，缓解 chunk 切断语义的问题 | `src/advanced_retrieval.py::SentenceWindowRetriever`，入口 `src/retrieval_enhance.py::sentence_window_retriever()` |
| `auto_merging` | 检索子 chunk，若同一父文档命中足够多，则合并回父文档 | `src/advanced_retrieval.py::AutoMergingRetriever`，入口 `src/retrieval_enhance.py::auto_merging_retriever()` |

这组策略解决的是：检索命中了片段，但片段上下文不完整。

## 迭代与自校验

| 策略 | 核心思想 | 代码位置 |
| --- | --- | --- |
| `iterative` | 先检索一轮，再基于已有上下文生成补充查询继续检索 | `src/retrieval_enhance.py::iterative_retrieve()` |
| `self_rag` | 检索后让模型判断上下文是否足够、答案是否需要修正 | `src/self_rag_retriever.py::self_rag_answer()` |
| `self_rag_langgraph` | 用 LangGraph 状态图实现 Self-RAG 节点流 | `src/self_rag_retriever.py::self_rag_answer_langgraph()` |

这组策略从“单次检索”走向“检索-判断-修正”。

## LlamaIndex 版策略

这些策略在 UI 的 `llamaindex` 实现下选择。service 层通过 `LLAMAINDEX_STRATEGY_METHODS` 将枚举映射到 `LlamaIndexRetrievalEnhancer` 方法。

| 策略 | 核心思想 | 代码位置 |
| --- | --- | --- |
| `llama_plain` | LlamaIndex VectorStoreIndex 基础向量检索 | `src/llamaindex_retrieval_enhance.py::plain_retrieve()` |
| `llama_sentence_window` | LlamaIndex SentenceWindowNodeParser + MetadataReplacementPostProcessor | `src/llamaindex_retrieval_enhance.py::sentence_window_retrieve()` |
| `llama_auto_merging` | LlamaIndex HierarchicalNodeParser + AutoMergingRetriever | `src/llamaindex_retrieval_enhance.py::auto_merging_retrieve()` |
| `llama_hyde` | LlamaIndex HyDEQueryTransform | `src/llamaindex_retrieval_enhance.py::hyde_retrieve()` |
| `llama_query_fusion` | 多查询生成 + QueryFusionRetriever + RRF 融合 | `src/llamaindex_retrieval_enhance.py::llama_query_fusion_retrieve()` |
| `llama_hybrid` | LlamaIndex BM25 + vector 的混合检索 | `src/llamaindex_retrieval_enhance.py::hybrid_retrieve()` |
| `llama_rerank` | LlamaIndex LLMRerank 后处理 | `src/llamaindex_retrieval_enhance.py::rerank_retrieve()` |
| `llama_router` | RouterRetriever 在多个检索工具之间选择 | `src/llamaindex_retrieval_enhance.py::llama_router_retrieve()` |
| `llama_recursive` | RecursiveRetriever 先查入口节点，再深入子索引 | `src/llamaindex_retrieval_enhance.py::llama_recursive_retrieve()` |
| `llama_summary` | SummaryIndex，适合总结型问题 | `src/llamaindex_retrieval_enhance.py::summary_retrieve()` |
| `llama_auto_retrieval` | VectorIndexAutoRetriever，结合 metadata schema 自动构造检索 | `src/llamaindex_retrieval_enhance.py::llama_auto_retrieval_retrieve()` |
| `llama_graph` | PropertyGraphIndex/KnowledgeGraphIndex 风格 GraphRAG | `src/llamaindex_retrieval_enhance.py::llama_graph_retrieve()` |

LlamaIndex 版策略适合作为对照学习：同一个思想，看看成熟框架是如何封装索引、retriever、postprocessor 的。

## LangGraph Agentic RAG

| 策略 | 核心思想 | 代码位置 |
| --- | --- | --- |
| `langgraph_agent` | Agent 先规划 route 和查询，再检索、生成、反思、必要时修订 | `src/langgraph_enterprise_agent.py::EnterpriseLangGraphAgent` |

service 层入口：

- `src/rag_service.py::_langgraph_agent_answer()`

UI 入口：

- `src/ui_app.py::_strategy_choices()`
- 选择 `检索实现 = langgraph`

这个策略不只是检索增强，而是一个小型 Agent 编排：

```text
plan -> retrieve_rules/retrieve_business/retrieve_both -> generate -> reflect -> revise/end
```

## 如何选择策略

| 场景 | 推荐策略 |
| --- | --- |
| 想要 baseline | `plain` |
| 制度条款里关键词很重要 | `hybrid` |
| 用户问题表达口语化 | `rewrite`、`query2doc`、`hyde` |
| 一个问题包含多个点 | `sub_question` |
| 问题需要背景规则 | `step_back` |
| chunk 太碎导致回答缺上下文 | `sentence_window`、`auto_merging` |
| 想对照 LlamaIndex 实现 | `llama_hybrid`、`llama_recursive` |
| 想学习 Agent 编排 | `langgraph_agent` |
| 想调试 RAG 质量 | 任意策略 + `enable_triad_eval` |
