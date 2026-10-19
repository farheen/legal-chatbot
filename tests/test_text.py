from legalbot.chunking import chunk_text
from legalbot.citations import find_citations, normalize_cite


def test_chunks_respect_paragraphs_and_size():
    text = "\n".join(f"Paragraph {i}. " + "word " * 100 for i in range(20))
    chunks = chunk_text(text, target=1200, max_chars=2000)
    assert all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks).count("Paragraph") == 20  # nothing lost
    assert all(c.startswith("Paragraph") for c in chunks)  # splits land on paragraph boundaries


def test_long_paragraph_split_at_sentences():
    text = "The court held that the statute applies. " * 200
    chunks = chunk_text(text, target=1200, max_chars=2000)
    assert len(chunks) > 1
    assert all(c.endswith("applies.") for c in chunks)


def test_find_citations():
    text = "See 1 A.3d 281, 285; 100 F. Supp. 2d 5; 535 U.S. 1; but not 8 Del. C. 220 or 42 U.S.C. 1983."
    assert find_citations(text) == ["1 A.3d 281", "100 F. Supp. 2d 5", "535 U.S. 1"]


def test_normalize_cite():
    assert normalize_cite("100 F. Supp. 2d 5") == normalize_cite("100  F.Supp.2d 5") == "100 F.Supp.2d 5"
