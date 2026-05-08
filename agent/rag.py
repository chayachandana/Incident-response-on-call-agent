# agent/rag.py
"""
RAG Runbook Retrieval — ChromaDB
=================================
Two responsibilities:
  1. ingest_runbooks()  — load markdown files, chunk, embed, store in ChromaDB
  2. retrieve_runbook() — semantic search given incident context

Uses sentence-transformers for local embeddings (no API key needed).
ChromaDB stores vectors on disk — persists between runs.

Usage:
  # One-time setup (or when runbooks change):
  python -m agent.rag

  # At runtime (called by fetch_runbook node):
  from agent.rag import retrieve_runbook
  result = retrieve_runbook("DB connection pool exhaustion checkout-service")
"""

import os
import glob
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

RUNBOOKS_DIR   = os.getenv("RUNBOOKS_DIR", "runbooks")
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", ".chromadb")
COLLECTION_NAME = "runbooks"

# Use local sentence-transformers model — no API key, runs on CPU
EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # fast, small, good for retrieval


def _get_collection():
    """Get or create the ChromaDB collection."""
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},   # cosine similarity
    )

    return collection


def _chunk_markdown(content: str, chunk_size: int = 500) -> list[str]:
    """
    Split a runbook into overlapping chunks.
    Splits on section headers first, then by character limit.
    Overlap ensures context isn't lost at chunk boundaries.
    """
    # Split on ## headers to keep sections together
    sections = []
    current = []

    for line in content.split("\n"):
        if line.startswith("## ") and current:
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        sections.append("\n".join(current))

    # If a section is too long, split by character with overlap
    chunks = []
    overlap = 100

    for section in sections:
        if len(section) <= chunk_size:
            chunks.append(section.strip())
        else:
            start = 0
            while start < len(section):
                end = start + chunk_size
                chunks.append(section[start:end].strip())
                start += chunk_size - overlap

    return [c for c in chunks if len(c) > 50]  # drop tiny chunks


def ingest_runbooks(force_reload: bool = False) -> int:
    """
    Load all markdown runbooks from runbooks/ directory,
    chunk them, embed, and store in ChromaDB.

    Returns number of chunks stored.
    Set force_reload=True to re-embed everything.
    """
    collection = _get_collection()

    # Skip if already loaded (unless forced)
    if not force_reload and collection.count() > 0:
        print(f"[rag] ChromaDB already has {collection.count()} chunks — skipping ingest")
        print(f"      Use force_reload=True to re-embed")
        return collection.count()

    if force_reload:
        # Clear existing data
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        client.delete_collection(COLLECTION_NAME)
        collection = _get_collection()

    runbook_files = glob.glob(f"{RUNBOOKS_DIR}/*.md")

    if not runbook_files:
        print(f"[rag] ⚠️  No runbook files found in {RUNBOOKS_DIR}/")
        return 0

    all_chunks    = []
    all_ids       = []
    all_metadatas = []

    for filepath in runbook_files:
        filename = Path(filepath).stem
        content  = Path(filepath).read_text()

        # Extract title from first line
        title = content.split("\n")[0].replace("# ", "").strip()

        chunks = _chunk_markdown(content)
        print(f"[rag] {filename}: {len(chunks)} chunks")

        for i, chunk in enumerate(chunks):
            chunk_id = f"{filename}_{i}"
            all_chunks.append(chunk)
            all_ids.append(chunk_id)
            all_metadatas.append({
                "filename":  filename,
                "title":     title,
                "chunk_idx": i,
                "filepath":  filepath,
            })

    # Batch upsert into ChromaDB
    collection.upsert(
        documents=all_ids,        # ChromaDB uses these as IDs
        ids=all_ids,
        metadatas=all_metadatas,
    )

    # Store actual text separately (ChromaDB stores embeddings, we store text)
    # Use add() with documents for text storage + embedding
    collection.upsert(
        ids=all_ids,
        documents=all_chunks,
        metadatas=all_metadatas,
    )

    total = len(all_chunks)
    print(f"[rag] ✅ Ingested {total} chunks from {len(runbook_files)} runbooks")
    return total


def retrieve_runbook(
    query: str,
    n_results: int = 1,
    min_relevance_score: float = 0.3,
) -> dict:
    """
    Semantic search for the most relevant runbook.

    Args:
        query: natural language description of the incident
               e.g. "DB connection pool exhaustion checkout-service"
        n_results: how many chunks to retrieve
        min_relevance_score: minimum cosine similarity (0-1)

    Returns:
        {
          "title": str,
          "filename": str,
          "content": str,        # full runbook text
          "relevance_score": float,
          "matched_chunks": list
        }
    """
    collection = _get_collection()

    if collection.count() == 0:
        print("[rag] ⚠️  No runbooks in ChromaDB — running ingest first")
        ingest_runbooks()

    results = collection.query(
        query_texts=[query],
        n_results=min(n_results * 3, collection.count()),  # get extras, pick best
        include=["documents", "metadatas", "distances"],
    )

    if not results["ids"][0]:
        return _fallback_runbook()

    # ChromaDB returns distance (lower = more similar for cosine)
    # Convert to similarity score: score = 1 - distance
    best_chunks    = []
    seen_files     = {}

    for i, (doc, meta, dist) in enumerate(zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    )):
        score    = round(1 - dist, 4)
        filename = meta["filename"]

        if score < min_relevance_score:
            continue

        if filename not in seen_files:
            seen_files[filename] = {
                "filename": filename,
                "title":    meta["title"],
                "score":    score,
                "chunks":   [],
            }

        seen_files[filename]["chunks"].append(doc)
        seen_files[filename]["score"] = max(seen_files[filename]["score"], score)

    if not seen_files:
        return _fallback_runbook()

    # Pick the file with highest relevance score
    best_file = max(seen_files.values(), key=lambda x: x["score"])

    # Read the full runbook content from disk
    filepath = f"{RUNBOOKS_DIR}/{best_file['filename']}.md"
    full_content = Path(filepath).read_text() if Path(filepath).exists() else \
                   "\n\n".join(best_file["chunks"])

    print(f"[rag] Matched: '{best_file['title']}' (score: {best_file['score']:.0%})")

    return {
        "title":           best_file["title"],
        "filename":        best_file["filename"],
        "content":         full_content,
        "relevance_score": best_file["score"],
        "matched_chunks":  best_file["chunks"],
    }


def _fallback_runbook() -> dict:
    """Return a generic runbook when no match is found."""
    return {
        "title":           "General Incident Response",
        "filename":        "fallback",
        "content":         Path(f"{RUNBOOKS_DIR}/high_error_rate.md").read_text()
                           if Path(f"{RUNBOOKS_DIR}/high_error_rate.md").exists()
                           else "No runbook found. Investigate manually.",
        "relevance_score": 0.0,
        "matched_chunks":  [],
    }


# ── CLI: run this file directly to ingest runbooks ─────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--reload", action="store_true", help="Force re-embed all runbooks")
    parser.add_argument("--query",  type=str, help="Test a retrieval query")
    args = parser.parse_args()

    print("=" * 50)
    print("  RAG Runbook Ingestion")
    print("=" * 50)

    count = ingest_runbooks(force_reload=args.reload)
    print(f"\nTotal chunks in ChromaDB: {count}")

    if args.query:
        print(f"\nTest query: '{args.query}'")
        result = retrieve_runbook(args.query)
        print(f"Match: {result['title']}")
        print(f"Score: {result['relevance_score']:.0%}")
        print(f"\nContent preview:\n{result['content'][:300]}...")