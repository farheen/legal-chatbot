"""Split opinion text into passage-sized chunks along paragraph boundaries."""
import re

from .config import CHUNK_MAX_CHARS, CHUNK_TARGET_CHARS

_SENTENCE_END = re.compile(r"(?:(?<=[.?!])|(?<=[.?!][\"”’)]))\s+(?=[A-Z(“\"])")


def _split_long(paragraph: str, target: int, max_chars: int) -> list[str]:
    """Break a long paragraph into ~target-char pieces at sentence ends (hard-wrapping only sentences over max_chars)."""
    pieces, current = [], ""
    for sentence in _SENTENCE_END.split(paragraph):
        while len(sentence) > max_chars:
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if current and len(current) + 1 + len(sentence) > target:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text: str, target: int = CHUNK_TARGET_CHARS, max_chars: int = CHUNK_MAX_CHARS) -> list[str]:
    """Greedily pack paragraphs into chunks of about `target` chars, never exceeding `max_chars`."""
    paragraphs = []
    for para in text.split("\n"):
        para = " ".join(para.split())
        if not para:
            continue
        paragraphs.extend(_split_long(para, target, max_chars) if len(para) > max_chars else [para])

    chunks, current = [], ""
    for para in paragraphs:
        if current and len(current) + 1 + len(para) > max_chars:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n{para}" if current else para
        if len(current) >= target:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks
