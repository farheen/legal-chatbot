"""Answer a research question from retrieved passages with Claude, citing each passage used."""
from collections.abc import Iterator
from html import escape

import anthropic

from .config import LLM_EFFORT, LLM_MODEL
from .search import Passage

SYSTEM_PROMPT = """You are a legal research assistant for practicing lawyers. You answer questions using only the case-law passages provided in the user's message.

How to answer:
- Base every legal statement on the provided passages. After each sentence that relies on a passage, cite it with its marker, e.g. [P2] or [P1, P4].
- When you name a case, give its name and citation exactly as shown in the passage metadata.
- Quote sparingly and exactly; only put text in quotation marks if it appears verbatim in a passage.
- Note the court, jurisdiction and year of each authority, since the user needs to judge whether it is binding or persuasive. Distinguish majority opinions from concurrences and dissents.
- If the passages do not answer the question, or only partly answer it, say so plainly and describe what is missing (for example a different jurisdiction, more recent authority, or statutory text). Do not fill gaps from general knowledge, and never cite a case that is not in the passages.
- The passages come from a historical case-law collection that may not reflect later developments. Do not state that a case is still good law.
- Be concise and organized: lead with the direct answer, then the supporting authorities.

You are a research aid for lawyers, not a substitute for their judgment; they will verify the authorities before relying on them."""


def format_passages(passages: list[Passage]) -> str:
    blocks = []
    for n, p in enumerate(passages, 1):
        attrs = {
            "id": f"P{n}", "case": p.case_name, "citation": p.citation or "", "court": p.court or "",
            "jurisdiction": p.jurisdiction or "", "date": p.decision_date or "",
            "opinion": " ".join(filter(None, [p.opinion_type, p.opinion_author])),
        }
        attr_text = " ".join(f'{k}="{escape(str(v), quote=True)}"' for k, v in attrs.items())
        blocks.append(f"<passage {attr_text}>\n{escape(p.text, quote=False)}\n</passage>")
    return "\n\n".join(blocks)


def build_messages(question: str, passages: list[Passage], history: list[dict] | None = None) -> list[dict]:
    """history: earlier turns as [{'role': 'user'|'assistant', 'content': str}, ...] (plain text only)."""
    if passages:
        context = f"<passages>\n{format_passages(passages)}\n</passages>"
    else:
        context = "<passages>\n(no passages matched this question)\n</passages>"
    return [*(history or []), {"role": "user", "content": f"{context}\n\nQuestion: {question}"}]


class AnswerError(Exception):
    """Raised with a user-presentable message when generation fails."""


def stream_answer(
    question: str, passages: list[Passage], history: list[dict] | None = None, client: anthropic.Anthropic | None = None,
) -> Iterator[str]:
    """Yield answer text as it is generated."""
    client = client or anthropic.Anthropic()
    try:
        with client.beta.messages.stream(
            model=LLM_MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=build_messages(question, passages, history),
            output_config={"effort": LLM_EFFORT},
            # If a safety classifier declines, the API retries on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            yield from stream.text_stream
            final = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise AnswerError("The language model rejected our credentials. Check ANTHROPIC_API_KEY.") from e
    except anthropic.RateLimitError as e:
        raise AnswerError("The language model is rate limited. Try again shortly.") from e
    except anthropic.APIStatusError as e:
        raise AnswerError(f"The language model returned an error ({e.status_code}).") from e
    except anthropic.APIConnectionError as e:
        raise AnswerError("Could not reach the language model.") from e

    if final.stop_reason == "refusal":
        raise AnswerError("The model declined to answer this question.")
    if final.stop_reason == "max_tokens":
        yield "\n\n[Answer truncated at the length limit.]"
