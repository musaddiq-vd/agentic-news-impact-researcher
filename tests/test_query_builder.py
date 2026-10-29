from app.nodes.query_builder import QueryList, build_queries


class FakeLLM:
    """Mimics llm.with_structured_output(...).invoke(...)."""

    def __init__(self, queries=None, error=None):
        self.queries, self.error, self.messages = queries, error, None

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        self.messages = messages
        if self.error:
            raise self.error
        return QueryList(queries=self.queries)


def test_returns_llm_queries():
    llm = FakeLLM(["solar module price India", "polysilicon price"])
    assert build_queries("what is the module price?", llm=llm) == [
        "solar module price India", "polysilicon price",
    ]


def test_prompt_includes_question_topic_competitors():
    llm = FakeLLM(["q"])
    build_queries("my question", "policy", ["Waaree Energies"], llm=llm)
    user_msg = llm.messages[1][1]
    assert "my question" in user_msg and "policy" in user_msg and "Waaree Energies" in user_msg


def test_falls_back_to_question_on_error():
    llm = FakeLLM(error=RuntimeError("bedrock down"))
    assert build_queries("crude oil impact?", llm=llm) == ["crude oil impact?"]


def test_falls_back_when_llm_returns_nothing():
    assert build_queries("my question", llm=FakeLLM(["", "  "])) == ["my question"]


def test_caps_at_four_and_dedupes():
    llm = FakeLLM(["a", "a", "b", "c", "d", "e"])
    assert build_queries("q", llm=llm) == ["a", "b", "c", "d"]
