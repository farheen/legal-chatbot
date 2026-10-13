# Case Law Research Assistant

A research assistant for lawyers. It searches a case-law collection, and Claude answers each question **only from the passages it retrieved**, citing every passage it relies on. Each answer is then checked automatically against the database.

It is a research aid, not legal advice, and not a citator: lawyers must verify every authority before relying on it.

## How it works

1. **Ingest** (`legalbot.ingest`): Caselaw Access Project (CAP) volume zips are loaded into SQLite. Each case keeps all its opinions (majority, concurrences, dissents), every citation it is published under, and every citation it makes. Opinions are split into passages along paragraph breaks.
2. **Search** (`legalbot.search`): keyword search (SQLite FTS5, BM25) and embedding search (FAISS, `BAAI/bge-small-en-v1.5`) are merged with Reciprocal Rank Fusion. On top of that:
   - cases the question cites ("1 A.3d 281") or names ("Revlon v. MacAndrews") are pinned first;
   - cases cited by several of the top results are added as candidates, since that is usually the leading authority on the point;
   - filters (jurisdiction, court, date range) apply to every step.
3. **Answer** (`legalbot.answer`): Claude (`claude-opus-5-5`) gets the numbered passages and must cite them as `[P1]`, `[P2]`, …, quote only verbatim, and say when the passages don't answer the question.
4. **Verify** (`legalbot.verify`): every case citation in the answer is looked up in the database, every `[P#]` must point to a real passage, and every quotation must appear verbatim in a passage. Problems are shown to the user in red.
5. **Treatment** (`legalbot.treatment`): the case viewer shows how many later cases in the database cite the case, and flags nearby language such as "overruled" or "abrogated". This only sees cases in this database, so it is a prompt to check a citator, not a substitute for one.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # then fill in ANTHROPIC_API_KEY and LEGALBOT_SECRET_KEY
```

### Build the data

```bash
python -m legalbot.download --list                 # reporter slugs on static.case.law
python -m legalbot.download a2d a3d                # saves data/raw/<reporter>/<volume>.zip
python -m legalbot.ingest                          # zips -> data/legal.db (82k cases: ~4 min)
python -m legalbot.vectors                         # embeddings -> data/index/ (851k passages: ~2.5 h on Apple silicon; resumable)
```

`legalbot.ingest --jurisdiction Delaware` limits the import to one jurisdiction. `legalbot.vectors` only embeds passages that aren't indexed yet, so you can rerun it after adding data.

To add opinions newer than CAP's cutoff, get a free [CourtListener](https://www.courtlistener.com) API token and run:

```bash
COURTLISTENER_API_TOKEN=... python -m legalbot.courtlistener --court del --court delch --filed-after 2018-01-01
python -m legalbot.vectors
```

### Run

```bash
python -m legalbot.auth add-user alice             # prompts for a password (12+ characters)
set -a; source .env; set +a
uvicorn app.server:app --port 8000                 # LEGALBOT_DEV=1 for plain-HTTP local use
```

Or build the Docker image, mounting the data directory at `/data`:

```bash
docker build -t legalbot .
docker run --env-file .env -v "$PWD/data:/data" -p 8000:8000 legalbot
```

In production, serve it behind HTTPS (session cookies are `Secure` unless `LEGALBOT_DEV=1`).

## Measuring quality

`eval/questions.jsonl` has questions paired with the authority a lawyer would expect (currently 20 Delaware corporate-law questions). To score retrieval:

```bash
python -m legalbot.evaluate                        # hybrid search
python -m legalbot.evaluate --no-vectors           # keyword-only baseline
python -m legalbot.evaluate --rerank               # with the cross-encoder re-ranker
```

The output gives recall@8 (did the expected authority appear in the 8 passages Claude sees?) and MRR. It also prints each miss. Before changing anything in search, run this command and compare. The question set should grow to 50+ questions written or reviewed by practicing lawyers in the jurisdictions you serve.

## Tests

```bash
pytest
```

## Confidentiality and professional-responsibility notes

- Questions can contain client confidences. Use an Anthropic organization whose data-retention and no-training terms your firm has approved. Set `LEGALBOT_AUDIT_QUESTIONS=0` to keep question text out of the audit log.
- Every login, question, and opened case is written to the `audit_log` table.
- The UI tells users to verify every authority (see ABA Formal Opinion 512 on lawyers' use of generative AI).
- Coverage is limited to the volumes you download. For example, the default collection lacks some landmark cases (*Commonwealth v. Edmunds*, 586 A.2d 887). The answer prompt tells Claude to say when the passages don't answer the question, so it doesn't fill gaps from memory.
