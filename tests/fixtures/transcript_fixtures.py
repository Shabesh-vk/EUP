"""
Transcript fixtures for unit, integration, and E2E tests.
Includes a realistic talking head interview video transcript with:
- "welcome to the channel" spoken at 42.0s - 44.0s
- "pricing" mentioned at three distinct timestamps (65.0s, 160.0s, 195.0s)
- filler words ("um", "uh", "like")
- silences
- multi-speaker sections (host and guest)
"""

from typing import List
from core.schema import TranscriptWord, Transcript, SourceMedia, ClipSegment, Timeline, EffectsCollection


def create_sample_transcript_words() -> List[TranscriptWord]:
    words_data = [
        # Intro (0s - 30s)
        (0, "hey", 1000, 1400, "host", False),
        (1, "everyone", 1400, 2000, "host", False),
        (2, "um", 2200, 2600, "host", True),  # filler
        (3, "today", 3000, 3500, "host", False),
        (4, "we", 3500, 3700, "host", False),
        (5, "have", 3700, 4000, "host", False),
        (6, "a", 4000, 4100, "host", False),
        (7, "great", 4100, 4600, "host", False),
        (8, "topic", 4600, 5200, "host", False),
        # Long pause between 5.2s and 8.0s (silence: 2800ms)
        (9, "let", 8000, 8300, "host", False),
        (10, "us", 8300, 8500, "host", False),
        (11, "get", 8500, 8800, "host", False),
        (12, "started", 8800, 9500, "host", False),
        # More intro speech...
        (13, "in", 25000, 25300, "host", False),
        (14, "this", 25300, 25600, "host", False),
        (15, "video", 25600, 26200, "host", False),
        # Section with "welcome to the channel" at 42.0s - 44.0s
        (16, "welcome", 42000, 42500, "host", False),
        (17, "to", 42500, 42700, "host", False),
        (18, "the", 42700, 42900, "host", False),
        (19, "channel", 42900, 44000, "host", False),
        # Pricing mention #1 at 65.0s (65000 - 66500)
        (20, "our", 64500, 64900, "host", False),
        (21, "pricing", 65000, 65800, "host", False),
        (22, "is", 65800, 66000, "host", False),
        (23, "affordable", 66000, 67000, "host", False),
        # Range 60s - 90s has general speech (speed target in step 4: 1:00 to 1:30)
        (24, "we", 70000, 70300, "host", False),
        (25, "have", 70300, 70600, "host", False),
        (26, "plans", 70600, 71200, "host", False),
        (27, "for", 71200, 71400, "host", False),
        (28, "creators", 71400, 72200, "host", False),
        # Filler "uh" at 75.0s
        (29, "uh", 75000, 75500, "host", True),
        # Pricing mention #2 at 160.0s (2:40 = 160s)
        (30, "the", 159500, 159800, "guest", False),
        (31, "pricing", 160000, 160800, "guest", False),
        (32, "tier", 160800, 161400, "guest", False),
        (33, "for", 161400, 161700, "guest", False),
        (34, "teams", 161700, 162400, "guest", False),
        (35, "starts", 162400, 163000, "guest", False),
        (36, "low", 163000, 163600, "guest", False),
        # Pricing mention #3 at 195.0s (3:15 = 195s)
        (37, "regarding", 194000, 194800, "host", False),
        (38, "pricing", 195000, 195700, "host", False),
        (39, "updates", 195700, 196400, "host", False),
        # Multi-speaker section about old job
        (40, "tell", 220000, 220400, "host", False),
        (41, "me", 220400, 220600, "host", False),
        (42, "about", 220600, 221000, "host", False),
        (43, "your", 221000, 221300, "host", False),
        (44, "old", 221300, 221600, "host", False),
        (45, "job", 221600, 222200, "host", False),
        (46, "at", 222500, 222800, "guest", False),
        (47, "my", 222800, 223100, "guest", False),
        (48, "old", 223100, 223500, "guest", False),
        (49, "job", 223500, 224000, "guest", False),
        (50, "i", 224000, 224200, "guest", False),
        (51, "managed", 224200, 224900, "guest", False),
        (52, "video", 224900, 225400, "guest", False),
        (53, "pipelines", 225400, 226200, "guest", False),
        # Outro with "thanks" said multiple times
        (54, "thanks", 250000, 250600, "host", False),
        (55, "for", 250600, 250900, "host", False),
        (56, "joining", 250900, 251600, "host", False),
        (57, "thanks", 252000, 252500, "guest", False),
        (58, "thanks", 253000, 253500, "host", False),
        (59, "again", 253500, 254000, "host", False),
        (60, "thanks", 255000, 255500, "host", False),
    ]

    words = []
    for idx, (w_id, word, s_ms, e_ms, spk, is_f) in enumerate(words_data):
        words.append(
            TranscriptWord(
                id=f"w_{w_id:03d}",
                word=word,
                start_ticks=s_ms,
                end_ticks=e_ms,
                speaker=spk,
                confidence=0.98,
                is_filler=is_f,
            )
        )
    return words


def create_test_timeline(duration_seconds: float = 300.0) -> Timeline:
    """Create a pristine 5-minute (300s) test timeline matching the worked example requirements."""
    dur_ticks = int(duration_seconds * 1000)
    source_media = SourceMedia(
        id="media_test_001",
        filename="interview.mp4",
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        duration_ticks=dur_ticks,
        fps=30.0,
        width=1920,
        height=1080,
        audio_channels=2,
        sample_rate=48000,
    )
    transcript = Transcript(
        words=create_sample_transcript_words(),
        language="en",
        is_mock=True,
    )
    # Initially 1 continuous segment covering the entire source
    initial_segment = ClipSegment(
        segment_id="seg_001",
        source_start_ticks=0,
        source_end_ticks=dur_ticks,
        speed_ratio=1.0,
    )
    tl = Timeline(
        schema_version="1.0.0",
        project_id="proj_test_001",
        timebase=1000,
        source_media=source_media,
        transcript=transcript,
        segments=[initial_segment],
        effects=EffectsCollection(),
        transactions=[],
        timeline_hash="",
    )
    from core.canonicalizer import compute_timeline_hash
    tl.timeline_hash = compute_timeline_hash(tl)
    return tl

