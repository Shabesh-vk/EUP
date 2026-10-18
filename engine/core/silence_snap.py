"""Silence snapping algorithm to prevent word clipping.

Adheres to Outstanding Requirement:
"cuts snap to nearby silence so no word is clipped".
Ensures cut boundaries fall into silence gaps between words rather than
slicing through word phonemes.
"""

from typing import Tuple, List, Optional
from engine.core.models import Transcript, Word


def snap_cut_boundaries_to_silence(
    cut_start: float,
    cut_end: float,
    transcript: Transcript,
    padding_s: float = 0.05
) -> Tuple[float, float, List[str]]:
    """Snaps [cut_start, cut_end] to nearby silence gaps so no word is clipped.

    Returns:
        (snapped_start, snapped_end, list_of_snap_notes)
    """
    notes = []
    snapped_start = cut_start
    snapped_end = cut_end

    words = sorted(transcript.words, key=lambda w: w.start)
    if not words:
        return snapped_start, snapped_end, notes

    # Check cut_start
    for i, w in enumerate(words):
        if w.start <= cut_start <= w.end:
            # cut_start lands right in the middle of word w
            mid = (w.start + w.end) / 2.0
            if cut_start <= mid:
                # Snap to silence before word w
                prev_end = words[i - 1].end if i > 0 else 0.0
                snapped_start = max(prev_end, w.start - padding_s)
                notes.append(
                    f"Snapped cut start from {cut_start:.2f}s to {snapped_start:.2f}s to protect word '{w.text}'"
                )
            else:
                # Snap to silence after word w (exclude word from cut)
                next_start = words[i + 1].start if i + 1 < len(words) else w.end + padding_s
                snapped_start = min(next_start, w.end + padding_s)
                notes.append(
                    f"Snapped cut start from {cut_start:.2f}s to {snapped_start:.2f}s after word '{w.text}'"
                )
            break

    # Check cut_end
    for i, w in enumerate(words):
        if w.start <= cut_end <= w.end:
            # cut_end lands inside word w
            mid = (w.start + w.end) / 2.0
            if cut_end >= mid:
                # Include the full word in the cut; snap to silence after w
                next_start = words[i + 1].start if i + 1 < len(words) else w.end + padding_s
                snapped_end = min(next_start, w.end + padding_s)
                notes.append(
                    f"Snapped cut end from {cut_end:.2f}s to {snapped_end:.2f}s to include full word '{w.text}'"
                )
            else:
                # Exclude word from cut; snap to silence before w
                prev_end = words[i - 1].end if i > 0 else 0.0
                snapped_end = max(prev_end, w.start - padding_s)
                notes.append(
                    f"Snapped cut end from {cut_end:.2f}s to {snapped_end:.2f}s before word '{w.text}'"
                )
            break

    return round(snapped_start, 3), round(snapped_end, 3), notes
