"""
rag.py — RAG pipeline for PawPal+.

Public functions:
  - retrieve(query, species, k)              → list of relevant doc chunks
  - generate_schedule_with_llm(tasks, pet, owner) → Schedule with LLM-assigned times + rationale
  - answer_question(question, pet)           → grounded multi-sentence Q&A answer
"""

import os
import re
import json
import datetime
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional; set ANTHROPIC_API_KEY in env directly if not installed
import chromadb
from chromadb.utils import embedding_functions
import anthropic

CHROMA_PATH = os.path.join(os.path.dirname(__file__), ".chroma")
COLLECTION_NAME = "pet_care"
EMBED_MODEL = "all-MiniLM-L6-v2"

_collection = None
_ef = None


def _get_collection():
    """Lazy-load the ChromaDB collection and embedding function."""
    global _collection, _ef
    if _collection is None:
        _ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBED_MODEL
        )
        client = chromadb.PersistentClient(path=os.path.abspath(CHROMA_PATH))
        _collection = client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=_ef,
        )
    return _collection


def retrieve(query: str, species: str | None = None, k: int = 4) -> list[dict]:
    """
    Retrieve the top-k most relevant chunks for a query.

    Args:
        query:   Natural language query string.
        species: "dog", "cat", or None (no species filter).
        k:       Number of chunks to return.

    Returns:
        List of dicts with keys: text, source, species, distance.
    """
    collection = _get_collection()

    where = None
    if species in ("dog", "cat"):
        where = {"$or": [{"species": species}, {"species": "both"}]}

    results = collection.query(
        query_texts=[query],
        n_results=k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({
            "text": doc,
            "source": meta.get("source", ""),
            "species": meta.get("species", ""),
            "distance": dist,
        })
    return chunks


def _build_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a context block for the prompt."""
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[Reference {i} — {c['source']}]\n{c['text']}")
    return "\n\n".join(parts)


def _short_source(s: str) -> str:
    """Reduce a source string to just the org name."""
    if s.startswith("ASPCA"):
        return "ASPCA"
    if s.startswith("Curated"):
        return "ASPCA/AKC/AVMA guidelines"
    if s.startswith("Cornell"):
        return "Cornell Feline Health Center"
    return s.split("(")[0].strip()


def _parse_schedule_json(raw: str, tasks: list) -> list[dict] | None:
    """
    Extract and validate the JSON array from the LLM response.
    Returns a list of validated block dicts, or None if parsing fails.
    """
    # Strip markdown code fences if present
    raw = re.sub(r"```(?:json)?", "", raw).strip()

    # Extract the outermost [...] block
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return None

    try:
        items = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    if not isinstance(items, list) or not items:
        return None

    # Build a lookup from lowercase task title → Task object for fuzzy matching
    task_map = {t.title.lower(): t for t in tasks}

    validated = []
    for item in items:
        if not isinstance(item, dict):
            continue

        # Required: time and task name
        raw_time = item.get("time", "")
        raw_title = item.get("task", "")
        if not raw_time or not raw_title:
            continue

        # Normalise time to HH:MM
        try:
            # Accept "8:00", "08:00", "8:00 AM", etc.
            for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p"):
                try:
                    parsed_time = datetime.datetime.strptime(raw_time.strip(), fmt).time()
                    break
                except ValueError:
                    continue
            else:
                continue  # couldn't parse — skip this block
        except Exception:
            continue

        # Match title back to a Task object (exact first, then lowercase fuzzy)
        task_obj = task_map.get(raw_title.lower())
        if task_obj is None:
            # Try partial match
            for key, t in task_map.items():
                if key in raw_title.lower() or raw_title.lower() in key:
                    task_obj = t
                    break
        if task_obj is None:
            continue  # unrecognisable task — skip

        duration = item.get("duration_minutes", task_obj.duration_minutes)
        reason = str(item.get("reason", f"Scheduled: priority={task_obj.priority}")).strip()

        validated.append({
            "time": parsed_time,
            "task": task_obj,
            "duration_minutes": int(duration),
            "reason": reason,
        })

    return validated if validated else None


def generate_schedule_with_llm(tasks: list, pet, owner) -> "Schedule":
    """
    Use Claude + RAG context to produce a realistic daily schedule with rationale.

    Falls back to the rule-based Scheduler if the LLM call or JSON parse fails.

    Args:
        tasks:  List of Task dataclass instances (already frequency-expanded by caller if needed).
        pet:    Pet dataclass instance.
        owner:  Owner dataclass instance.

    Returns:
        A Schedule with TimeBlock entries and per-task rationale.
    """
    from models import Schedule, TimeBlock, Scheduler

    # Retrieve context covering the full task list in one shot
    query = " ".join(t.title for t in tasks) + f" {pet.species} daily care schedule"
    chunks = retrieve(query, species=pet.species, k=6)
    context = _build_context(chunks)

    # Collect unique sources for citation
    sources = list(dict.fromkeys(_short_source(c["source"]) for c in chunks if c["source"]))
    source_line = f"Source: {', '.join(sources)}" if sources else ""

    # Expand frequency > 1 tasks so the LLM sees the full list
    expanded = []
    for task in tasks:
        for _ in range(task.frequency):
            expanded.append(task)

    task_list = "\n".join(
        f'- "{t.title}": {t.duration_minutes} min, priority={t.priority}'
        for t in expanded
    )

    day_end_hour = 8 + owner.available_hours

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            system=(
                "You are a veterinary care assistant scheduling a pet's daily care tasks. "
                "Assign realistic times of day based on normal pet care routines. "
                "Return ONLY a JSON array — no prose, no markdown fences, no explanation outside the array.\n\n"
                "Rules:\n"
                "- Morning walks go between 07:00–09:00\n"
                "- Evening walks go between 17:00–19:00\n"
                "- For tasks appearing twice (e.g. feeding, water), space them 8–12 hours apart\n"
                "- Do not schedule two tasks at the same start time\n"
                "- Keep all tasks within the owner's available window\n"
                "- Use 24-hour HH:MM format for times\n"
                "- Use the exact task name string from the input list\n\n"
                "Each item must have exactly these fields:\n"
                '{"time": "HH:MM", "task": "<exact name>", "duration_minutes": <int>, "reason": "<one sentence why this time, max 20 words>"}'
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Pet: {pet.name}, a {pet.species}\n"
                    f"Owner available: 08:00–{day_end_hour:02d}:00\n\n"
                    f"Tasks to schedule:\n{task_list}\n\n"
                    f"Veterinary reference material:\n{context}\n\n"
                    "Return the JSON array now:"
                ),
            }],
        )

        raw = response.content[0].text
        validated = _parse_schedule_json(raw, tasks)

        if validated is None:
            raise ValueError("JSON parse returned no valid blocks")

        # Build Schedule from validated blocks, sorted by time
        validated.sort(key=lambda b: b["time"])
        schedule = Schedule()
        for b in validated:
            start_dt = datetime.datetime.combine(datetime.date.today(), b["time"])
            end_dt = start_dt + datetime.timedelta(minutes=b["duration_minutes"])
            reason = b["reason"]
            if source_line:
                reason = f"{reason} ({source_line})"
            schedule.blocks.append(
                TimeBlock(b["task"], b["time"], end_dt.time(), reason)
            )
        return schedule

    except Exception:
        # Fallback: rule-based scheduler, no LLM rationale
        return Scheduler(owner=owner, tasks=tasks).generate_schedule()


def answer_question(question: str, pet) -> str:
    """
    Answer a free-form owner question grounded in the knowledge base.
    Used for the chat widget in the Streamlit sidebar.

    Args:
        question: The owner's question as a string.
        pet:      A Pet dataclass instance (for species context).

    Returns:
        A grounded, conversational answer string.
    """
    query = f"{question} {pet.species}"
    chunks = retrieve(query, species=pet.species, k=4)

    if not chunks:
        return "I don't have enough reference material to answer that confidently. Please consult your veterinarian."

    context = _build_context(chunks)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=(
            "You are a helpful veterinary care assistant for the PawPal+ app. "
            "Answer the owner's question using only the provided reference material. "
            "Be friendly, specific, and practical. If the reference material does not "
            "contain enough information to answer fully, say so and recommend consulting a vet. "
            "Keep responses to 3-5 sentences."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Reference material:\n{context}\n\n"
                f"My pet: {pet.name}, a {pet.species}\n\n"
                f"Question: {question}"
            ),
        }],
    )
    return response.content[0].text.strip()
