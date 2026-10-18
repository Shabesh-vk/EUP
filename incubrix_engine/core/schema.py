"""
Exports Timeline JSON Schema and Markdown documentation.
Requirement: The JSON Schema of your timeline format, with a one-page explanation of how edits stay attached to content.
"""

import json
from pathlib import Path
from .models import Timeline

EXPLANATION_MD = """# Content-Anchored Timeline Schema Specification

## Executive Summary
In video editing, anchoring effects (captions, mutes, cuts, overlays) to absolute timeline clock positions (e.g., `01:42.500`) fails when preceding content is trimmed, sped up, or rearranged. 

The IncuBrix Editing Engine implements **Content-Based Anchoring**:
1. **Immutable Source Anchors**: All dialogue elements are mapped to unique, immutable word IDs (`Word.id`) from the original transcript, with fixed source timestamps (`start`, `end`).
2. **Derived Playhead Timings**: Timeline clock times are never hardcoded on content elements. Instead, the current playhead interval `[timeline_start, timeline_end]` for any caption or effect is calculated dynamically on-the-fly by projecting the anchor word's source coordinates through active media segments.
3. **Non-Destructive Segment Transformations**: Trimming, cutting, and speed variations only alter the list of active media `Segment`s. 

---

## Architecture of Content Anchoring

```
Source Video (Untouched Original)
[0.0s ----------------- Word 42: "welcome" (42.0s - 44.0s) ----------------- 120.0s]
      ▲                                ▲
      │ (Cut first 30s)                │ Pinned Anchor: start_word_id = 42
      ▼                                ▼
Edited Timeline (Derived)
[0.0s ----------------- Caption "Welcome!" (12.0s - 14.0s) ----------------- 90.0s]
```

### 1. The Pinned Word Anchor (`start_word_id`, `end_word_id`)
A caption created via:
> *"Add a caption 'Welcome!' when I say welcome to the channel"*

is stored as:
```json
{
  "id": "cap_1",
  "text": "Welcome!",
  "start_word_id": 42,
  "end_word_id": 45,
  "style": { "color": "white", "font_size": 24 }
}
```
Notice that no clock positions (`0:42` or `0:12`) are stored in the persistent schema! 

### 2. Time Projection Function
When the timeline renders or serializes its state, the engine evaluates each word:
$$\\text{timeline\\_time}(t_{\\text{source}}) = \\sum_{s < s_{\\text{target}}} \\frac{\\text{duration}(s)}{\\text{speed}(s)} + \\frac{t_{\\text{source}} - \\text{start}(s_{\\text{target}})}{\\text{speed}(s_{\\text{target}})}$$

- **When the first 30 seconds are cut**: Segments prior to 30.0s are dropped. Word 42 now falls at offset $42.0 - 30.0 = 12.0\\text{s}$.
- **When the section is sped up 2x**: The duration automatically scales to $(44.0 - 42.0) / 2 = 1.0\\text{s}$.
- **When the intro is restored**: Segments prior to 30.0s are restored, and Word 42 automatically lands back at $42.0\\text{s}$ without altering the caption record.
- **When words under a caption are deleted**: The projection returns `None`. The caption becomes inactive (`is_active = false`), rather than corrupting random downstream video. If that cut is later restored, the caption reappears instantly.

---

## Deterministic Hashing (`timeline_hash`)
Every valid edit produces a canonical JSON representation containing sorted segment slices, active anchors, and effect states. A SHA-256 digest is calculated over this canonical string, ensuring that identical session workflows always produce identical timeline hashes across multiple runs.
"""


def export_schema_and_docs(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    schema_path = output_dir / "timeline.schema.json"
    docs_path = output_dir / "TIMELINE_SCHEMA_EXPLANATION.md"

    schema = Timeline.model_json_schema()
    schema["title"] = "IncuBrixContentAnchoredTimeline"
    schema["description"] = "JSON Schema for the IncuBrix Content-Anchored Video Editing Timeline"

    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)

    with open(docs_path, "w", encoding="utf-8") as f:
        f.write(EXPLANATION_MD)

    return schema_path


if __name__ == "__main__":
    out = Path("n:/Concat/schema")
    export_schema_and_docs(out)
    print(f"Exported schema and docs to {out}")
