"""ChromaDB access layer.

ChromaDB is *embedded* — just local files, no server. Two stores are used:

* **Bundled, read-only** index at ``data/chroma_db`` shipped with the app
  (built offline by ``scripts/chunk_and_embed.py``).
* **Writable user index** in the per-user app-data dir, holding chunks from
  PDFs the user uploads at runtime.

Queries transparently search both and merge results.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional

from . import embeddings
from .paths import bundled_chroma_dir, user_chroma_dir

# Disable Chroma's telemetry up front. (Chroma 0.5.x + newer posthog emit a
# noisy but harmless "capture() takes 1 positional argument" error otherwise.)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

COLLECTION_NAME = "pyq_chunks"

_lock = threading.Lock()
_bundled_collection = None
_user_collection = None


def _make_client(path: str):
    import chromadb
    from chromadb.config import Settings

    return chromadb.PersistentClient(
        path=path,
        settings=Settings(anonymized_telemetry=False, allow_reset=False),
    )


def _get_bundled_collection():
    global _bundled_collection
    if _bundled_collection is None:
        with _lock:
            if _bundled_collection is None:
                client = _make_client(str(bundled_chroma_dir()))
                _bundled_collection = client.get_or_create_collection(
                    name=COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
    return _bundled_collection


def get_user_collection():
    """Writable collection for user-uploaded content."""
    global _user_collection
    if _user_collection is None:
        with _lock:
            if _user_collection is None:
                client = _make_client(str(user_chroma_dir()))
                _user_collection = client.get_or_create_collection(
                    name=COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
    return _user_collection


def _build_where(category: Optional[str], difficulty: Optional[str]) -> Optional[Dict[str, Any]]:
    clauses: List[Dict[str, Any]] = []
    if category and category != "All":
        clauses.append({"topic_tag": category})
    if difficulty and difficulty != "All":
        clauses.append({"difficulty": difficulty})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def query_chunks(
    query_text: str,
    top_k: int = 8,
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
    include_user_uploads: bool = True,
) -> List[Dict[str, Any]]:
    """Retrieve the most relevant chunks across bundled + user collections.

    Returns a list of dicts: ``{text, metadata, distance, source}``.
    """
    embedding = embeddings.embed_text(query_text)
    where = _build_where(category, difficulty)

    collections = [("bundled", _get_bundled_collection())]
    if include_user_uploads:
        try:
            collections.append(("user", get_user_collection()))
        except Exception:
            pass  # user store optional; never block retrieval on it

    results: List[Dict[str, Any]] = []
    for source, collection in collections:
        try:
            if collection.count() == 0:
                continue
        except Exception:
            continue
        try:
            res = collection.query(
                query_embeddings=[embedding],
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            continue
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for doc, meta, dist in zip(docs, metas, dists):
            results.append(
                {
                    "text": doc,
                    "metadata": meta or {},
                    "distance": dist,
                    "source": source,
                }
            )

    results.sort(key=lambda r: r["distance"] if r["distance"] is not None else 1e9)
    return results[:top_k]


def list_categories(include_user_uploads: bool = True) -> List[str]:
    """Distinct ``topic_tag`` values present in the store(s)."""
    tags = set()
    collections = [_get_bundled_collection()]
    if include_user_uploads:
        try:
            collections.append(get_user_collection())
        except Exception:
            pass
    for collection in collections:
        try:
            if collection.count() == 0:
                continue
            data = collection.get(include=["metadatas"])
        except Exception:
            continue
        for meta in data.get("metadatas") or []:
            tag = (meta or {}).get("topic_tag")
            if tag:
                tags.add(tag)
    return sorted(tags)


def add_chunks(chunks: List[Dict[str, Any]], to_user_store: bool = True) -> int:
    """Embed and add chunks. Each chunk: ``{id, text, metadata}``.

    Used by the offline prep pipeline (bundled store) and runtime PDF uploads
    (user store). Returns the number of chunks added.
    """
    if not chunks:
        return 0
    collection = get_user_collection() if to_user_store else _get_bundled_collection()
    ids = [c["id"] for c in chunks]
    docs = [c["text"] for c in chunks]
    metas = [c.get("metadata", {}) for c in chunks]
    vectors = embeddings.embed_texts(docs)
    collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=vectors)
    return len(chunks)


def clear_user_store() -> int:
    """Delete all user-uploaded chunks. Returns the number removed."""
    try:
        collection = get_user_collection()
    except Exception:
        return 0
    with _lock:
        try:
            ids = collection.get().get("ids") or []
        except Exception:
            ids = []
        if ids:
            collection.delete(ids=ids)
    return len(ids)


def list_user_sources() -> List[Dict[str, Any]]:
    """User-uploaded PDF sources grouped by ``topic_tag`` with chunk counts."""
    try:
        collection = get_user_collection()
        if collection.count() == 0:
            return []
        data = collection.get(include=["metadatas"])
    except Exception:
        return []
    counts: Dict[str, int] = {}
    for meta in data.get("metadatas") or []:
        tag = (meta or {}).get("topic_tag") or "Uploaded PDF"
        counts[tag] = counts.get(tag, 0) + 1
    return [{"source": s, "count": n} for s, n in sorted(counts.items())]


def delete_user_source(topic_tag: str) -> int:
    """Delete all user-uploaded chunks with the given ``topic_tag``.

    Returns the number of chunks removed.
    """
    try:
        collection = get_user_collection()
    except Exception:
        return 0
    with _lock:
        try:
            data = collection.get(where={"topic_tag": topic_tag})
            ids = data.get("ids") or []
        except Exception:
            ids = []
        if ids:
            collection.delete(ids=ids)
    return len(ids)
