# tests/test_rag.py — tests for the RAG pipeline that do not require API calls
import datetime
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Pet, Task
from rag import _parse_schedule_json, _short_source


# -- Fixtures --

def make_tasks():
    pet = Pet("Mochi", "dog", 3)
    return [
        Task("Morning walk", 30, "high",   1, pet),
        Task("Feeding",       10, "high",   2, pet),
        Task("Evening walk",  30, "high",   1, pet),
        Task("Playtime",      20, "medium", 1, pet),
    ]


VALID_JSON = """
[
  {"time": "08:00", "task": "Morning walk",  "duration_minutes": 30, "reason": "Dogs need morning exercise."},
  {"time": "08:35", "task": "Feeding",       "duration_minutes": 10, "reason": "First meal after walk."},
  {"time": "17:30", "task": "Evening walk",  "duration_minutes": 30, "reason": "Evening wind-down."},
  {"time": "18:10", "task": "Playtime",      "duration_minutes": 20, "reason": "Mental stimulation."}
]
"""


# -- PARSE-01: Valid JSON parses to correct number of blocks --

def test_valid_json_returns_all_blocks():
    result = _parse_schedule_json(VALID_JSON, make_tasks())
    assert result is not None
    assert len(result) == 4


# -- PARSE-02: Fields are correctly extracted --

def test_block_fields_extracted():
    result = _parse_schedule_json(VALID_JSON, make_tasks())
    first = result[0]
    assert first["time"] == datetime.time(8, 0)
    assert first["task"].title == "Morning walk"
    assert first["duration_minutes"] == 30
    assert "morning exercise" in first["reason"].lower()


# -- PARSE-03: Markdown code fences are stripped --

def test_strips_markdown_fences():
    fenced = "```json\n" + VALID_JSON.strip() + "\n```"
    result = _parse_schedule_json(fenced, make_tasks())
    assert result is not None
    assert len(result) == 4


# -- PARSE-04: Leading prose before the array is ignored --

def test_strips_leading_prose():
    with_prose = "Here is the schedule you requested:\n" + VALID_JSON
    result = _parse_schedule_json(with_prose, make_tasks())
    assert result is not None
    assert len(result) == 4


# -- PARSE-05: Completely invalid input returns None --

def test_returns_none_on_invalid_json():
    result = _parse_schedule_json("This is not JSON at all.", make_tasks())
    assert result is None


# -- PARSE-06: Empty array returns None --

def test_returns_none_on_empty_array():
    result = _parse_schedule_json("[]", make_tasks())
    assert result is None


# -- PARSE-07: Blocks with missing required fields are skipped, rest parse fine --

def test_skips_blocks_missing_required_fields():
    partial = """
    [
      {"time": "08:00", "task": "Morning walk", "duration_minutes": 30, "reason": "Good."},
      {"task": "Feeding", "duration_minutes": 10, "reason": "Missing time field."},
      {"time": "17:30", "duration_minutes": 30, "reason": "Missing task field."}
    ]
    """
    result = _parse_schedule_json(partial, make_tasks())
    assert result is not None
    assert len(result) == 1
    assert result[0]["task"].title == "Morning walk"


# -- PARSE-08: Unrecognised task names are skipped --

def test_skips_unrecognised_task_names():
    unknown = """
    [
      {"time": "08:00", "task": "Morning walk",  "duration_minutes": 30, "reason": "Good."},
      {"time": "09:00", "task": "Completely unknown task", "duration_minutes": 15, "reason": "?"}
    ]
    """
    result = _parse_schedule_json(unknown, make_tasks())
    assert result is not None
    assert len(result) == 1


# -- PARSE-09: Time formats normalise correctly --

def test_normalises_short_time_format():
    short_time = """[{"time": "8:00", "task": "Morning walk", "duration_minutes": 30, "reason": "Good."}]"""
    result = _parse_schedule_json(short_time, make_tasks())
    assert result is not None
    assert result[0]["time"] == datetime.time(8, 0)


# -- PARSE-10: Fuzzy task name matching --

def test_fuzzy_task_name_match():
    fuzzy = """[{"time": "08:00", "task": "Morning Walk", "duration_minutes": 30, "reason": "Good."}]"""
    result = _parse_schedule_json(fuzzy, make_tasks())
    assert result is not None
    assert result[0]["task"].title == "Morning walk"


# -- SOURCE-01: _short_source reduces ASPCA URLs to "ASPCA" --

def test_short_source_aspca():
    assert _short_source("ASPCA (aspca.org/pet-care/dog-care/general-dog-care)") == "ASPCA"


# -- SOURCE-02: _short_source reduces curated docs to readable label --

def test_short_source_curated():
    assert _short_source("Curated from ASPCA, AKC, and AVMA published guidelines") == "ASPCA/AKC/AVMA guidelines"


# -- SOURCE-03: _short_source handles unknown source gracefully --

def test_short_source_unknown():
    result = _short_source("Some other source")
    assert isinstance(result, str)
    assert len(result) > 0
