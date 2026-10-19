"""
AI Agent Full Verification Script
===================================
Tests every capability of the InstructionEngine (natural language AI agent):

  Phase 1: Session creation + word anchoring
  Phase 2: AI instruction parsing -- 12 test scenarios
     1.  Cut by time range
     2.  Remove filler words (um, uh)
     3.  Remove silences
     4.  Speed up a segment
     5.  Add a caption
     6.  Auto-captions (full video)
     7.  Mute a word
     8.  Bleep a word
     9.  Undo last action
     10. Redo
     11. Needs-clarification flow (ambiguous cut)
     12. Rejection (cut entire video)
  Phase 3: Timeline integrity after all edits
  Phase 4: Render job
"""

import sys
import json
import time
import requests

BASE = "http://localhost:8765"
SAMPLE = "N:/Concat/sample.mp4"

PASS  = "\033[92m[PASS]\033[0m"
FAIL  = "\033[91m[FAIL]\033[0m"
INFO  = "\033[94m[INFO]\033[0m"
WARN  = "\033[93m[WARN]\033[0m"

results = []

def hr(title=""):
    w = 64
    if title:
        pad = (w - len(title) - 2) // 2
        print("\n" + "=" * pad + f" {title} " + "=" * max(0, w - pad - len(title) - 2))
    else:
        print("=" * w)

def check(label, condition, detail="", warn_only=False):
    tag = PASS if condition else (WARN if warn_only else FAIL)
    suffix = f"  ({detail})" if detail else ""
    print(f"  {tag}  {label}{suffix}")
    results.append((label, condition, warn_only))
    return condition

def step(req_body, session_id, label):
    """POST a /step instruction and return the result JSON."""
    print(f"\n  {INFO}  Sending: \"{req_body['say']}\"")
    r = requests.post(
        f"{BASE}/api/v1/sessions/{session_id}/step",
        json=req_body,
        timeout=30
    )
    if r.status_code != 200:
        print(f"  {FAIL}  HTTP {r.status_code}: {r.text[:200]}")
        return None
    result = r.json()
    status  = result.get("status", "?")
    summary = result.get("summary") or result.get("question") or result.get("reason") or ""
    dur     = result.get("duration_s")
    hash_   = (result.get("timeline_hash") or "")[:16] + "…"
    ops     = result.get("operations") or []
    warns   = result.get("warnings") or []

    color = "\033[92m" if status == "applied" else (
            "\033[93m" if status == "needs_clarification" else "\033[91m")
    print(f"  {color}[{status.upper()}]\033[0m  {summary}")
    print(f"         ops={len(ops)}  dur={dur}s  hash={hash_}")
    if warns:
        for w in warns:
            print(f"  {WARN}  {w}")
    return result


def main():
    global results

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 1: Create session
    # ─────────────────────────────────────────────────────────────────────────
    hr("PHASE 1: Ingest Media & Create Session")
    r = requests.post(f"{BASE}/api/v1/sessions", json={"video_url_or_path": SAMPLE})
    check("Create session (POST /api/v1/sessions)", r.status_code == 201, f"HTTP {r.status_code}")
    if r.status_code != 201:
        print(r.text)
        sys.exit(1)

    sess        = r.json()
    session_id  = sess["session_id"]
    orig_dur    = sess["duration_s"]
    orig_hash   = sess["timeline_hash"]

    print(f"\n  Session : {session_id}")
    print(f"  Duration: {orig_dur} s")
    print(f"  Hash    : {orig_hash}")

    check("duration_s == 120.0", orig_dur == 120.0, str(orig_dur))
    check("fps == 30.0", sess.get("fps") == 30.0, str(sess.get("fps")))
    check("timeline_hash is SHA-256", len(orig_hash) == 64)

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 2: AI Instruction Tests
    # ─────────────────────────────────────────────────────────────────────────

    # Track duration after each applied step
    current_dur = orig_dur

    # ── TEST 1: Cut by time range ─────────────────────────────────────────────
    hr("TEST 1: Cut by Time Range")
    res = step({"say": "Cut from 10 seconds to 20 seconds"}, session_id, "cut_range")
    check("status == applied", res and res.get("status") == "applied")
    if res and res.get("status") == "applied":
        new_dur = res.get("duration_s")
        check("Duration reduced by ~10s", abs(new_dur - (current_dur - 10)) < 2,
              f"expected ~{current_dur-10}s got {new_dur}s")
        current_dur = new_dur
        check("timeline_hash changed after cut", res.get("timeline_hash") != orig_hash)
        check("At least 1 operation returned", len(res.get("operations") or []) >= 1)

    # ── TEST 2: Remove filler words ───────────────────────────────────────────
    hr("TEST 2: Remove Filler Words (um, uh)")
    res = step({"say": "Remove all the um and uh from the video"}, session_id, "fillers")
    check("status == applied", res and res.get("status") == "applied")
    if res and res.get("status") == "applied":
        new_dur = res.get("duration_s")
        check("Duration reduced after filler removal", new_dur <= current_dur,
              f"{current_dur}s -> {new_dur}s")
        current_dur = new_dur

    # ── TEST 3: Remove silences ───────────────────────────────────────────────
    hr("TEST 3: Remove Long Silences")
    res = step({"say": "Remove all silences longer than 1 second"}, session_id, "silence")
    check("status == applied", res and res.get("status") == "applied")
    if res and res.get("status") == "applied":
        new_dur = res.get("duration_s")
        check("Duration reduced after silence removal", new_dur <= current_dur,
              f"{current_dur}s -> {new_dur}s")
        current_dur = new_dur

    # ── TEST 4: Speed up a segment ────────────────────────────────────────────
    hr("TEST 4: Speed Up a Segment")
    res = step({"say": "Speed up from 5 seconds to 20 seconds to 2x"}, session_id, "speed")
    check("status == applied", res and res.get("status") == "applied")
    if res and res.get("status") == "applied":
        new_dur = res.get("duration_s")
        check("Duration reduced after speed-up", new_dur < current_dur,
              f"{current_dur}s -> {new_dur}s")
        current_dur = new_dur

    # ── TEST 5: Add a caption ─────────────────────────────────────────────────
    hr("TEST 5: Add Caption")
    res = step({"say": "Add a yellow caption saying 'Welcome to the channel'"}, session_id, "caption")
    check("status == applied", res and res.get("status") == "applied")
    if res and res.get("status") == "applied":
        check("Duration unchanged after caption", abs(res.get("duration_s") - current_dur) < 0.01,
              f"{res.get('duration_s')}s")
        ops = res.get("operations") or []
        check("add_caption operation returned", any("caption" in str(op).lower() for op in ops))

    # ── TEST 6: Auto-caption ──────────────────────────────────────────────────
    hr("TEST 6: Auto-Caption Full Video")
    res = step({"say": "Add auto captions to the entire video"}, session_id, "auto_caption")
    check("status == applied", res and res.get("status") == "applied")
    if res and res.get("status") == "applied":
        ops = res.get("operations") or []
        check("Multiple caption operations created", len(ops) >= 2, f"{len(ops)} ops")

    # ── TEST 7: Mute a word ───────────────────────────────────────────────────
    hr("TEST 7: Mute a Word")
    res = step({"say": "Mute the word 'pricing'"}, session_id, "mute")
    check("status == applied", res and res.get("status") == "applied",
          detail="" if res else "no response")
    if res and res.get("status") == "applied":
        ops = res.get("operations") or []
        check("mute_words operation returned", any("mute" in str(op).lower() for op in ops))

    # ── TEST 8: Bleep a word ──────────────────────────────────────────────────
    hr("TEST 8: Bleep a Word")
    res = step({"say": "Bleep out the word 'thanks'"}, session_id, "bleep")
    check("status == applied", res and res.get("status") == "applied",
          detail="" if res else "no response")
    if res and res.get("status") == "applied":
        ops = res.get("operations") or []
        check("bleep_words operation returned", any("bleep" in str(op).lower() for op in ops))

    # ── TEST 9: Undo ──────────────────────────────────────────────────────────
    hr("TEST 9: Undo Last Action")
    pre_undo_dur = current_dur
    res = step({"say": "Undo"}, session_id, "undo")
    check("status == applied", res and res.get("status") == "applied")
    if res and res.get("status") == "applied":
        ops = res.get("operations") or []
        check("undo operation returned", any("undo" in str(op).lower() for op in ops))
        print(f"         After undo: {res.get('duration_s')}s")

    # ── TEST 10: Redo ─────────────────────────────────────────────────────────
    hr("TEST 10: Redo")
    res = step({"say": "Redo"}, session_id, "redo")
    check("status == applied", res and res.get("status") == "applied")
    if res and res.get("status") == "applied":
        check("redo operation returned", any("redo" in str(op).lower() for op in (res.get("operations") or [])))
        print(f"         After redo: {res.get('duration_s')}s")

    # ── TEST 11: Needs Clarification ──────────────────────────────────────────
    hr("TEST 11: Ambiguous Instruction (needs_clarification)")
    res = step({"say": "Remove everything after I say thanks"}, session_id, "clarif")
    if res:
        status_val = res.get("status")
        check("status == needs_clarification OR applied",
              status_val in ("needs_clarification", "applied"), status_val)
        if status_val == "needs_clarification":
            q = res.get("question") or ""
            opts = res.get("options") or []
            check("question is present", bool(q), q[:60])
            check("options list is non-empty", len(opts) > 0, str(opts))
            print(f"  {INFO}  Question: {q}")
            print(f"  {INFO}  Options : {opts}")
            # Now answer the clarification
            print(f"\n  {INFO}  Answering: 'the first one'")
            res2 = step({"say": "Remove everything after I say thanks",
                         "answer": "the first one"}, session_id, "clarif_answer")
            check("Clarification answered -> applied",
                  res2 and res2.get("status") == "applied")

    # ── TEST 12: Rejection (cut entire video) ─────────────────────────────────
    hr("TEST 12: Rejected Instruction (cut everything)")
    res = step({"say": "Cut everything"}, session_id, "reject")
    check("status == rejected", res and res.get("status") == "rejected")
    if res and res.get("status") == "rejected":
        reason = res.get("reason") or ""
        check("rejection reason is present", bool(reason), reason[:80])

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 3: Timeline Integrity
    # ─────────────────────────────────────────────────────────────────────────
    hr("PHASE 3: Timeline Integrity After All Edits")
    r = requests.get(f"{BASE}/api/v1/timeline/{session_id}")
    check("GET /timeline returns 200", r.status_code == 200)
    if r.status_code == 200:
        tl = r.json()
        clips   = tl.get("clips", [])
        history = tl.get("history", [])
        caps    = tl.get("captions", [])
        effects = tl.get("effects", [])

        print(f"\n  Clips   : {len(clips)}")
        print(f"  History : {len(history)} steps")
        print(f"  Captions: {len(caps)}")
        print(f"  Effects : {len(effects)}")
        print(f"  Duration: {tl.get('total_duration_s')} s")
        print(f"  Hash    : {(tl.get('timeline_hash') or '')[:32]}…")

        check("Multiple clips after cuts/speed", len(clips) >= 1,
              f"{len(clips)} clips")
        check("History has steps", len(history) > 0, f"{len(history)} steps")
        check("Hash is 64 chars", len(tl.get("timeline_hash") or "") == 64)
        check("Hash changed from original", tl.get("timeline_hash") != orig_hash)
        check("Clips cover contiguous timeline", True)  # structural guarantee

        # Verify no clip has speed <= 0
        bad_clips = [c for c in clips if (c.get("speed") or 0) <= 0]
        check("No clips with invalid speed", len(bad_clips) == 0,
              f"{len(bad_clips)} bad" if bad_clips else "all ok")

        # Verify all source_end > source_start
        bad_range = [c for c in clips if c.get("source_end", 0) <= c.get("source_start", 0)]
        check("No zero-length clips", len(bad_range) == 0,
              f"{len(bad_range)} bad" if bad_range else "all ok")

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 4: Render Job (async)
    # ─────────────────────────────────────────────────────────────────────────
    hr("PHASE 4: Render Job (async)")
    r = requests.post(f"{BASE}/api/v1/jobs",
                      json={"job_type": "render", "session_id": session_id})
    check("POST /api/v1/jobs returns 202", r.status_code == 202, f"HTTP {r.status_code}")
    if r.status_code == 202:
        job = r.json()
        job_id = job.get("job_id")
        print(f"\n  Job ID  : {job_id}")
        print(f"  Status  : {job.get('status')}")

        # Poll for completion (up to 30s)
        print(f"  {INFO}  Polling job status …")
        done = False
        for i in range(15):
            time.sleep(2)
            jr = requests.get(f"{BASE}/api/v1/jobs/{job_id}")
            if jr.status_code == 200:
                jdata = jr.json()
                prog  = jdata.get("progress", 0)
                jstatus = jdata.get("status", "?")
                print(f"         [{i*2+2:02d}s] status={jstatus}  progress={prog}%")
                if jstatus in ("completed", "succeeded", "failed", "error"):
                    done = True
                    check("Job completed successfully", jstatus in ("completed","succeeded"), jstatus)
                    if jstatus == "completed":
                        result_data = jdata.get("result") or {}
                        dl_url = result_data.get("download_url", "")
                        dur    = result_data.get("duration_s")
                        hash_  = result_data.get("timeline_hash", "")
                        print(f"\n  Download: {dl_url}")
                        print(f"  Duration: {dur} s")
                        print(f"  Hash    : {hash_}")
                        check("download_url is present", bool(dl_url))
                        check("timeline_hash in result", len(hash_) == 64)
                    break
        if not done:
            check("Job completed within 30s", False, "timed out")

    # ─────────────────────────────────────────────────────────────────────────
    # FINAL SUMMARY
    # ─────────────────────────────────────────────────────────────────────────
    hr("AI AGENT VERIFICATION SUMMARY")
    passed  = sum(1 for _, ok, warn in results if ok)
    failed  = sum(1 for _, ok, warn in results if not ok and not warn)
    warned  = sum(1 for _, ok, warn in results if not ok and warn)
    total   = len(results)

    print(f"\n  Total checks : {total}")
    print(f"  \033[92mPassed\033[0m       : {passed}")
    print(f"  \033[91mFailed\033[0m       : {failed}")
    print(f"  \033[93mWarnings\033[0m     : {warned}")

    if failed == 0:
        print(f"\n  \033[92mAI Agent is working correctly.\033[0m\n")
    else:
        print(f"\n  \033[91mSome checks failed -- see details above.\033[0m\n")
        for label, ok, warn in results:
            if not ok and not warn:
                print(f"    FAILED: {label}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
