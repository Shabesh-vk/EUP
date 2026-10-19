"""
Unit tests verifying timeline schema compliance against timeline.schema.json.
"""

import json
from pathlib import Path
import jsonschema
from core.schema import Timeline
from tests.fixtures.transcript_fixtures import create_test_timeline


def test_timeline_schema_validation():
    schema_path = Path(__file__).resolve().parent.parent.parent / "timeline.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_dict = json.load(f)

    # Validate against JSON Schema Draft 2020-12
    jsonschema.Draft202012Validator.check_schema(schema_dict)

    timeline = create_test_timeline(duration_seconds=120.0)
    timeline_dict = timeline.model_dump(mode="json")
    # Must validate successfully without raising jsonschema.ValidationError
    jsonschema.validate(instance=timeline_dict, schema=schema_dict)


def test_pydantic_roundtrip():
    timeline = create_test_timeline(duration_seconds=60.0)
    dumped = timeline.model_dump(mode="json")
    reloaded = Timeline.model_validate(dumped)
    assert reloaded.project_id == timeline.project_id
    assert len(reloaded.transcript.words) == len(timeline.transcript.words)
    assert reloaded.total_duration_seconds == 60.0
