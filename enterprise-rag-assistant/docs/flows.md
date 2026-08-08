# 流程图

本页用流程图描述项目的关键执行路径。

## 启动与索引构建

```mermaid
flowchart TD
    Start["启动 app.py"] --> Config["读取 Config<br/>模型、路径、API Key"]
    Config --> Clients["初始化 QwenChatClient<br/>DashScopeEmbeddingClient"]
    Clients --> Loader["创建 DataLoader"]
    Loader --> Index["创建 ChromaIndexManager"]
    Index --> Manifest{"文档签名是否变化?"}
    Manifest -- "是" --> LoadDocs["加载 rules/business 文档"]
    LoadDocs --> Split["切分为 Document chunks"]
    Split --> Rebuild["重建 Chroma collection"]
    Manifest -- "否" --> Reuse["复用已有 Chroma 索引"]
    Rebuild --> Service["组装 EnterpriseAssistantService"]
    Reuse --> Service
    Service --> UI["启动 Gradio UI"]
```

代码位置：

- `app.py::build_service()`
- `src/config.py::Config`
- `src/data_loader.py::DataLoader`
- `src/index_manager.py::ChromaIndexManager._ensure_indexes()`

## 普通 RAG 问答流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant UI as ui_app.py
    participant S as EnterpriseAssistantService
    participant R as QueryRouter
    participant E as RetrievalEnhancer
    participant C as ChromaIndexManager
    participant L as QwenChatClient

    U->>UI: 输入问题并选择策略
    UI->>S: service.answer(query, RetrievalOptions)
    S->>R: route(query)
    R-->>S: rules 或 business
    alt business
        S->>C: _search_business(query, top_k)
        C-->>S: docs
        S->>L: BUSINESS_PROMPT + context
        L-->>S: answer
    else rules
        S->>E: 根据 RetrievalStrategy 调用策略
        E->>C: 检索制度库
        C-->>E: docs
        E-->>S: RetrievalResult
        S->>L: RULE_PROMPT + context
        L-->>S: answer
    end
    S-->>UI: AnswerPackage
    UI-->>U: 答案、引用、上下文、调试信息
```

代码位置：

- `src/ui_app.py::_chat()`
- `src/rag_service.py::EnterpriseAssistantService.answer()`
- `src/rag_service.py::EnterpriseAssistantService._retrieval_rules()`
- `src/retrieval_enhance.py::RetrievalEnhancer`

## LlamaIndex 策略流程

```mermaid
flowchart TD
    UI["UI 选择 llama_* 策略"] --> Service["EnterpriseAssistantService"]
    Service --> Dispatch{"strategy in LLAMAINDEX_STRATEGY_METHODS?"}
    Dispatch -- "是" --> LlamaEnhancer["LlamaIndexRetrievalEnhancer"]
    LlamaEnhancer --> LlamaRetriever["LlamaIndex retriever/index/postprocessor"]
    LlamaRetriever --> Docs["List[Document]"]
    Docs --> Wrap["包装成 RetrievalResult"]
    Wrap --> Generate["service 统一生成答案"]
    Generate --> Answer["AnswerPackage"]
```

代码位置：

- `src/rag_service.py::LLAMAINDEX_STRATEGY_METHODS`
- `src/rag_service.py::_llamaindex_retrieve()`
- `src/llamaindex_retrieval_enhance.py::LlamaIndexRetrievalEnhancer`

## LangGraph Agentic RAG 流程

```mermaid
flowchart TD
    Start["service.answer()"] --> Check{"strategy == langgraph_agent?"}
    Check -- "是" --> Agent["EnterpriseLangGraphAgent.answer()"]
    Agent --> Plan["plan<br/>生成 route 和 search_queries"]
    Plan --> Route{"route"}
    Route -- "rules" --> Rules["retrieve_rules"]
    Route -- "business" --> Business["retrieve_business"]
    Route -- "both" --> Both["retrieve_both"]
    Rules --> Generate["generate"]
    Business --> Generate
    Both --> Generate
    Generate --> Reflect["reflect"]
    Reflect --> ReviseOrEnd{"需要修订?"}
    ReviseOrEnd -- "revise" --> Revise["revise"]
    Revise --> Reflect
    ReviseOrEnd -- "end" --> Result["LangGraphAgentResult"]
    Result --> Package["AnswerPackage"]
```

代码位置：

- `src/langgraph_enterprise_agent.py::EnterpriseLangGraphAgent._build_graph()`
- `src/rag_service.py::_langgraph_agent_answer()`

## RAG Triad 评估流程

```mermaid
flowchart TD
    Answer["生成 AnswerPackage 前"] --> Enabled{"enable_triad_eval?"}
    Enabled -- "否" --> Skip["跳过评估"]
    Enabled -- "是" --> Triad["RAGTriadEvaluator.evaluate()"]
    Triad --> AR["Answer Relevance<br/>答案是否回答问题"]
    Triad --> CR["Context Relevance<br/>上下文是否相关"]
    Triad --> G["Groundedness<br/>答案是否被上下文支撑"]
    AR --> Report["RAGTriadReport.to_text()"]
    CR --> Report
    G --> Report
    Report --> UI["展示在调试信息"]
```

代码位置：

- `src/rag_service.py::_maybe_evaluate_triad()`
- `src/rag_triad.py::RAGTriadEvaluator`
- `src/advanced_rag_types.py::RAGTriadReport`
