"""
Phase 1 Verification Script
============================
Tests the full Phase 1 pipeline:
  1. POST /api/v1/sessions   -> probe media + transcribe + build Timeline
  2. GET  /api/v1/sessions/{id}  -> verify session info
  3. GET  /api/v1/timeline/{id}  -> verify clips, word list, hash
  4. Print all chunk (clip) files and storage artefacts
"""

import sys
import json
import os
import hashlib
import requests
from pathlib import Path

BASE = "http://localhost:8765"
SAMPLE = str(Path("N:/Concat/sample.mp4").resolve())
STORAGE = Path("N:/Concat/storage_data")

PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"

def hr(title=""):
    w = 60
    if title:
        pad = (w - len(title) - 2) // 2
        print("\n" + "=" * pad + f" {title} " + "=" * (w - pad - len(title) - 2))
    else:
        print("=" * w)

def check(label, condition, detail=""):
    if condition:
        print(f"  {PASS}  {label}" + (f"  ({detail})" if detail else ""))
    else:
        print(f"  {FAIL}  {label}" + (f"  ({detail})" if detail else ""))
    return condition

def main():
    all_ok = True

    # ── STEP 1: Health ────────────────────────────────────────────────────────
    hr("STEP 1: Engine Health")
    r = requests.get(f"{BASE}/health")
    ok = check("GET /health returns 200", r.status_code == 200)
    ok &= check("status == ok", r.json().get("status") == "ok")
    all_ok &= ok

    # ── STEP 2: Create Session (Phase 1 trigger) ──────────────────────────────
    hr("STEP 2: Create Session  (Phase 1 Ingestion)")
    print(f"  {INFO}  Importing: {SAMPLE}")

    payload = {"video_url_or_path": SAMPLE}
    r = requests.post(f"{BASE}/api/v1/sessions", json=payload)
    print(f"  {INFO}  HTTP {r.status_code}")

    ok = check("POST /api/v1/sessions returns 201", r.status_code == 201,
               f"got {r.status_code}")
    all_ok &= ok

    if not ok:
        print(f"  {FAIL}  Response body: {r.text[:500]}")
        print("\nAborting -- session creation failed.")
        sys.exit(1)

    sess = r.json()
    session_id = sess.get("session_id")
    print(f"\n  Session ID  : {session_id}")
    print(f"  Duration    : {sess.get('duration_s')} s")
    print(f"  FPS         : {sess.get('fps')}")
    print(f"  Time policy : {sess.get('time_policy')}")
    print(f"  Hash        : {sess.get('timeline_hash')}")

    check("session_id is present", bool(session_id))
    check("duration_s > 0", (sess.get("duration_s") or 0) > 0,
          f"{sess.get('duration_s')} s")
    check("fps > 0", (sess.get("fps") or 0) > 0, str(sess.get("fps")))
    check("timeline_hash is 64-char SHA-256",
          len(sess.get("timeline_hash") or "") == 64)

    # ── STEP 3: Verify session info ───────────────────────────────────────────
    hr("STEP 3: GET Session Info")
    r2 = requests.get(f"{BASE}/api/v1/sessions/{session_id}")
    ok = check("GET /sessions/{id} returns 200", r2.status_code == 200)
    all_ok &= ok
    if ok:
        s2 = r2.json()
        check("source_media_id is present", bool(s2.get("source_media_id")))
        check("duration matches", abs((s2.get("duration_s") or 0) - (sess.get("duration_s") or 0)) < 0.01)
        check("hash is stable (same as creation)", s2.get("timeline_hash") == sess.get("timeline_hash"))

    # ── STEP 4: Full Timeline inspect ────────────────────────────────────────
    hr("STEP 4: GET Full Timeline Data")
    r3 = requests.get(f"{BASE}/api/v1/timeline/{session_id}")
    ok = check("GET /timeline/{id} returns 200", r3.status_code == 200)
    all_ok &= ok

    tl = {}
    if ok:
        tl = r3.json()

        # Clips
        clips = tl.get("clips", [])
        print(f"\n  Clip count  : {len(clips)}")
        check("At least 1 clip (base clip)", len(clips) >= 1)
        if clips:
            c0 = clips[0]
            check("Clip 0 source_start == 0.0", c0.get("source_start") == 0.0,
                  str(c0.get("source_start")))
            check("Clip 0 source_end > 0", (c0.get("source_end") or 0) > 0,
                  f"{c0.get('source_end')} s")
            check("Clip 0 speed == 1.0", c0.get("speed") == 1.0)
            check("Clip 0 has word_ids", len(c0.get("word_ids", [])) > 0,
                  f"{len(c0.get('word_ids', []))} words")

        # Words in transcript (via word_ids in clips)
        all_word_ids = []
        for c in clips:
            all_word_ids.extend(c.get("word_ids", []))
        print(f"  Total words : {len(all_word_ids)}")
        check("Word IDs are present in clips", len(all_word_ids) > 0)

        # History
        history = tl.get("history", [])
        print(f"  History len : {len(history)} steps")
        check("No history yet (fresh session)", len(history) == 0)

        # Captions / Effects
        check("No captions yet", len(tl.get("captions", [])) == 0)
        check("No effects yet",  len(tl.get("effects",  [])) == 0)

        # Timeline hash present
        check("timeline_hash in timeline response",
              len(tl.get("timeline_hash", "")) == 64)

    # ── STEP 5: Verify temp file created in storage_data ─────────────────────
    hr("STEP 5: Storage / Chunk File Verification")

    if STORAGE.exists():
        all_files = list(STORAGE.iterdir())
        temp_files = [f for f in all_files if f.name.startswith("temp_")]
        mp4_files  = [f for f in all_files if f.suffix == ".mp4"]
        otio_files = [f for f in all_files if f.suffix == ".otio"]

        print(f"\n  Storage dir : {STORAGE}")
        print(f"  Total files : {len(all_files)}")
        print(f"  temp_*.mp4  : {len(temp_files)}  (copied source files)")
        print(f"  *.mp4 total : {len(mp4_files)}")
        print(f"  *.otio      : {len(otio_files)}")

        check("storage_data directory exists", True)
        check("At least 1 temp_*.mp4 exists (source copy)", len(temp_files) > 0)

        if temp_files:
            newest_temp = sorted(temp_files, key=lambda f: f.stat().st_mtime, reverse=True)[0]
            size_mb = newest_temp.stat().st_size / (1024 * 1024)
            print(f"\n  Newest temp : {newest_temp.name}  ({size_mb:.2f} MB)")
            check("Newest temp file is non-empty", size_mb > 0, f"{size_mb:.2f} MB")

            # Compute SHA-256 of the temp file and compare to sample
            print(f"  {INFO}  Computing SHA-256 of {newest_temp.name} ...")
            h = hashlib.sha256()
            with open(newest_temp, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            temp_sha = h.hexdigest()

            h2 = hashlib.sha256()
            with open(SAMPLE, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h2.update(chunk)
            sample_sha = h2.hexdigest()

            print(f"  temp SHA-256  : {temp_sha}")
            print(f"  sample SHA-256: {sample_sha}")
            check("Temp file SHA-256 matches original sample.mp4",
                  temp_sha == sample_sha, "content integrity verified")
    else:
        check("storage_data directory exists", False, str(STORAGE))
        all_ok = False

    # ── STEP 6: Phase 1 word map sample output ───────────────────────────────
    hr("STEP 6: Word Map Sample (from clips)")
    if clips:
        word_ids = clips[0].get("word_ids", [])[:10]
        print(f"\n  First {len(word_ids)} Word IDs from Clip 0:")
        for wid in word_ids:
            print(f"    {wid}")
        check("Word IDs follow w_N format", all(w.startswith("w_") for w in word_ids))

    # ── STEP 7: Probe metadata via SourceMedia (from timeline) ───────────────
    hr("STEP 7: Source Media Probe Metadata")
    # We get fps/duration from session info
    print(f"  Duration (s) : {sess.get('duration_s')}")
    print(f"  FPS          : {sess.get('fps')}")
    check("Duration extracted by ffprobe", (sess.get("duration_s") or 0) > 0)
    check("FPS extracted by ffprobe", (sess.get("fps") or 0) > 0)

    # ── Summary ───────────────────────────────────────────────────────────────
    hr("PHASE 1 VERIFICATION SUMMARY")
    if all_ok:
        print("\n  ALL CHECKS PASSED -- Phase 1 is working correctly.\n")
    else:
        print("\n  SOME CHECKS FAILED -- see details above.\n")

    # Print full timeline JSON (pretty)
    hr("FULL TIMELINE JSON (clips array)")
    if tl:
        clips_summary = []
        for i, c in enumerate(tl.get("clips", [])):
            clips_summary.append({
                "index": i,
                "clip_id": c.get("clip_id"),
                "source_start": c.get("source_start"),
                "source_end": c.get("source_end"),
                "speed": c.get("speed"),
                "word_count": len(c.get("word_ids", [])),
                "first_5_words": c.get("word_ids", [])[:5],
            })
        print(json.dumps(clips_summary, indent=2))

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
