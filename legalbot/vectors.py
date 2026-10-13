"""Dense (embedding) index over passage chunks, stored with FAISS.

    python -m legalbot.vectors            # embed chunks that are not yet indexed
    python -m legalbot.vectors --rebuild  # start over
"""
import argparse
from pathlib import Path

import numpy as np

from .config import EMBED_MODEL, INDEX_DIR
from .db import connect

# BGE models expect this instruction on queries (not on passages).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder:
    def __init__(self, model_name: str = EMBED_MODEL):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        if self.model.device.type in ("mps", "cuda"):
            self.model.half()  # ~2x faster on GPU; vectors match fp32 to cosine > 0.999
        self.query_prefix = QUERY_PREFIX if "bge" in model_name.lower() else ""
        self.dim = self.model.get_embedding_dimension()

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(texts, batch_size=128, normalize_embeddings=True, convert_to_numpy=True).astype("float32")

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_passages([self.query_prefix + text])[0]


class VectorIndex:
    """Inner-product index over L2-normalized embeddings (cosine similarity), keyed by chunk id.

    8-bit scalar quantization keeps memory at ~dim bytes per chunk (e.g. ~300 MB for 800k chunks).
    """

    def __init__(self, dim: int, path: Path = INDEX_DIR / "chunks.faiss"):
        import faiss

        # faiss and torch each bundle their own OpenMP runtime on macOS; letting both run
        # multithreaded in one process segfaults inside faiss. Single-threaded faiss is fast enough here.
        faiss.omp_set_num_threads(1)
        self.faiss = faiss
        self.path = path
        if path.exists():
            self.index = faiss.read_index(str(path))
        else:
            base = faiss.IndexScalarQuantizer(dim, faiss.ScalarQuantizer.QT_8bit, faiss.METRIC_INNER_PRODUCT)
            self.index = faiss.IndexIDMap2(base)

    def __len__(self) -> int:
        return self.index.ntotal

    def ids(self) -> set[int]:
        return set(self.faiss.vector_to_array(self.index.id_map).tolist())

    def add(self, ids: np.ndarray, vectors: np.ndarray) -> None:
        if not self.index.is_trained:
            self.index.train(vectors)
        self.index.add_with_ids(vectors, ids.astype("int64"))

    def remove(self, ids: list[int]) -> None:
        if ids:
            self.index.remove_ids(np.array(ids, dtype="int64"))

    def search(self, query: np.ndarray, k: int, allowed_ids: list[int] | None = None) -> list[tuple[int, float]]:
        if len(self) == 0:
            return []
        params = None
        if allowed_ids is not None:
            if not allowed_ids:
                return []
            params = self.faiss.SearchParameters(sel=self.faiss.IDSelectorBatch(np.array(allowed_ids, dtype="int64")))
        scores, ids = self.index.search(query.reshape(1, -1).astype("float32"), k, params=params)
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        self.faiss.write_index(self.index, str(tmp))
        tmp.replace(self.path)


def build(rebuild: bool = False, batch: int = 4096) -> None:
    from tqdm import tqdm

    conn = connect()
    embedder = Embedder()
    path = INDEX_DIR / "chunks.faiss"
    if rebuild and path.exists():
        path.unlink()
    index = VectorIndex(embedder.dim, path)

    indexed = index.ids()
    current = {row[0] for row in conn.execute("SELECT id FROM chunks")}
    index.remove(sorted(indexed - current))  # chunks deleted by a re-ingest
    todo = sorted(current - indexed)
    print(f"{len(indexed & current)} chunks already indexed, {len(todo)} to embed")

    if todo and not index.index.is_trained:
        # The 8-bit quantizer needs value ranges; train it on a sample before adding.
        sample = todo[:: max(1, len(todo) // 20000)][:20000]
        texts = _texts(conn, sample)
        index.index.train(embedder.embed_passages(texts))

    for start in tqdm(range(0, len(todo), batch), desc="Embedding"):
        ids = todo[start : start + batch]
        index.add(np.array(ids), embedder.embed_passages(_texts(conn, ids)))
        if (start // batch) % 25 == 24:
            index.save()  # checkpoint so an interrupted run can resume
    index.save()
    print(f"Index holds {len(index)} chunks at {path}")


def _texts(conn, ids: list[int]) -> list[str]:
    placeholders = ",".join("?" * len(ids))
    by_id = dict(conn.execute(f"SELECT id, text FROM chunks WHERE id IN ({placeholders})", ids).fetchall())
    return [by_id[i] for i in ids]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    build(rebuild=args.rebuild)


if __name__ == "__main__":
    main()
