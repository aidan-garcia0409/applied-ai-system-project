# Model Card — PawPal+

## Model Overview

**Project:** PawPal+ AI-Grounded Pet Care Scheduler
**Base project:** PawPal+ rule-based scheduler (Modules 1–3) — a greedy, priority-sorted daily task scheduler for dogs and cats with no AI component.
**Extension:** RAG pipeline grounding schedule recommendations in veterinary guidelines, with LLM-driven scheduling and a conversational Q&A assistant.
**Model used:** Claude claude-haiku-4-5 (Anthropic) via API
**Embedding model:** all-MiniLM-L6-v2 (sentence-transformers, local)
**Vector store:** ChromaDB (local persistent)

---

## Intended Use

PawPal+ is intended to help everyday pet owners plan a realistic daily care schedule for their dog or cat, with explanations grounded in published veterinary guidelines. It is a general-purpose care planning tool for healthy adult pets.

**Not intended for:**
- Pets with active medical conditions, post-surgical recovery needs, or special dietary requirements
- Use as a substitute for professional veterinary advice
- Species other than dogs and cats

---

## Knowledge Base

The system's knowledge base consists of 10 markdown documents sourced from:

| Source | Topics covered |
|---|---|
| ASPCA (scraped) | General dog care, general cat care, dog nutrition, cat nutrition, dog grooming, cat grooming |
| Curated from ASPCA/AKC/AVMA published guidelines | Dog exercise and walks, cat play and enrichment, cat litter box care, pet hydration |

All documents reflect publicly available, non-proprietary veterinary care guidelines. No proprietary clinical data is used. The knowledge base has not been reviewed by a licensed veterinarian.

---

## AI Collaboration

### Helpful AI suggestion

The most valuable contribution came when the LLM took over scheduling entirely. The expectation was that producing realistic times (morning walk at 8 AM, evening walk at 5:30 PM, feedings 8+ hours apart) would require explicit examples, extensive prompt engineering, or hardcoded rules. Instead, Claude inferred the time-of-day intent of every task from the task names alone — on the first attempt, without examples. This revealed that scheduling is a semantic problem that an LLM handles naturally, not a constraint-satisfaction problem that requires explicit rules.

### Flawed AI suggestion

The initial architecture was a hybrid: rule-based scheduler handles *when*, LLM handles *why*. This seemed like a clean separation of concerns. In practice it was architecturally wrong. The rule-based scheduler placed "Evening walk" at 8:40 AM and scheduled two feedings 10 minutes apart — because a greedy priority queue has no model of time-of-day meaning. The flaw wasn't a bug; the design itself was wrong. Timing and rationale can't be cleanly separated: the *time* a task is scheduled is part of the reasoning. The hybrid approach was abandoned in favor of having the LLM own the full schedule, with the rule-based scheduler kept only as a fallback.

---

## Biases and Limitations

**Geographic and cultural bias:** All source documents are from US-based organizations (ASPCA, AKC, AVMA). Feeding frequencies, exercise expectations, and indoor/outdoor assumptions reflect North American pet ownership norms and may not generalize to other cultural or geographic contexts.

**Species coverage:** Only dogs and cats are supported. The system has no knowledge of exotic pets, birds, reptiles, or small animals.

**Age and health blindness:** The `age` field exists in the data model but is not used in scheduling or retrieval. A 14-year-old senior dog and a 2-year-old dog receive identical schedules. Breed, weight, and health conditions are not considered.

**Citation reliability gap:** Source citations are attached at the retrieval level, not the claim level. The system appends citations based on which documents were retrieved, not which specific passage a given sentence was drawn from. Claude may synthesize claims from its training knowledge, and a citation will still appear because those documents were in the retrieved context. The system appears more traceable than it actually is.

**Small knowledge base:** With 10 documents and 11 chunks in the index, different queries often retrieve overlapping content. The knowledge base covers core daily care tasks well but has no depth on health conditions, medications, aging, or seasonal care.

---

## Testing Results

**30 / 30 automated tests passed** (`pytest tests/ -v`)

| Test file | Count | Coverage |
|---|---|---|
| `tests/test_models.py` | 8 | Dataclass fields, default task lists, priority ordering |
| `tests/test_scheduler.py` | 13 | Rule-based fallback: priority sort, frequency expansion, skipped tasks, time block validity |
| `tests/test_rag.py` | 9 | JSON parse pipeline: valid input, markdown fences, leading prose, missing fields, unrecognised task names, time normalisation, fuzzy matching, source citation formatting |

RAG tests require no API calls. The parser and source utilities are tested directly, making the suite fast and fully deterministic.

**Runtime logging:** `rag.py` writes to `rag.log`. Each generation records chunk count, top cosine distance, success/fallback status, and raw output on parse failure. This provides a post-hoc record of reliability across real runs.

**Manual testing observations:**
- LLM scheduling honored time-of-day constraints consistently across all test runs
- Retrieval top cosine distance averaged ~0.50–0.55 for well-matched queries, indicating good but not perfect alignment between task vocabulary and document vocabulary
- The fallback path was never triggered during normal use; it was only verified through direct unit tests

---

## Ethical Considerations

The system should not be used as a substitute for veterinary care. A schedule that looks appropriate for a healthy pet may be harmful for one with medical needs. The current app has no disclaimer to this effect — adding one is the highest-priority responsible-AI improvement identified.

The conversational Q&A function is explicitly instructed to recommend consulting a veterinarian when the knowledge base does not contain sufficient information to answer a question. This is the primary safety guardrail for the chat path. No equivalent guardrail exists for the schedule output.

---

## Reflection

**What this project taught about AI and problem-solving:**

The clearest lesson was about the limits of rule-based thinking when the problem is fundamentally semantic. The original scheduler was logically correct code that produced wrong answers — not because of bugs, but because priority queues don't understand meaning. Recognizing that class of failure, and knowing when to hand a problem to a model that reasons rather than calculates, is a more important engineering judgment than any specific implementation detail.

The second lesson was about what RAG buys you. In a small knowledge base, Claude often already knows the facts in the documents. The value of retrieval is accountability, not novelty. A cited recommendation is not necessarily more accurate than an uncited one — but it is auditable. For systems that affect living things, that traceability matters even when it feels redundant.

**What I would improve with more time:**
- Add age awareness to retrieval queries (senior dog vs. puppy care docs)
- Add a UI disclaimer that PawPal+ provides general guidance, not individualized veterinary advice
- Expand the knowledge base with species-specific condition articles
- Implement claim-level citation tracking rather than retrieval-level attribution
