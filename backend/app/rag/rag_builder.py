INSTRUCTIONS = '''
Your task is to answer questions from the database
based on the provided context.

Use the context to find relevant information and provide accurate
answers. If the answer is not found in the context,
respond with "I don't know."

Don't show similarity percentages
'''

PROMPT_TEMPLATE = '''
QUESTION: {question}

CONTEXT:
{context}
'''.strip()


class RAGPgVector:

    def __init__(
        self,
        llm_client,
        embedder,
        conn,
        instructions=INSTRUCTIONS,
        prompt_template=PROMPT_TEMPLATE,
        model='gpt-5.4-mini'
    ):
        self.llm_client = llm_client
        self.instructions = instructions
        self.prompt_template = prompt_template
        self.model = model
        self.embedder = embedder
        self.conn = conn

    def vec_to_str(self, vector):
        return '[' + ','.join(str(x) for x in vector) + ']'

    def search(self, query, num_results=5):
        query_vector = self.embedder.encode(query)
        query_str = self.vec_to_str(query_vector)

        rows = self.conn.execute(
            """
            SELECT
                doc_name,
                chunk_text,
                1 - (embedding <=> %s::vector) AS similarity
            FROM documents
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (query_str, query_str, num_results)
        )

        return [
            {'doc_name': r[0], 'chunk': r[1], 'similarity': r[2]}
            for r in rows
        ]

    def build_context(self, search_results):
        lines = []

        for doc in search_results:
            lines.append('doc: ' + doc['doc_name'])
            lines.append('text: ' + doc['chunk'])
            lines.append('')

        return '\n'.join(lines).strip()

    def build_prompt(self, query, search_results):
        context = self.build_context(search_results)
        return self.prompt_template.format(
            question=query, context=context
        )

    def llm(self, prompt):
        input_messages = [
            {'role': 'developer', 'content': self.instructions},
            {'role': 'user', 'content': prompt}
        ]

        response = self.llm_client.responses.create(
            model=self.model,
            input=input_messages
        )

        return response.output_text

    def rag(self, query):
        search_results = self.search(query)
        prompt = self.build_prompt(query, search_results)
        answer = self.llm(prompt)
        return answer
