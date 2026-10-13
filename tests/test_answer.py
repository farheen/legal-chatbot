from types import SimpleNamespace

import pytest

from legalbot import answer
from legalbot.search import Searcher
from legalbot.verify import verify_answer


def test_verify_flags_problems(conn):
    passages = Searcher(conn).search("credible basis books and records section 220", k=3)
    good = (
        "A stockholder must show a proper purpose [P1]. The court in City of Westland, 1 A.3d 281, required "
        '"some evidence to suggest a credible basis" [P1].'
    )
    v = verify_answer(conn, good, passages)
    assert v.ok and v.used_passages == [1] and v.citations[0].status == "verified"

    bad = 'See Smith v. Jones, 999 A.2d 1 [P9]. The court said "a stockholder may inspect anything at all times".'
    v = verify_answer(conn, bad, passages)
    assert not v.ok
    assert v.invalid_markers == ["P9"]
    assert [c.status for c in v.citations] == ["unverified"]
    assert v.unmatched_quotes == ["a stockholder may inspect anything at all times"]


def test_cite_mentioned_only_in_a_passage_is_marked_in_sources(conn):
    with conn:
        conn.execute("DELETE FROM cases WHERE source_id = '1002'")
    passages = Searcher(conn).search("Westland books and records", k=2)
    v = verify_answer(conn, "Relying on 923 A.2d 810 [P1].", passages)
    assert v.citations[0].status == "in_sources"


def test_prompt_contains_passages_and_metadata(conn):
    passages = Searcher(conn).search("Westland", k=1)
    messages = answer.build_messages("What is required?", passages, [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}])
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    content = messages[-1]["content"]
    assert 'id="P1"' in content and 'citation="1 A.3d 281"' in content and "Question: What is required?" in content


class FakeStream:
    def __init__(self, chunks, stop_reason="end_turn"):
        self.text_stream = iter(chunks)
        self.final = SimpleNamespace(stop_reason=stop_reason)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.final


class FakeClient:
    def __init__(self, stream):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))
        self._s = stream

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return self._s


def test_stream_answer_passes_settings_and_yields_text():
    client = FakeClient(FakeStream(["Hello ", "world [P1]."]))
    assert "".join(answer.stream_answer("q", [], client=client)) == "Hello world [P1]."
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert call["system"] == answer.SYSTEM_PROMPT


def test_stream_answer_refusal_raises():
    client = FakeClient(FakeStream(["partial"], stop_reason="refusal"))
    with pytest.raises(answer.AnswerError):
        list(answer.stream_answer("q", [], client=client))
