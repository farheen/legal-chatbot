"""Measure retrieval quality against a set of questions with known authorities.

Each line of the questions file is JSON: {"question": ..., "expected": ["1 A.3d 281", ...], "filters": {...}}.
A question is a hit when any expected citation belongs to a case among the top-k retrieved passages.

    python -m legalbot.evaluate                         # eval/questions.jsonl, full hybrid pipeline
    python -m legalbot.evaluate --no-vectors              # keyword-only baseline, for comparison
    python -m legalbot.evaluate --rerank                  # add the cross-encoder re-ranker
"""
import argparse
import json
from pathlib import Path

from .citations import normalize_cite
from .config import ROOT
from .db import connect
from .search import Filters, default_searcher


def evaluate(searcher, questions: list[dict], k: int) -> dict:
    conn = searcher.conn
    hits, reciprocal_ranks, misses = 0, [], []
    for q in questions:
        expected = {normalize_cite(c) for c in q["expected"]}
        passages = searcher.search(q["question"], Filters(**q.get("filters", {})), k=k)
        rank = None
        for i, p in enumerate(passages, 1):
            cites = {r[0] for r in conn.execute("SELECT norm_cite FROM case_citations WHERE case_id = ?", (p.case_id,))}
            if cites & expected:
                rank = i
                break
        if rank:
            hits += 1
            reciprocal_ranks.append(1 / rank)
        else:
            reciprocal_ranks.append(0.0)
            misses.append({"question": q["question"], "expected": q["expected"], "got": [p.citation for p in passages[:5]]})
    n = len(questions)
    return {"questions": n, f"recall@{k}": hits / n if n else 0.0, "mrr": sum(reciprocal_ranks) / n if n else 0.0, "misses": misses}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", type=Path, default=ROOT / "eval" / "questions.jsonl")
    parser.add_argument("-k", type=int, default=8)
    parser.add_argument("--no-vectors", action="store_true")
    parser.add_argument("--rerank", action="store_true")
    args = parser.parse_args()
    questions = [json.loads(line) for line in args.questions.read_text().splitlines() if line.strip()]
    searcher = default_searcher(connect(), use_vectors=not args.no_vectors, use_reranker=args.rerank)
    report = evaluate(searcher, questions, args.k)
    for miss in report.pop("misses"):
        print(f"MISS: {miss['question']}\n      expected {miss['expected']}, top results {miss['got']}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
