"""
Knowledge base: ingest + kb_search.  OWNER: P3.

Stack (blueprint 2.9): embedded persistent Chroma + BAAI/bge-small-en-v1.5 via
sentence-transformers on device="cpu".  CPU is a REQUIREMENT, not a compromise:
an embedding model on the GPU forces an Ollama eviction on every search.

Chunking: 800 characters, 150 overlap, recursive split on "\\n\\n" -> "\\n" ->
". " -> " ".  Forty lines, written here.  No LangChain, no LlamaIndex.

Retrieval: top-k 5, then filter by cosine distance < 0.75.  NOTE that
config/models.yaml deliberately leaves `retrieval.top_k` and `distance_cutoff`
null pending calibration on a labelled query set - the constants below are the
blueprint defaults and P3 replaces them with calibrated values.

MOCK MODE returns fixture chunks with `simulated` labelling upstream.  Nothing
in this module imports chromadb or sentence-transformers at module scope, so a
teammate with neither installed can still run the whole app.
"""

from __future__ import annotations

from typing import Iterable, Optional

from ..config import Settings
from ..contracts import Chunk, ChunkMetadata, ErrorCode, KbSearchArgs
from .base import ToolContext, ToolError, optional_import

CHUNK_CHARS = 800
CHUNK_OVERLAP = 150
DEFAULT_TOP_K = 5
DISTANCE_CUTOFF = 0.75
COLLECTION = "setu_corpus"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

_SEPARATORS = ("\n\n", "\n", ". ", " ")


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Recursive character split.  Deterministic, dependency-free, testable."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    def split(block: str, depth: int = 0) -> list[str]:
        if len(block) <= size:
            return [block]
        if depth >= len(_SEPARATORS):
            return [block[i : i + size] for i in range(0, len(block), size - overlap)]
        sep = _SEPARATORS[depth]
        parts = block.split(sep)
        if len(parts) == 1:
            return split(block, depth + 1)
        out: list[str] = []
        buf = ""
        for part in parts:
            candidate = (buf + sep + part) if buf else part
            if len(candidate) <= size:
                buf = candidate
            else:
                if buf:
                    out.extend(split(buf, depth + 1))
                buf = part
        if buf:
            out.extend(split(buf, depth + 1))
        return out

    pieces = [p.strip() for p in split(text) if p.strip()]
    # Re-apply overlap between adjacent pieces so a claim spanning a boundary is
    # still retrievable.
    if overlap <= 0 or len(pieces) < 2:
        return pieces
    overlapped = [pieces[0]]
    for prev, cur in zip(pieces, pieces[1:]):
        tail = prev[-overlap:]
        overlapped.append((tail + " " + cur).strip())
    return overlapped


class KnowledgeBase:
    """Real Chroma-backed KB.  Every heavy import happens inside a method."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None
        self._collection = None
        self._embedder = None

    def _ensure(self):
        if self._collection is not None:
            return self._collection
        chromadb = optional_import("chromadb", owner="P3", purpose="knowledge base")
        self._client = chromadb.PersistentClient(path=str(self.settings.kb_path))
        self._collection = self._client.get_or_create_collection(
            COLLECTION, metadata={"hnsw:space": "cosine"}
        )
        return self._collection

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedder is None:
            st = optional_import(
                "sentence_transformers", owner="P3", purpose="CPU embeddings"
            )
            # device="cpu" is deliberate; see the module docstring.
            self._embedder = st.SentenceTransformer(EMBED_MODEL, device="cpu")
        return [list(map(float, v)) for v in self._embedder.encode(texts)]

    def ingest(self, docs: Iterable[tuple[str, int, str]]) -> int:
        """NOT IMPLEMENTED - P3.

        `docs` is an iterable of (source_file, page, text).  Implementation must:
          - chunk with chunk_text()
          - run security.injection.scan() on each chunk BEFORE indexing
          - quarantine flagged chunks and surface them, never silently index
          - store ChunkMetadata fields verbatim so citations can be rendered

        Acceptance (P3): `kb_search("hydrotest acceptance criteria")` over
        data/kb_corpus returns >= 3 chunks from the expected SOP with distance
        below the calibrated cutoff, and the injected demo PDF produces exactly
        one quarantined chunk.
        """
        raise NotImplementedError("P3 owns KB ingestion (tools/kb.py::ingest)")

    def search(self, query: str, k: int = DEFAULT_TOP_K) -> list[Chunk]:
        collection = self._ensure()
        if collection.count() == 0:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                "knowledge base is empty: run the P3 ingestion over data/kb_corpus "
                "first, or use mock mode",
            )
        res = collection.query(
            query_embeddings=self._embed([query]), n_results=k,
            include=["documents", "metadatas", "distances"],
        )
        out: list[Chunk] = []
        for text, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            if dist >= DISTANCE_CUTOFF:
                continue
            out.append(
                Chunk(
                    chunk_id=str(meta.get("chunk_id", "unknown")),
                    text=text,
                    distance=float(dist),
                    metadata=ChunkMetadata(
                        source_file=str(meta.get("source_file", "unknown")),
                        page=int(meta.get("page", 1)),
                        chunk_id=str(meta.get("chunk_id", "unknown")),
                        trust_level=str(meta.get("trust_level", "untrusted")),  # type: ignore[arg-type]
                    ),
                )
            )
        return out


_KB_SINGLETON: Optional[KnowledgeBase] = None


def kb_search(args: KbSearchArgs, ctx: ToolContext) -> dict:
    """Real-mode handler.  The mock adapter lives in app/mocks/adapters.py."""
    global _KB_SINGLETON
    if _KB_SINGLETON is None:
        _KB_SINGLETON = KnowledgeBase(ctx.settings)
    chunks = _KB_SINGLETON.search(args.query, args.k)
    from ..security.injection import screen_chunks

    clean, quarantined = screen_chunks(chunks)
    return {
        "query": args.query,
        "chunks": [c.model_dump() for c in clean],
        "quarantined": [c.model_dump() for c in quarantined],
        "count": len(clean),
    }
