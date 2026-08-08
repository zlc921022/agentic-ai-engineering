import json
from src.client import QwenChatClient, DashScopeEmbeddingClient
from src.config import Config
from src.data_loader import DataLoader
from src.index_manager import ChromaIndexManager
from src.retrieval_util import docs_to_context


class MiniEmployeeAgent:

    def __init__(self,
                 llm: QwenChatClient,
                 index_manager: ChromaIndexManager
                 ):
        self.llm = llm
        self.index_manager = index_manager

    # 判断问题类型，生成检索 query
    def plan(self, question: str):
        prompt = (
            "你是一个检索专家。请根据用户问题判断问题类型，并生成检索 query。\n"
            "问题类型只有两种：\n"
            "- rule：企业制度类，比如请假、报销、考勤、IT、入职等\n"
            "- business：经营业务类，比如营收、市场、投融资、季度经营等\n\n"
            "请严格返回 JSON，不要输出额外解释，格式如下：\n"
            '{{"type": "rule", "query": "内容"}}\n\n'
            "原始问题为: {question}"
        )
        llm_prompt = prompt.format(question=question)
        response = self.llm.complete(llm_prompt, temperature=0, max_tokens=1024)
        print(f"生成计划：{response}")
        return response

    def policy_search(self, query: str, k: int = 4):
        try:
            data = json.loads(query)
        except Exception as e:
            print(f"解析计划失败: {e}, 原始内容: {query}")
            data = {
                "type": "rule",
                "query": query,
            }
        query_type = data.get("type", "")
        new_query = data.get('query')
        if query_type == 'rule':
            docs = self.index_manager._search_rules(new_query, k)
        else:
            docs = self.index_manager._search_business(new_query, k)

        if not docs:
            return ""
        else:
            return docs_to_context(docs)

    # 基于制度上下文生成回答
    def generate(self, question: str, context: str):
        prompt = (
            "你是一个企业专家，请你根据问题和上下文生成答案。\n"
            "要求：回答要包含结论、步骤、依据。\n\n"
            "问题为: {question}\n"
            "上下文为: {context}\n"
        )
        llm_prompt = prompt.format(question=question, context=context)
        response = self.llm.complete(llm_prompt, temperature=0, max_tokens=2048)
        print(f"生成结果：{response}")
        return response

    def reflect(self, question: str, context: str, answer: str):
        prompt = ("你是一个企业反思专家，请你根据问题和上下文，答案，给我检查有没有依据、有没有回答问题、有没有下一步"
                  "如果无需优化，只输出 finish。如果需要优化，输出具体修改意见。"
                  "问题为: {question}"
                  "上下文为: {context}"
                  "答案为: {answer}"
                  "")
        llm_prompt = prompt.format(question=question, context=context, answer=answer)
        reflect_response = self.llm.complete(llm_prompt, temperature=0, max_tokens=2048)
        print(f"反思结果：{reflect_response}")
        return reflect_response

    def revise(self, question: str, context: str, reflect_answer: str):
        prompt = (
            "你是一个企业员工助手优化专家。请根据问题、上下文和反思意见，生成优化后的最终答案。\n"
            "要求：\n"
            "1. 必须基于上下文，不要编造制度。\n"
            "2. 补充缺失的依据、步骤或下一步建议。\n"
            "3. 回答要清晰、可执行。\n\n"
            "问题为: {question}\n"
            "上下文为: {context}\n"
            "反思意见为: {reflect_answer}\n"
        )
        llm_prompt = prompt.format(question=question, context=context, reflect_answer=reflect_answer)
        revise_response = self.llm.complete(llm_prompt, temperature=0, max_tokens=2048)
        print(f"优化结果：{revise_response}")
        return revise_response

    def run(self, question: str):
        plan_query = self.plan(question)
        context = self.policy_search(plan_query)
        answer = self.generate(question, context)
        reflect_answer = self.reflect(question, context, answer)
        if "finish" in reflect_answer.lower():
            return answer
        revise_answer = self.revise(question, context, reflect_answer)
        return revise_answer


if __name__ == "__main__":
    question = "差旅报销需要哪些材料？请按步骤说明，并给出依据。"
    config = Config()
    llm = QwenChatClient(config)
    loader = DataLoader(chunk_size=700, chunk_overlap=80)
    index_manager = ChromaIndexManager(
        config=config,
        embedding_client=DashScopeEmbeddingClient(config),
        data_loader=loader
    )
    index_manager._ensure_indexes()
    answer = MiniEmployeeAgent(
        llm= llm,
        index_manager=index_manager
    ).run(question)
    print(f"最终生成结果：{answer}")
