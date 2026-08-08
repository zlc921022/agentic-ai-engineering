# 类图

本页展示核心类之间的协作关系。类图只保留关键字段和方法，便于理解项目结构。

## 主服务类图

```mermaid
classDiagram
    class Config {
        +base_dir
        +data_rule_dir
        +data_business_dir
        +chroma_dir
        +chat_model
        +embedding_model
        +ensure_dirs()
        +check()
    }

    class QwenChatClient {
        +complete(prompt, temperature, max_tokens)
        +stream(prompt, temperature, max_tokens)
    }

    class DashScopeEmbeddingClient {
        +embed_documents(texts)
        +embed_query(text)
        +get_embedding_function()
    }

    class DataLoader {
        +_split_text(text)
        +_directory_signature(data_dir)
        +_load_documents(data_dir, source_type)
    }

    class ChromaIndexManager {
        +rule_store
        +business_store
        +_ensure_indexes(force)
        +_search_rules(query, k)
        +_search_business(query, k)
        +_all_rule_documents()
    }

    class EnterpriseAssistantService {
        +answer(query, options)
        +_retrieval_rules(query, options)
        +_business_answer(query, options)
        +_rule_answer(query, options)
        +_langgraph_agent_answer(query, options)
        +_maybe_evaluate_triad(query, answer, docs, options)
    }

    Config --> QwenChatClient
    Config --> DashScopeEmbeddingClient
    Config --> ChromaIndexManager
    DataLoader --> ChromaIndexManager
    DashScopeEmbeddingClient --> ChromaIndexManager
    QwenChatClient --> EnterpriseAssistantService
    ChromaIndexManager --> EnterpriseAssistantService
```

代码位置：

- `src/config.py`
- `src/client.py`
- `src/data_loader.py`
- `src/index_manager.py`
- `src/rag_service.py`

## 检索增强类图

```mermaid
classDiagram
    class RetrievalOptions {
        +strategy
        +top_k
        +enable_rerank
        +rerank_top_n
        +rerank_method
        +bm25_weight
        +vector_weight
        +enable_triad_eval
    }

    class RetrievalResult {
        +strategy
        +docs
        +debug_note
    }

    class RetrievalEnhancer {
        +plain_retrieve(query, k)
        +hybrid_retrieve(query, k, bm25_weight, vector_weight)
        +query2doc_retrieve(query, k)
        +hyde_retrieve(query, k)
        +sub_question_retrieve(query, k)
        +question_rewrite_retrieve(query, k)
        +step_back_retrieve(query, k)
        +iterative_retrieve(query, k)
        +rerank(query, docs, top_n, method)
    }

    class MultiIndexRetriever {
        +parent_child_retrieve(query, k)
        +summary_retrieve(query, k)
        +hypothetical_question_retrieve(query, k)
        +multi_index_retrieve(query, k)
    }

    class SentenceWindowRetriever {
        +retrieve(query, k)
    }

    class AutoMergingRetriever {
        +retrieve(query, k)
    }

    class SelfRagRetriever {
        +self_rag_answer(query, k)
        +self_rag_answer_langgraph(query, k)
    }

    RetrievalOptions --> EnterpriseAssistantService
    EnterpriseAssistantService --> RetrievalEnhancer
    RetrievalEnhancer --> RetrievalResult
    RetrievalEnhancer --> MultiIndexRetriever
    RetrievalEnhancer --> SentenceWindowRetriever
    RetrievalEnhancer --> AutoMergingRetriever
    RetrievalEnhancer --> SelfRagRetriever
```

代码位置：

- `src/rag_types.py`
- `src/retrieval_types.py`
- `src/retrieval_enhance.py`
- `src/multi_index_retriever.py`
- `src/advanced_retrieval.py`
- `src/self_rag_retriever.py`

## LlamaIndex 与 LangGraph 类图

```mermaid
classDiagram
    class LlamaIndexRetrievalEnhancer {
        +plain_retrieve(query, k)
        +sentence_window_retrieve(query, k)
        +auto_merging_retrieve(query, k)
        +hyde_retrieve(query, k)
        +hybrid_retrieve(query, k)
        +rerank_retrieve(query, k)
        +summary_retrieve(query, k)
        +llama_query_fusion_retrieve(query, k)
        +llama_router_retrieve(query, k)
        +llama_recursive_retrieve(query, k)
        +llama_auto_retrieval_retrieve(query, k)
        +llama_graph_retrieve(query, k)
    }

    class EnterpriseLangGraphAgent {
        +answer(question, top_k, thread_id, revision_max)
        +stream_events(question, top_k, thread_id, revision_max)
        +plan(state)
        +retrieve_rules(state)
        +retrieve_business(state)
        +retrieve_both(state)
        +generate(state)
        +reflect(state)
        +revise(state)
    }

    class LangGraphAgentResult {
        +answer
        +context
        +references
        +route
        +docs
        +debug_note
        +plan
        +critique
        +needs_human_review
    }

    EnterpriseAssistantService --> LlamaIndexRetrievalEnhancer
    EnterpriseAssistantService --> EnterpriseLangGraphAgent
    EnterpriseLangGraphAgent --> LangGraphAgentResult
```

代码位置：

- `src/llamaindex_retrieval_enhance.py`
- `src/langgraph_enterprise_agent.py`
- `src/rag_service.py`

## 评估类图

```mermaid
classDiagram
    class RAGTriadEvaluator {
        +evaluate_answer_relevance(question, answer)
        +evaluate_context_relevance(question, docs)
        +evaluate_groundedness(answer, docs)
        +evaluate(question, answer, docs)
    }

    class TriadMetricResult {
        +name
        +score
        +reason
    }

    class RAGTriadReport {
        +answer_relevance
        +context_relevance
        +groundedness
        +context_items
        +average_score
        +to_text()
    }

    RAGTriadEvaluator --> TriadMetricResult
    RAGTriadEvaluator --> RAGTriadReport
    RAGTriadReport --> TriadMetricResult
    EnterpriseAssistantService --> RAGTriadEvaluator
```

代码位置：

- `src/rag_triad.py`
- `src/advanced_rag_types.py`
- `src/evaluator.py`
