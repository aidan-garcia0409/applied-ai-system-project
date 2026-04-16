"""
build_kb.py — One-time script to chunk knowledge base docs and embed them into ChromaDB.

Run from the project root:
    python scripts/build_kb.py

This only needs to be re-run if you add or edit files in knowledge_base/.
"""

import os
import re
import chromadb
from chromadb.utils import embedding_functions

KNOWLEDGE_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "knowledge_base")
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", ".chroma")
COLLECTION_NAME = "pet_care"

CHUNK_SIZE = 400      # target words per chunk
CHUNK_OVERLAP = 50    # words of overlap between consecutive chunks


def parse_species(text: str) -> str:
    """Extract species tag from the document header, defaulting to 'both'."""
    match = re.search(r"^Species:\s*(.+)$", text, re.MULTILINE)
    if not match:
        return "both"
    value = match.group(1).strip().lower()
    if "dog" in value and "cat" in value:
        return "both"
    if "dog" in value:
        return "dog"
    if "cat" in value:
        return "cat"
    return "both"


def parse_source(text: str) -> str:
    """Extract source line from the document header."""
    match = re.search(r"^Source:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else "unknown"


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping word-count chunks."""
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += chunk_size - overlap
    return chunks


def load_documents(kb_dir: str) -> list[dict]:
    """Load all markdown files from the knowledge base directory."""
    docs = []
    for fname in sorted(os.listdir(kb_dir)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(kb_dir, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            text = f.read()
        docs.append({
            "filename": fname,
            "text": text,
            "species": parse_species(text),
            "source": parse_source(text),
        })
    return docs


def build_index():
    kb_dir = os.path.abspath(KNOWLEDGE_BASE_DIR)
    chroma_path = os.path.abspath(CHROMA_PATH)

    print(f"Loading documents from: {kb_dir}")
    docs = load_documents(kb_dir)
    print(f"Found {len(docs)} documents")

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    client = chromadb.PersistentClient(path=chroma_path)

    # Delete and recreate for a clean rebuild
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"Deleted existing collection '{COLLECTION_NAME}'")
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    all_ids, all_docs, all_metas = [], [], []
    chunk_count = 0

    for doc in docs:
        chunks = chunk_text(doc["text"], CHUNK_SIZE, CHUNK_OVERLAP)
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc['filename']}__chunk_{i}"
            all_ids.append(chunk_id)
            all_docs.append(chunk)
            all_metas.append({
                "source": doc["source"],
                "species": doc["species"],
                "filename": doc["filename"],
                "chunk_index": i,
            })
            chunk_count += 1

    # Upsert in batches to avoid memory issues
    batch_size = 100
    for i in range(0, len(all_ids), batch_size):
        collection.upsert(
            ids=all_ids[i:i + batch_size],
            documents=all_docs[i:i + batch_size],
            metadatas=all_metas[i:i + batch_size],
        )

    print(f"Indexed {chunk_count} chunks from {len(docs)} documents into '{COLLECTION_NAME}'")
    print(f"ChromaDB stored at: {chroma_path}")


if __name__ == "__main__":
    build_index()
