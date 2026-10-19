"""
Concat Editor -- Editing Internals Deep Dive PDF Generator
Covers: Timeline data model, cut/skip mechanics, silence snapping,
filler word detection, speed changes, word anchoring, SHA-256 hashing,
undo/redo, and OTIO export.
"""

import os
import sys
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.pdfgen import canvas as pdfcanvas

# ─── Color palette ───────────────────────────────────────────────────────────
NAVY       = colors.HexColor("#0f172a")
BLUE       = colors.HexColor("#1e3a8a")
ACCENT     = colors.HexColor("#3b82f6")
LIGHT_BLUE = colors.HexColor("#dbeafe")
GREEN_BG   = colors.HexColor("#d1fae5")
AMBER_BG   = colors.HexColor("#fef3c7")
RED_BG     = colors.HexColor("#fee2e2")
GRAY_BG    = colors.HexColor("#f1f5f9")
WHITE      = colors.white
BLACK      = colors.HexColor("#0f172a")
SUBTLE     = colors.HexColor("#64748b")
CODE_BG    = colors.HexColor("#1e293b")
CODE_FG    = colors.HexColor("#e2e8f0")

PAGE_W, PAGE_H = A4
MARGIN = 2.2 * cm


# ─── Numbered Canvas (header + footer on every page) ─────────────────────────
class NumberedCanvas(pdfcanvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_header_footer(total)
            super().showPage()
        super().save()

    def _draw_header_footer(self, total_pages):
        self.saveState()
        w = PAGE_W

        # Header bar
        self.setFillColor(NAVY)
        self.rect(0, PAGE_H - 18 * mm, w, 18 * mm, fill=1, stroke=0)
        self.setFillColor(WHITE)
        self.setFont("Helvetica-Bold", 9)
        self.drawString(MARGIN, PAGE_H - 11 * mm, "CONCAT EDITOR")
        self.setFont("Helvetica", 9)
        self.drawRightString(w - MARGIN, PAGE_H - 11 * mm,
                             "Editing Internals: Cut, Skip, Timeline & Anchoring")

        # Footer
        self.setFillColor(NAVY)
        self.rect(0, 0, w, 13 * mm, fill=1, stroke=0)
        self.setFillColor(WHITE)
        self.setFont("Helvetica", 8)
        self.drawString(MARGIN, 4.5 * mm, "IncuBrix AI Engine  --  Concat Desktop Editor")
        self.drawRightString(w - MARGIN, 4.5 * mm,
                             f"Page {self._pageNumber} of {total_pages}")

        self.restoreState()


# ─── Style factory ────────────────────────────────────────────────────────────
def make_styles():
    base = getSampleStyleSheet()

    def ps(name, **kw):
        return ParagraphStyle(name, parent=base["Normal"], **kw)

    styles = {
        "title": ps("title",
            fontSize=28, textColor=WHITE, fontName="Helvetica-Bold",
            alignment=TA_CENTER, leading=34, spaceAfter=4),
        "subtitle": ps("subtitle",
            fontSize=13, textColor=LIGHT_BLUE, fontName="Helvetica",
            alignment=TA_CENTER, leading=18, spaceAfter=2),
        "h1": ps("h1",
            fontSize=17, textColor=WHITE, fontName="Helvetica-Bold",
            alignment=TA_LEFT, leading=22, spaceAfter=4, spaceBefore=6),
        "h2": ps("h2",
            fontSize=13, textColor=NAVY, fontName="Helvetica-Bold",
            alignment=TA_LEFT, leading=17, spaceAfter=3, spaceBefore=10),
        "h3": ps("h3",
            fontSize=11, textColor=BLUE, fontName="Helvetica-Bold",
            alignment=TA_LEFT, leading=15, spaceAfter=2, spaceBefore=6),
        "body": ps("body",
            fontSize=9.5, textColor=BLACK, fontName="Helvetica",
            alignment=TA_JUSTIFY, leading=14, spaceAfter=5),
        "bullet": ps("bullet",
            fontSize=9.5, textColor=BLACK, fontName="Helvetica",
            leftIndent=14, bulletIndent=4, leading=13, spaceAfter=3),
        "code": ps("code",
            fontSize=8.2, textColor=CODE_FG, fontName="Courier",
            backColor=CODE_BG, leading=12.5, leftIndent=10, rightIndent=10,
            spaceBefore=3, spaceAfter=3),
        "note": ps("note",
            fontSize=9, textColor=colors.HexColor("#1e40af"),
            fontName="Helvetica-Oblique", leading=13, leftIndent=12,
            spaceAfter=4),
        "caption": ps("caption",
            fontSize=8, textColor=SUBTLE, fontName="Helvetica-Oblique",
            alignment=TA_CENTER, leading=11),
        "rule_text": ps("rule_text",
            fontSize=9.5, textColor=colors.HexColor("#78350f"),
            fontName="Helvetica-Bold", leading=14, leftIndent=12),
    }
    return styles


# ─── Reusable builders ────────────────────────────────────────────────────────
def section_header(title, styles):
    return Table(
        [[Paragraph(title, styles["h1"])]],
        colWidths=[PAGE_W - 2 * MARGIN],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), NAVY),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
            ("ROUNDEDCORNERS", [4]),
        ])
    )


def callout(text, styles, bg=AMBER_BG, label="NOTE"):
    label_p = Paragraph(f"<b>{label}</b>", ParagraphStyle(
        "cl", parent=styles["body"],
        textColor=colors.HexColor("#92400e"), fontName="Helvetica-Bold",
        fontSize=9))
    body_p = Paragraph(text, ParagraphStyle(
        "clb", parent=styles["body"],
        textColor=colors.HexColor("#78350f"), fontSize=9, leading=13))
    t = Table(
        [[label_p], [body_p]],
        colWidths=[PAGE_W - 2 * MARGIN - 24],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 12),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ])
    )
    return t


def header_table(headers, rows, col_widths, styles, hdr_bg=NAVY):
    data = [[Paragraph(h, ParagraphStyle(
        "th", parent=styles["body"], textColor=WHITE,
        fontName="Helvetica-Bold", fontSize=9)) for h in headers]]
    for row in rows:
        data.append([Paragraph(str(c), ParagraphStyle(
            "td", parent=styles["body"], fontSize=9, leading=12)) for c in row])
    ts = TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  hdr_bg),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, GRAY_BG]),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 7),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 7),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ])
    return Table(data, colWidths=col_widths, style=ts, repeatRows=1)


def ascii_box(lines, styles):
    text = "\n".join(lines)
    return Paragraph(text.replace("\n", "<br/>"), styles["code"])


def sp(n=1):
    return Spacer(1, n * 4 * mm)


def hr():
    return HRFlowable(width="100%", thickness=0.5,
                      color=colors.HexColor("#cbd5e1"), spaceAfter=4)


# ─── Cover page ───────────────────────────────────────────────────────────────
def cover_page(styles):
    elems = []
    # Big navy cover block
    cover = Table(
        [
            [Paragraph("CONCAT EDITOR", styles["title"])],
            [Paragraph("Editing Internals Deep Dive", styles["title"])],
            [Spacer(1, 6 * mm)],
            [Paragraph("How Cut, Skip, Timeline, Speed, Silence Snap,<br/>"
                       "Word Anchoring &amp; SHA-256 Hashing Actually Work",
                       styles["subtitle"])],
            [Spacer(1, 4 * mm)],
            [Paragraph("IncuBrix AI Engine  |  v1.0  |  2026", ParagraphStyle(
                "cv", parent=styles["subtitle"],
                fontSize=10, textColor=colors.HexColor("#93c5fd")))],
        ],
        colWidths=[PAGE_W - 2 * MARGIN],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), NAVY),
            ("TOPPADDING",    (0, 0), (-1, -1), 22),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 22),
            ("LEFTPADDING",   (0, 0), (-1, -1), 20),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 20),
        ])
    )
    elems.append(Spacer(1, 30 * mm))
    elems.append(cover)
    elems.append(Spacer(1, 12 * mm))
    elems.append(Paragraph(
        "This document is a source-code-accurate technical reference for engineers, "
        "contributors, and learners who want to understand how the Concat Desktop Video Editor "
        "performs its core editing operations under the hood. All algorithms described here are "
        "extracted directly from the Python engine source in <b>engine/core/</b>.",
        ParagraphStyle("cover_body", parent=styles["body"],
                       alignment=TA_CENTER, textColor=SUBTLE, fontSize=10)))
    elems.append(PageBreak())
    return elems


# ─── Table of Contents ────────────────────────────────────────────────────────
def table_of_contents(styles):
    elems = []
    elems.append(section_header("TABLE OF CONTENTS", styles))
    elems.append(sp(2))
    toc = [
        ("1", "The Golden Timeline Rule", "The core invariant governing every edit"),
        ("2", "Data Models", "Word, Transcript, TimelineClip, AnchoredCaption, EditStep"),
        ("3", "The Timeline Object", "Clips array, apply_cut(), apply_speed(), history"),
        ("4", "How a CUT Works", "Step-by-step algorithm with before/after diagrams"),
        ("5", "Silence Snapping", "snap_cut_boundaries_to_silence() algorithm"),
        ("6", "How SKIP Works (Silence Removal)", "execute_remove_silences() deep dive"),
        ("7", "Filler Word Detection", "execute_remove_filler_words() and contextual 'like'"),
        ("8", "Speed Changes", "apply_speed(), source_relative flag, clip splitting"),
        ("9", "Word ID Anchoring", "The anchor engine: map_source_time_to_playback()"),
        ("10", "Captions: Add, Resolve, Style", "execute_add_caption(), resolve_captions()"),
        ("11", "Mute / Bleep Audio Effects", "execute_bleep_or_mute_words(), resolve_audio_effects()"),
        ("12", "Auto-Captions", "execute_auto_caption() chunking algorithm"),
        ("13", "Undo / Redo / Restore", "replay_history(), undo(), redo(), restore_step()"),
        ("14", "SHA-256 Timeline Hashing", "compute_timeline_hash() determinism guarantee"),
        ("15", "Background Music & Ducking", "apply_background_music(), ducking model"),
        ("16", "End-to-End Edit Lifecycle", "From user instruction to rendered output"),
    ]
    rows = [[f"  {n}.", title, desc] for n, title, desc in toc]
    t = header_table(
        ["#", "Section", "Description"],
        rows,
        [1.2 * cm, 5.5 * cm, 9.5 * cm],
        styles,
        hdr_bg=BLUE
    )
    elems.append(t)
    elems.append(PageBreak())
    return elems


# ─── Section 1: The Golden Timeline Rule ─────────────────────────────────────
def section_golden_rule(styles):
    elems = []
    elems.append(section_header("1. THE GOLDEN TIMELINE RULE", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "Every edit in Concat is governed by one core invariant called <b>The Golden Timeline Rule</b>. "
        "Understanding this single principle makes all other behaviour predictable:",
        styles["body"]))
    elems.append(sp())

    rule_box = Table(
        [[Paragraph(
            "The original media file is <b>never modified</b>.<br/>"
            "All edits are recorded as an <b>append-only event history</b>.<br/>"
            "Captions, mutes, and bleeps are <b>anchored to Word IDs</b> -- not to timestamps -- "
            "so they automatically follow content through cuts, speed changes, and reordering.",
            styles["rule_text"])]],
        colWidths=[PAGE_W - 2 * MARGIN],
        style=TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), AMBER_BG),
            ("TOPPADDING",    (0, 0), (-1, -1), 14),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
            ("LEFTPADDING",   (0, 0), (-1, -1), 16),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 16),
            ("BOX", (0, 0), (-1, -1), 1.5, colors.HexColor("#d97706")),
        ])
    )
    elems.append(rule_box)
    elems.append(sp())
    elems.append(Paragraph("Why this matters:", styles["h3"]))
    consequences = [
        ("Non-destructive", "You can undo any operation at any time -- the source media never changes."),
        ("Word-anchored overlays", "A caption added to the word 'hello' will still appear on that word "
         "even if you cut earlier content, speed up that segment, or reorder clips."),
        ("Deterministic replay", "Replaying the full history on the same source file always produces "
         "an identical output, guaranteed by SHA-256 hashing."),
        ("Immutable transcript", "The Transcript (all Word objects with original timestamps) "
         "is never mutated -- only the clips array changes."),
    ]
    rows = [[b, d] for b, d in consequences]
    elems.append(header_table(
        ["Benefit", "Explanation"],
        rows,
        [4 * cm, 12.6 * cm],
        styles, hdr_bg=BLUE))
    elems.append(PageBreak())
    return elems


# ─── Section 2: Data Models ───────────────────────────────────────────────────
def section_data_models(styles):
    elems = []
    elems.append(section_header("2. DATA MODELS  (engine/core/models.py)", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "The engine is built on Pydantic models. Every piece of state is typed and validated. "
        "Here are the seven core models you need to understand:",
        styles["body"]))
    elems.append(sp())

    models = [
        ("Word",
         "id, text, start, end, confidence, speaker",
         "One transcribed word with original source timestamps. The atom of all editing."),
        ("Transcript",
         "language, words: List[Word]",
         "Immutable list of all words in the source media. Never modified after creation."),
        ("SourceMedia",
         "media_id, file_path, sha256, duration_s, fps, sample_rate",
         "Metadata for the original file. sha256 seeds the timeline hash chain."),
        ("TimelineClip",
         "clip_id, source_start, source_end, speed, word_ids",
         "A contiguous slice of source media playing at a given speed. The timeline is a list of these."),
        ("AnchoredCaption",
         "caption_id, text, word_ids, style, created_step, active",
         "A caption pinned to specific Word IDs. Resolves to playback timestamps dynamically."),
        ("AnchoredAudioEffect",
         "effect_id, effect_type (mute/bleep), word_ids, active",
         "A mute or bleep effect also pinned to Word IDs. Same resolution mechanic as captions."),
        ("EditStep",
         "step_index, instruction, operations: List[EditOperation], undone",
         "One user instruction recorded in the append-only history log."),
    ]
    elems.append(header_table(
        ["Model", "Key Fields", "Purpose"],
        models,
        [3.5 * cm, 5.5 * cm, 7.6 * cm],
        styles))
    elems.append(sp())

    elems.append(Paragraph("TimelineClip computed properties:", styles["h3"]))
    elems.append(ascii_box([
        "class TimelineClip(BaseModel):",
        "    source_start: float   # offset in original media (seconds)",
        "    source_end:   float   # end offset in original media (seconds)",
        "    speed:        float   # playback speed (1.0 = normal, 2.0 = double speed)",
        "",
        "    @property",
        "    def source_duration(self) -> float:",
        "        return max(0.0, self.source_end - self.source_start)",
        "",
        "    @property",
        "    def playback_duration(self) -> float:",
        "        # How long this clip takes in actual playback",
        "        return self.source_duration / self.speed   # e.g. 10s at 2x = 5s playback",
    ], styles))
    elems.append(sp())
    elems.append(callout(
        "playback_duration is what the viewer experiences. source_duration is how much "
        "of the original media is used. At 2x speed, source_duration is twice the playback_duration.",
        styles, bg=LIGHT_BLUE, label="KEY CONCEPT"))
    elems.append(PageBreak())
    return elems


# ─── Section 3: The Timeline Object ──────────────────────────────────────────
def section_timeline_object(styles):
    elems = []
    elems.append(section_header("3. THE TIMELINE OBJECT  (engine/core/timeline.py)", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "The <b>Timeline</b> class is the central mutable object in the engine. It owns the "
        "clips array, the immutable transcript, the edit history, and all overlays. "
        "Here is what it holds:",
        styles["body"]))
    elems.append(sp())

    fields = [
        ("source", "SourceMedia", "The original media file metadata (immutable reference)"),
        ("transcript", "Transcript", "All words from the original recording (never mutated)"),
        ("clips", "List[TimelineClip]", "Ordered list of clip segments making up the current edit"),
        ("captions", "List[AnchoredCaption]", "Caption overlays anchored to Word IDs"),
        ("effects", "List[AnchoredAudioEffect]", "Mute/bleep effects anchored to Word IDs"),
        ("music", "List[BackgroundMusicTrack]", "Background music overlays with auto-ducking"),
        ("history", "List[EditStep]", "Append-only log of every instruction applied"),
        ("redo_stack", "List[EditStep]", "Temporarily undone steps available for redo"),
        ("total_duration", "float (property)", "Sum of playback_duration of all clips"),
    ]
    elems.append(header_table(
        ["Attribute", "Type", "Description"],
        fields,
        [4 * cm, 4.5 * cm, 8.1 * cm],
        styles))
    elems.append(sp())

    elems.append(Paragraph("How total_duration is computed:", styles["h3"]))
    elems.append(ascii_box([
        "@property",
        "def total_duration(self) -> float:",
        "    return sum(c.playback_duration for c in self.clips)",
        "",
        "# Example with 3 clips:",
        "# Clip A: source 0.0-30.0s  speed 1.0  -> playback 30.0s",
        "# Clip B: source 35.0-50.0s speed 2.0  -> playback  7.5s  (sped up)",
        "# Clip C: source 55.0-90.0s speed 1.0  -> playback 35.0s",
        "# total_duration = 30.0 + 7.5 + 35.0 = 72.5s",
    ], styles))
    elems.append(PageBreak())
    return elems


# ─── Section 4: How a CUT Works ──────────────────────────────────────────────
def section_cut(styles):
    elems = []
    elems.append(section_header("4. HOW A CUT WORKS", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "A cut removes a time range from the playback timeline. The source media is untouched. "
        "Instead, the clips array is surgically split. Here is the full step-by-step algorithm:",
        styles["body"]))
    elems.append(sp())

    steps = [
        ("1", "User calls execute_cut_range(start_s, end_s)",
         "High-level entry point in operations.py"),
        ("2", "Silence snap (optional)",
         "snap_cut_boundaries_to_silence() adjusts start/end to fall in silence gaps between words"),
        ("3", "timeline.apply_cut(snapped_start, snapped_end)",
         "Core mutation inside the Timeline class"),
        ("4", "Iterate clips",
         "Walk each TimelineClip; skip clips entirely outside the cut range"),
        ("5", "Split overlapping clips",
         "Any clip that partially overlaps [cut_start, cut_end] is split into two smaller clips"),
        ("6", "Remove fully covered clips",
         "Any clip fully inside [cut_start, cut_end] is deleted from the clips list"),
        ("7", "Re-assign word_ids",
         "Each surviving clip recomputes which Word IDs fall within its new source range"),
        ("8", "Record EditStep",
         "Op is saved to history as op_type='cut_range' with source_start and source_end"),
    ]
    elems.append(header_table(
        ["Step", "Action", "Notes"],
        steps,
        [1.2 * cm, 5 * cm, 10.4 * cm],
        styles))
    elems.append(sp())

    elems.append(Paragraph("Visual diagram -- before and after a cut:", styles["h3"]))
    elems.append(ascii_box([
        "BEFORE CUT (clips array):",
        "  |------- Clip A (0.0 -> 60.0s, speed 1x) ------|",
        "",
        "  User says: cut from 20.0s to 35.0s",
        "",
        "AFTER CUT (clips array):",
        "  |-- Clip A1 (0.0 -> 20.0s) --| |-- Clip A2 (35.0 -> 60.0s) --|",
        "                                 ^",
        "                            15 seconds removed",
        "",
        "  Original 60s video is now 45s in playback.",
        "  Source media file: UNCHANGED.",
    ], styles))
    elems.append(sp())

    elems.append(Paragraph("What happens with word_ids during a cut:", styles["h3"]))
    elems.append(ascii_box([
        "# Words in transcript (immutable, never changes):",
        "# w_0='Hello' start=0.0  end=0.5",
        "# w_1='I'     start=1.0  end=1.2",
        "# w_2='think' start=22.0 end=22.4   <-- falls inside the cut [20-35]",
        "# w_3='great' start=40.0 end=40.6",
        "",
        "# After cut [20.0, 35.0]:",
        "# Clip A1 (0.0-20.0):  word_ids = ['w_0', 'w_1']   (w_2 excluded)",
        "# Clip A2 (35.0-60.0): word_ids = ['w_3']           (w_2 excluded)",
        "",
        "# w_2 is still in transcript.words -- just not in any clip's word_ids.",
        "# Any caption anchored to w_2 will be hidden (not deleted).",
    ], styles))
    elems.append(sp())
    elems.append(callout(
        "Multiple cuts (e.g., removing 10 filler words) are always applied in reverse "
        "chronological order -- from end to start. This keeps earlier timestamps valid "
        "while later ones are being cut.",
        styles, bg=AMBER_BG, label="IMPORTANT"))
    elems.append(PageBreak())
    return elems


# ─── Section 5: Silence Snapping ─────────────────────────────────────────────
def section_silence_snap(styles):
    elems = []
    elems.append(section_header("5. SILENCE SNAPPING  (engine/core/silence_snap.py)", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "When a cut boundary lands inside a spoken word, it would produce an audible click "
        "or word clipping artefact. The silence snapper automatically moves both cut "
        "boundaries into the nearest silence gap between words.",
        styles["body"]))
    elems.append(sp())

    elems.append(Paragraph("Algorithm for cut_start snapping:", styles["h3"]))
    elems.append(ascii_box([
        "def snap_cut_boundaries_to_silence(cut_start, cut_end, transcript, padding_s=0.05):",
        "",
        "  FOR each word w in transcript (sorted by start time):",
        "    IF cut_start falls INSIDE word w (w.start <= cut_start <= w.end):",
        "",
        "      mid = (w.start + w.end) / 2.0",
        "",
        "      IF cut_start is in the FIRST HALF of w:",
        "        # Protect the word -- snap start to silence BEFORE w",
        "        snapped_start = max(prev_word.end, w.start - padding_s)",
        "        # Shifts the cut to begin just before word w starts",
        "",
        "      ELSE (cut_start is in the SECOND HALF of w):",
        "        # Exclude word from cut -- snap start to silence AFTER w",
        "        snapped_start = min(next_word.start, w.end + padding_s)",
        "        # Shifts the cut to begin just after word w ends",
        "",
        "  # Same logic mirrors for cut_end",
        "  RETURN (snapped_start, snapped_end, list_of_notes)",
    ], styles))
    elems.append(sp())

    elems.append(Paragraph("Worked example:", styles["h3"]))
    elems.append(ascii_box([
        "Words: 'Hello'(0.1-0.6s)  'there'(0.8-1.3s)  'world'(1.5-1.9s)",
        "",
        "User cut: [0.4, 1.1]  (lands inside 'Hello' and inside 'there')",
        "",
        "cut_start=0.4 is in first half of 'Hello' (mid=0.35? No, 0.4 > 0.35).",
        "  -> Actually 0.4 > mid(0.35), so snap to AFTER Hello: snapped_start = 0.6+0.05 = 0.65",
        "",
        "cut_end=1.1 is in second half of 'there' (mid=1.05, 1.1 > 1.05).",
        "  -> Snap to AFTER 'there': snapped_end = min(1.5, 1.3+0.05) = 1.35",
        "",
        "Final snapped cut: [0.65, 1.35]  -- removes the gap between 'Hello' and 'there'.",
        "Both words are fully preserved in audio.",
    ], styles))
    elems.append(sp())
    elems.append(callout(
        "padding_s=0.05 (50ms) is added as a safety buffer around word boundaries. "
        "This ensures clean silence at the cut point rather than clipping a consonant.",
        styles, bg=GREEN_BG, label="TIP"))
    elems.append(PageBreak())
    return elems


# ─── Section 6: Skip / Silence Removal ───────────────────────────────────────
def section_skip(styles):
    elems = []
    elems.append(section_header("6. HOW SKIP WORKS: SILENCE REMOVAL", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "The 'skip silences' operation (<b>execute_remove_silences</b>) finds gaps in the "
        "transcript that are longer than a threshold and cuts them down to a short natural "
        "breathing pause. It does NOT remove all silence -- it preserves <b>keep_pause_s</b> "
        "seconds of natural rhythm.",
        styles["body"]))
    elems.append(sp())

    elems.append(Paragraph("Parameters:", styles["h3"]))
    elems.append(header_table(
        ["Parameter", "Default", "Meaning"],
        [
            ("min_silence_s", "1.0 s",
             "Only silence gaps LONGER than this are touched. Shorter pauses are left alone."),
            ("keep_pause_s", "0.20 s",
             "Amount of silence to preserve at each cut point. Keeps speech feeling natural."),
        ],
        [3.5 * cm, 2 * cm, 11.1 * cm], styles))
    elems.append(sp())

    elems.append(Paragraph("The three kinds of silence detected:", styles["h3"]))
    elems.append(ascii_box([
        "# 1. Pre-speech silence (before first word)",
        "if words[0].start > min_silence_s:",
        "    silences.append((0.0, words[0].start - keep_pause_s))",
        "",
        "# 2. Between-word gaps (the most common case)",
        "for i in range(len(words) - 1):",
        "    gap = words[i+1].start - words[i].end",
        "    if gap > min_silence_s:",
        "        cut_start = words[i].end   + (keep_pause_s / 2.0)  # leave 100ms after word",
        "        cut_end   = words[i+1].start - (keep_pause_s / 2.0)  # leave 100ms before next",
        "        silences.append((cut_start, cut_end))",
        "",
        "# 3. Post-speech silence (after last word)",
        "if (total_duration - words[-1].end) > min_silence_s:",
        "    silences.append((words[-1].end + keep_pause_s, total_duration))",
    ], styles))
    elems.append(sp())

    elems.append(Paragraph("Example:", styles["h3"]))
    elems.append(ascii_box([
        "Words: 'I'(0.0-0.2s)  'think'(0.4-0.8s)  [silence]  'so'(5.2-5.5s)",
        "Gap between 'think' and 'so': 5.2 - 0.8 = 4.4 seconds",
        "min_silence_s=1.0  --> 4.4 > 1.0, so this gets cut",
        "keep_pause_s=0.20:",
        "  cut_start = 0.8 + 0.10 = 0.90s",
        "  cut_end   = 5.2 - 0.10 = 5.10s",
        "  Duration removed: 4.2s",
        "  Remaining gap between 'think' and 'so' in playback: 0.20s (natural pause)",
    ], styles))
    elems.append(sp())
    elems.append(callout(
        "All silence cuts are applied in reverse order (latest first) to keep earlier "
        "timestamps valid. This is the same strategy used for filler word removal.",
        styles, bg=AMBER_BG, label="IMPORTANT"))
    elems.append(PageBreak())
    return elems


# ─── Section 7: Filler Word Detection ────────────────────────────────────────
def section_filler(styles):
    elems = []
    elems.append(section_header("7. FILLER WORD DETECTION", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "Filler words like <i>um</i>, <i>uh</i>, <i>er</i>, <i>ah</i> are always removed when "
        "detected. The word <i>like</i> requires context-sensitive analysis because it is "
        "sometimes used as a real word ('I like coffee') and sometimes as a filler "
        "('It was, like, amazing').",
        styles["body"]))
    elems.append(sp())

    elems.append(Paragraph("Default filler list:", styles["h3"]))
    elems.append(ascii_box([
        'fillers = ["um", "uh", "er", "ah"]   # always removed',
        '# "like" is conditionally removed based on context (see below)',
    ], styles))
    elems.append(sp())

    elems.append(Paragraph("Context-sensitive 'like' detection:", styles["h3"]))
    elems.append(ascii_box([
        'if clean_text == "like":',
        "    prev_word = words[i-1] if i > 0 else None",
        "    next_word = words[i+1] if i+1 < len(words) else None",
        "",
        "    gap_before = w.start - prev_word.end  if prev_word else 0.5",
        "    gap_after  = next_word.start - w.end  if next_word else 0.5",
        "",
        "    # Treat as filler if:",
        "    # (a) preceded by >250ms silence, OR",
        "    # (b) followed by >250ms silence, OR",
        "    # (c) immediately follows another filler word (e.g. 'um like')",
        "    if gap_before > 0.25 or gap_after > 0.25 or \\",
        '       (prev_word and prev_word.text.lower() in fillers):',
        "        is_filler = True",
    ], styles))
    elems.append(sp())

    elems.append(Paragraph("30ms padding on each side:", styles["h3"]))
    elems.append(ascii_box([
        "# Each filler word cut gets 30ms safety padding:",
        "cuts_to_make.append((w.start - 0.03, w.end + 0.03, clean_text))",
        "",
        "# Then silence-snapped to avoid clipping adjacent words.",
        "# Applied in reverse order (end-to-start) to preserve timestamp validity.",
    ], styles))
    elems.append(sp())

    elems.append(Paragraph("Decision table for 'like':", styles["h3"]))
    elems.append(header_table(
        ["Situation", "gap_before", "gap_after", "prev is filler?", "Action"],
        [
            ("'like' in 'I like coffee'",   "< 250ms", "< 250ms", "No",  "KEEP -- real usage"),
            ("'like' in 'It was, like, great'", "> 250ms", "> 250ms", "No", "REMOVE -- filler"),
            ("'um like I said'",            "any",     "any",     "Yes (um)", "REMOVE -- filler chain"),
            ("'like' at sentence start",    "> 250ms", "< 250ms", "No",  "REMOVE -- isolated filler"),
        ],
        [4 * cm, 2.2 * cm, 2.2 * cm, 2.5 * cm, 5.7 * cm],
        styles))
    elems.append(PageBreak())
    return elems


# ─── Section 8: Speed Changes ─────────────────────────────────────────────────
def section_speed(styles):
    elems = []
    elems.append(section_header("8. SPEED CHANGES", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "Speed changes work by splitting a clip at the requested boundaries and "
        "setting a different <b>speed</b> value on the middle segment. "
        "The source media range does not change -- only the playback speed factor does. "
        "This means the viewer sees the same content, just faster or slower.",
        styles["body"]))
    elems.append(sp())

    elems.append(Paragraph("The source_relative flag:", styles["h3"]))
    elems.append(header_table(
        ["source_relative", "Meaning", "When used"],
        [
            ("False (default)",
             "start_s and end_s are playback clock positions (what the viewer sees)",
             "Normal user instruction: 'speed up the section from 1:00 to 1:30'"),
            ("True",
             "start_s and end_s are positions in the ORIGINAL media (source timestamps)",
             "History replay: stored operations always use source timestamps for determinism"),
        ],
        [3 * cm, 6.5 * cm, 7.1 * cm],
        styles))
    elems.append(sp())

    elems.append(Paragraph("Algorithm -- apply_speed(start_s, end_s, speed):", styles["h3"]))
    elems.append(ascii_box([
        "BEFORE speed change:",
        "  |------ Clip A (0.0 -> 60.0s, speed 1.0) ------|",
        "",
        "User: 'speed up 20s to 40s to 2x'",
        "",
        "AFTER speed change:",
        "  |-- Clip A1 (0.0->20.0s, 1x) --| Clip B (20.0->40.0s, 2x) | Clip A2 (40.0->60.0s, 1x) --|",
        "",
        "Playback timeline:",
        "  Clip A1: 20s source -> 20s playback (1x)",
        "  Clip B:  20s source -> 10s playback (2x, half the time)",
        "  Clip A2: 20s source -> 20s playback (1x)",
        "  TOTAL: 50s playback (was 60s, saved 10s)",
    ], styles))
    elems.append(sp())

    elems.append(Paragraph("History replay and determinism:", styles["h3"]))
    elems.append(ascii_box([
        "# When saving to history, source timestamps are stored:",
        'op_result = {"op": "speed_up", "orig_start": 20.0, "orig_end": 40.0, "speed": 2.0}',
        "",
        "# During replay_history(), source_relative=True is used so that",
        "# even if previous cuts changed playback times, the correct",
        "# source media segment is always sped up.",
    ], styles))
    elems.append(sp())
    elems.append(callout(
        "Speed changes NEVER alter captions. A caption anchored to words inside the sped-up "
        "range will automatically display for a shorter duration (because those words play faster). "
        "The engine enforces a minimum caption display duration of 0.7 seconds for readability.",
        styles, bg=LIGHT_BLUE, label="KEY BEHAVIOUR"))
    elems.append(PageBreak())
    return elems


# ─── Section 9: Word ID Anchoring ────────────────────────────────────────────
def section_anchoring(styles):
    elems = []
    elems.append(section_header("9. WORD ID ANCHORING  (engine/core/word_anchor.py)", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "The anchor engine solves one fundamental problem: given a caption or audio effect "
        "attached to a word, <i>where exactly does it appear after cuts, speed changes, and reorders?</i> "
        "The answer is two bidirectional mapping functions that walk the clips array.",
        styles["body"]))
    elems.append(sp())

    elems.append(Paragraph("map_source_time_to_playback(source_time, clips):", styles["h3"]))
    elems.append(ascii_box([
        "accumulated_playback = 0.0",
        "",
        "FOR each clip in clips (in order):",
        "    IF source_time falls within clip.source_start .. clip.source_end:",
        "        offset_in_clip  = source_time - clip.source_start",
        "        playback_offset = offset_in_clip / clip.speed   # scale by speed",
        "        RETURN accumulated_playback + playback_offset",
        "",
        "    accumulated_playback += clip.playback_duration",
        "",
        "RETURN None   # source_time is in a cut region -- not visible in playback",
    ], styles))
    elems.append(sp())

    elems.append(Paragraph("map_playback_time_to_source(playback_time, clips):", styles["h3"]))
    elems.append(ascii_box([
        "accumulated_playback = 0.0",
        "",
        "FOR each clip in clips:",
        "    IF playback_time falls within [accumulated, accumulated + clip.playback_duration]:",
        "        offset_in_clip = (playback_time - accumulated) * clip.speed",
        "        RETURN clip.source_start + offset_in_clip",
        "",
        "    accumulated_playback += clip.playback_duration",
        "",
        "RETURN None   # playback_time is beyond the end of the timeline",
    ], styles))
    elems.append(sp())

    elems.append(Paragraph("How captions use these functions:", styles["h3"]))
    elems.append(ascii_box([
        "FOR each word_id in caption.word_ids:",
        "    word = transcript.get_word(word_id)      # O(n) lookup, immutable transcript",
        "    p_start = map_source_time_to_playback(word.start, clips)",
        "    p_end   = map_source_time_to_playback(word.end,   clips)",
        "",
        "    IF p_start is None or p_end is None:",
        "        # Word was cut -- caption partially hidden",
        "        add warning: 'Caption X: word Y was cut'",
        "    ELSE:",
        "        present_word_times.append((p_start, p_end))",
        "",
        "# Caption playback span = min(starts) to max(ends) of present words",
        "# If duration < 0.7s, extend end to start + 0.7s (minimum readability)",
    ], styles))
    elems.append(PageBreak())
    return elems


# ─── Section 10: Captions ────────────────────────────────────────────────────
def section_captions(styles):
    elems = []
    elems.append(section_header("10. CAPTIONS: ADD, RESOLVE & STYLE", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "Captions are non-destructive overlays. Adding, restyling, or removing a caption "
        "never changes the clips array. They are stored in <b>captions: List[AnchoredCaption]</b> "
        "and resolved to playback timestamps on demand.",
        styles["body"]))
    elems.append(sp())

    elems.append(Paragraph("execute_add_caption() -- phrase matching algorithm:", styles["h3"]))
    elems.append(ascii_box([
        "# Step 1: Try exact word_ids provided by caller",
        "matched_ids = word_ids or []",
        "",
        "# Step 2: Sliding window phrase search in transcript",
        "if not matched_ids and target_phrase:",
        "    phrase_words = target_phrase.lower().split()",
        "    FOR i in range(len(all_words) - len(phrase_words) + 1):",
        "        window = [word.text.lower() for word in all_words[i:i+len(phrase_words)]]",
        "        IF window == phrase_words:",
        "            matched_ids = [all_words[i+j].id for j in range(len(phrase_words))]",
        "            BREAK",
        "",
        "# Step 3: Fallback to first 4 words if no match found",
        "if not matched_ids:",
        "    matched_ids = [w.id for w in transcript.words[:4]]",
    ], styles))
    elems.append(sp())

    elems.append(Paragraph("CaptionStyle fields:", styles["h3"]))
    elems.append(header_table(
        ["Field", "Default", "Options"],
        [
            ("color", "white", "Any CSS colour string: 'yellow', '#ff0000', etc."),
            ("font_size", "28", "Integer point size"),
            ("position", "bottom", "'top', 'middle', 'bottom'"),
            ("background_box", "True", "True = dark semi-transparent box behind text"),
            ("highlight_color", "None", "Optional colour to highlight the active word (karaoke style)"),
        ],
        [3 * cm, 2.5 * cm, 11.1 * cm], styles))
    elems.append(sp())

    elems.append(Paragraph("Resolution guarantees:", styles["h3"]))
    rows = [
        ("All words present", "Caption displays normally at computed playback span"),
        ("Some words cut", "Caption shows on remaining words with a partial-cut warning"),
        ("All words cut", "Caption is hidden (active=True, but produces no ResolvedCaption)"),
        ("Words sped up 5x", "Caption duration scales down; floored at 0.70s minimum"),
        ("Clip reordered", "Caption follows its words to their new playback position"),
    ]
    elems.append(header_table(
        ["Scenario", "Behaviour"],
        rows,
        [5 * cm, 11.6 * cm], styles))
    elems.append(PageBreak())
    return elems


# ─── Section 11: Mute / Bleep ─────────────────────────────────────────────────
def section_mute_bleep(styles):
    elems = []
    elems.append(section_header("11. MUTE / BLEEP AUDIO EFFECTS", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "Audio effects work identically to captions under the hood: they are anchored to "
        "Word IDs and resolved to current playback timestamps by the same mapping functions. "
        "The key difference is that they affect audio output, not visual overlays.",
        styles["body"]))
    elems.append(sp())

    elems.append(Paragraph("execute_bleep_or_mute_words():", styles["h3"]))
    elems.append(ascii_box([
        "# 1. Find all Word IDs matching the target words",
        "target_ids = []",
        "for word in transcript.words:",
        "    clean = word.text.lower().strip('.,!?')",
        "    if clean in words_to_mute:",
        "        target_ids.append(word.id)",
        "",
        "# 2. Create AnchoredAudioEffect pointing to those IDs",
        "effect = AnchoredAudioEffect(",
        "    effect_type = 'bleep',   # or 'mute'",
        "    word_ids    = target_ids,",
        "    active      = True",
        ")",
        "timeline.effects.append(effect)",
        "",
        "# 3. At render time: resolve_audio_effects() maps each word.start/end",
        "#    to playback timestamps using map_source_time_to_playback()",
        "# -> If word is cut, effect is simply skipped (None returned from map).",
    ], styles))
    elems.append(sp())

    elems.append(header_table(
        ["effect_type", "Audio behaviour at render"],
        [
            ("mute",  "Audio replaced with silence for the duration of each matched word"),
            ("bleep", "Audio replaced with a 1kHz beep tone for the duration of each word"),
        ],
        [3 * cm, 13.6 * cm], styles))
    elems.append(PageBreak())
    return elems


# ─── Section 12: Auto-Captions ────────────────────────────────────────────────
def section_auto_caption(styles):
    elems = []
    elems.append(section_header("12. AUTO-CAPTIONS", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "Auto-captions chunk the entire transcript into groups and create one "
        "<b>AnchoredCaption</b> per group. Because they are anchored to Word IDs (not timestamps), "
        "they survive cuts, speed changes, and reorders automatically.",
        styles["body"]))
    elems.append(sp())
    elems.append(ascii_box([
        "def execute_auto_caption(timeline, words_per_caption=4):",
        "    words = timeline.transcript.words",
        "    for i in range(0, len(words), words_per_caption):",
        "        chunk     = words[i : i + words_per_caption]",
        "        text      = ' '.join(w.text for w in chunk)",
        "        chunk_ids = [w.id for w in chunk]",
        "        timeline.apply_add_caption(text=text, word_ids=chunk_ids)",
        "",
        "# Example with 12 words, words_per_caption=4:",
        "#   Caption 1: words w_0..w_3  -> 'Hello there how are'",
        "#   Caption 2: words w_4..w_7  -> 'you doing today friend'",
        "#   Caption 3: words w_8..w_11 -> 'I am doing well'",
    ], styles))
    elems.append(sp())
    elems.append(callout(
        "Auto-captions are the same as manual captions internally. You can restyle, "
        "delete, or override any individual auto-caption after generation.",
        styles, bg=GREEN_BG, label="TIP"))
    elems.append(PageBreak())
    return elems


# ─── Section 13: Undo / Redo / Restore ────────────────────────────────────────
def section_undo_redo(styles):
    elems = []
    elems.append(section_header("13. UNDO / REDO / RESTORE", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "Because the original media is never changed and all edits are in an append-only "
        "history, undo and redo are implemented by <b>replaying history from scratch</b>. "
        "This guarantees 100% mathematical consistency -- there is no partial state corruption possible.",
        styles["body"]))
    elems.append(sp())

    elems.append(Paragraph("undo():", styles["h3"]))
    elems.append(ascii_box([
        "def undo(self):",
        "    active_steps = [s for s in self.history if not s.undone]",
        "    last_step = active_steps[-1]",
        "    last_step.undone = True          # Mark the step as undone",
        "    self.redo_stack.append(last_step) # Save for redo",
        "    self.replay_history()            # Rebuild clips from scratch",
    ], styles))
    elems.append(sp())

    elems.append(Paragraph("replay_history():", styles["h3"]))
    elems.append(ascii_box([
        "def replay_history(self):",
        "    self._reset_to_base()            # Start with single full-length clip",
        "    for step in self.history:",
        "        if step.undone: continue     # Skip undone steps",
        "        for op in step.operations:",
        "            if op.op_type == 'cut_range':",
        "                self.apply_cut(p['source_start'], p['source_end'],",
        "                               source_relative=True)",
        "            elif op.op_type == 'speed_up':",
        "                self.apply_speed(p['orig_start'], p['orig_end'],",
        "                                 p['speed'], source_relative=True)",
        "            # ... captions, effects, music etc.",
    ], styles))
    elems.append(sp())

    elems.append(Paragraph("restore_step() -- non-linear undo:", styles["h3"]))
    elems.append(Paragraph(
        "Unlike undo() which always reverses the latest step, restore_step(step_index) can "
        "target any historical step. For example, 'bring back the intro I cut 3 steps ago'. "
        "It marks that specific step as undone and replays all remaining active steps.",
        styles["body"]))
    elems.append(sp())

    elems.append(header_table(
        ["Operation", "Behaviour"],
        [
            ("undo()", "Marks the most recent active step as undone, rebuilds timeline"),
            ("redo()", "Pops the most recent undone step from redo_stack, rebuilds timeline"),
            ("restore_step(n)", "Marks step n as undone regardless of order, rebuilds timeline"),
            ("record_step()", "Appends a new step to history and clears the redo stack"),
        ],
        [4 * cm, 12.6 * cm], styles))
    elems.append(PageBreak())
    return elems


# ─── Section 14: SHA-256 Hashing ──────────────────────────────────────────────
def section_hashing(styles):
    elems = []
    elems.append(section_header("14. SHA-256 TIMELINE HASHING  (engine/core/hashing.py)", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "After every edit, the engine computes a <b>timeline_hash</b>: a SHA-256 fingerprint "
        "of the complete timeline state. Running the same session on the same source file "
        "always produces the identical hash -- guaranteed by canonical serialization.",
        styles["body"]))
    elems.append(sp())

    elems.append(Paragraph("What goes into the hash:", styles["h3"]))
    elems.append(header_table(
        ["Component", "How it is canonicalized"],
        [
            ("source_sha256", "SHA-256 of the original media file (seeds the entire hash)"),
            ("clips", "source_start, source_end, speed rounded to 3dp; word_ids sorted"),
            ("captions", "Only active captions; word_ids sorted; text stripped; id-sorted"),
            ("effects", "Only active effects; word_ids sorted; sorted by effect_id"),
            ("music", "volume and ducking_volume rounded to 3dp; sorted by track_id"),
        ],
        [4 * cm, 12.6 * cm], styles))
    elems.append(sp())

    elems.append(Paragraph("Serialization:", styles["h3"]))
    elems.append(ascii_box([
        'payload = {',
        '    "source_sha256": source_sha256,',
        '    "clips":    canonical_clips,    # list, in playback order',
        '    "captions": canonical_captions, # sorted by caption_id',
        '    "effects":  canonical_effects,  # sorted by effect_id',
        '    "music":    canonical_music,    # sorted by track_id',
        '}',
        '',
        '# Deterministic JSON serialization:',
        'serialized = json.dumps(payload, sort_keys=True, separators=(",",":"))',
        'timeline_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()',
    ], styles))
    elems.append(sp())
    elems.append(callout(
        "Floating-point timestamps are rounded to 3 decimal places (millisecond precision) "
        "before hashing to prevent platform-specific floating-point differences from "
        "producing different hashes on different machines.",
        styles, bg=AMBER_BG, label="CROSS-PLATFORM GUARANTEE"))
    elems.append(PageBreak())
    return elems


# ─── Section 15: Background Music ─────────────────────────────────────────────
def section_music(styles):
    elems = []
    elems.append(section_header("15. BACKGROUND MUSIC & DUCKING", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "Background music tracks run as a separate overlay layer. They do not affect the clips "
        "array. Auto-ducking automatically lowers the music volume under speech segments "
        "so the speaker stays intelligible.",
        styles["body"]))
    elems.append(sp())

    elems.append(header_table(
        ["Parameter", "Default", "Meaning"],
        [
            ("volume", "0.20 (20%)", "Music volume during non-speech segments"),
            ("ducking_volume", "0.05 (5%)", "Music volume during speech (auto-ducked)"),
            ("duck_under_speech", "True", "Enable automatic ducking under speech"),
        ],
        [3.5 * cm, 3 * cm, 10.1 * cm], styles))
    elems.append(sp())
    elems.append(ascii_box([
        "# BackgroundMusicTrack model:",
        "class BackgroundMusicTrack(BaseModel):",
        "    music_file_path: str",
        "    volume:          float = 0.20",
        "    ducking_volume:  float = 0.05",
        "    duck_under_speech: bool = True",
        "",
        "# At render time, the audio pipeline:",
        "# 1. Plays music_file_path looped to match total_duration",
        "# 2. Detects speech regions from resolved word timestamps",
        "# 3. Applies volume envelope: ducking_volume during speech, volume otherwise",
    ], styles))
    elems.append(PageBreak())
    return elems


# ─── Section 16: End-to-End Lifecycle ─────────────────────────────────────────
def section_lifecycle(styles):
    elems = []
    elems.append(section_header("16. END-TO-END EDIT LIFECYCLE", styles))
    elems.append(sp())
    elems.append(Paragraph(
        "This section traces what happens from the moment a user types an instruction "
        "in the AI chat to the moment the final video is rendered.",
        styles["body"]))
    elems.append(sp())

    lifecycle = [
        ("1", "User types instruction",
         "e.g. 'Remove all umms and ahhs and speed up the boring bits'"),
        ("2", "LLM parses intent",
         "GPT-4o / Gemini analyzes the instruction and emits structured JSON operations"),
        ("3", "execute_* called",
         "operations.py dispatches to execute_remove_filler_words() and execute_remove_silences()"),
        ("4", "Silence snapping",
         "Each cut boundary is adjusted by snap_cut_boundaries_to_silence() before apply_cut()"),
        ("5", "apply_cut() / apply_speed()",
         "Timeline's clips array is mutated; word_ids recomputed; no source file touched"),
        ("6", "record_step()",
         "Instruction, operations, and summary appended to history log"),
        ("7", "compute_timeline_hash()",
         "SHA-256 fingerprint of the new timeline state returned with the response"),
        ("8", "InstructionResult returned",
         "API response includes status, ops list, summary, new duration, and hash"),
        ("9", "Anchor resolution (optional)",
         "get_resolved_captions() and get_resolved_audio_effects() map anchors to playback times"),
        ("10", "Render export",
         "OTIO / FFmpeg render uses clips to construct video; overlays applied from resolved anchors"),
    ]
    elems.append(header_table(
        ["#", "Stage", "Detail"],
        lifecycle,
        [0.8 * cm, 4.5 * cm, 11.3 * cm], styles))
    elems.append(sp())

    elems.append(Paragraph("Data flow diagram (text):", styles["h3"]))
    elems.append(ascii_box([
        "User Chat",
        "   |",
        "   v",
        "LLM (GPT-4o / Gemini)  -->  JSON operation list",
        "   |",
        "   v",
        "operations.py::execute_*(timeline, ...)",
        "   |",
        "   +-- snap_cut_boundaries_to_silence()  [silence_snap.py]",
        "   |",
        "   v",
        "timeline.apply_cut() / apply_speed() / apply_add_caption() ...  [timeline.py]",
        "   |",
        "   +-- clips[] mutated",
        "   +-- history[] appended  -->  record_step()",
        "   +-- compute_timeline_hash()  [hashing.py]",
        "   |",
        "   v",
        "InstructionResult { status, ops, summary, duration_s, timeline_hash }",
        "   |",
        "   v",
        "Render pipeline  -->  get_resolved_captions()  [word_anchor.py]",
        "                  -->  get_resolved_audio_effects()",
        "                  -->  OTIO / FFmpeg export",
    ], styles))
    elems.append(PageBreak())
    return elems


# ─── Back cover / summary page ────────────────────────────────────────────────
def summary_page(styles):
    elems = []
    elems.append(section_header("QUICK REFERENCE SUMMARY", styles))
    elems.append(sp())

    summary = [
        ("Cut", "execute_cut_range()", "Splits clips, removes range, rebinds word_ids"),
        ("Skip silence", "execute_remove_silences()", "Detects gaps >1s, cuts to keep_pause_s=200ms"),
        ("Remove fillers", "execute_remove_filler_words()", "Removes um/uh/er/ah + contextual 'like'"),
        ("Speed up", "execute_speed_change()", "Splits clip, sets speed factor on middle segment"),
        ("Add caption", "execute_add_caption()", "Phrase match -> word_ids anchor, stored in captions[]"),
        ("Auto-caption", "execute_auto_caption()", "Chunks all words by N, creates AnchoredCaption per chunk"),
        ("Mute words", "execute_bleep_or_mute_words('mute')", "AnchoredAudioEffect on word_ids"),
        ("Bleep words", "execute_bleep_or_mute_words('bleep')", "1kHz tone overlay on word_ids"),
        ("Undo", "timeline.undo()", "Mark last step undone, replay_history() from scratch"),
        ("Redo", "timeline.redo()", "Pop redo_stack, replay_history()"),
        ("Non-linear undo", "timeline.restore_step(n)", "Mark step n undone, replay_history()"),
        ("Hash", "compute_timeline_hash()", "SHA-256 of canonical JSON; 3dp float rounding"),
        ("Resolve captions", "get_resolved_captions()", "map_source_time_to_playback() per word"),
        ("Resolve effects", "get_resolved_audio_effects()", "Same mapping, per word in effect"),
    ]
    elems.append(header_table(
        ["Operation", "Function", "Mechanism"],
        summary,
        [3.5 * cm, 5.5 * cm, 7.6 * cm],
        styles, hdr_bg=NAVY))
    elems.append(sp(2))
    elems.append(Paragraph(
        "Source files: engine/core/operations.py  |  timeline.py  |  word_anchor.py  |  "
        "silence_snap.py  |  hashing.py  |  models.py",
        ParagraphStyle("footer_note", parent=styles["caption"],
                       textColor=SUBTLE, fontSize=8)))
    return elems


# ─── Main builder ─────────────────────────────────────────────────────────────
def build_pdf(out_path):
    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 15 * mm,
        bottomMargin=MARGIN + 10 * mm,
        title="Concat Editor - Editing Internals Deep Dive",
        author="IncuBrix AI Engine",
    )

    styles = make_styles()
    story = []

    story += cover_page(styles)
    story += table_of_contents(styles)
    story += section_golden_rule(styles)
    story += section_data_models(styles)
    story += section_timeline_object(styles)
    story += section_cut(styles)
    story += section_silence_snap(styles)
    story += section_skip(styles)
    story += section_filler(styles)
    story += section_speed(styles)
    story += section_anchoring(styles)
    story += section_captions(styles)
    story += section_mute_bleep(styles)
    story += section_auto_caption(styles)
    story += section_undo_redo(styles)
    story += section_hashing(styles)
    story += section_music(styles)
    story += section_lifecycle(styles)
    story += summary_page(styles)

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF written: {out_path}")


if __name__ == "__main__":
    out = r"N:\Concat\Concat_Editing_Internals_Deep_Dive.pdf"
    build_pdf(out)

    # Copy to artifact directory
    import shutil
    art = r"C:\Users\Nathan\.gemini\antigravity\brain\f2f3d9a3-7848-492e-945e-d1884de56a21\Concat_Editing_Internals_Deep_Dive.pdf"
    shutil.copy2(out, art)
    print(f"Copied to: {art}")
