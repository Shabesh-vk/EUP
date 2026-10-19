# Content-Anchored Video Editing: Design & Projection Model

## 1. The Fundamental Problem: Fragile Clock Coordinates
In traditional video editing or naive prompt-based systems, editing instructions are commonly evaluated against raw playback timestamps. For example:
- A user types: *"Add caption 'Welcome!' when I say welcome to the channel"* (spoken at `0:42-0:44`).
- Next, the user types: *"Cut the first 30 seconds"*.
- If the caption was stored at output time `0:42`, it will now display at `0:42` of the *new* video—which corresponds to `1:12` in the source video. The caption has silently detached from the words and lands on completely unrelated speech.

The single most important design rule in the IncuBrix engine is: **Edits belong to content, not to clock positions**.

---

## 2. Dual Coordinate Spaces

The IncuBrix engine separates temporal state into two strictly isolated domains:

```
[Immutable Source Media (t_source)]
  Word w_1 ("welcome") : [42000 ms, 42500 ms]
  Word w_2 ("to")      : [42500 ms, 42700 ms]
  Word w_3 ("the")     : [42700 ms, 42850 ms]
  Word w_4 ("channel") : [42850 ms, 44000 ms]
  Caption Effect C_1 anchored to [w_1, w_2, w_3, w_4] -> [42000 ms, 44000 ms]

         │
         │ Deterministic Projection (f: t_source -> t_output)
         ▼

[Active Playback Segments (t_output)]
  Segment S_1: Source [30000 ms -> 60000 ms] @ 1.0x  => Output [0 ms -> 30000 ms]
  Segment S_2: Source [60000 ms -> 90000 ms] @ 2.0x  => Output [30000 ms -> 45000 ms]
  Segment S_3: Source [90000 ms -> 120000 ms] @ 1.0x => Output [45000 ms -> 75000 ms]

  Resulting Output for Caption C_1:
  t_output_start = (42000 - 30000) = 12000 ms (0:12)
  t_output_end   = (44000 - 30000) = 14000 ms (0:14)
```

1. **Source Coordinate Space ($t_{source}$)**:
   - Fixed, immutable temporal coordinates anchored to the original media.
   - All transcript words possess permanent IDs, source start/end times in integer ticks, speaker tags, and confidence scores.
   - Effects (captions, mutes, bleeps, overlays) anchor to **Word IDs** and source intervals, never output time.

2. **Projected Playback Space ($t_{output}$)**:
   - An ordered list of active playback segments $[s_{start}^{(k)}, s_{end}^{(k)}]$ with speed multipliers $r_k$.
   - Output time is a pure function of active segments:
     $$t_{output}(t_{source}) = \sum_{j < k} \frac{s_{end}^{(j)} - s_{start}^{(j)}}{r_j} + \frac{t_{source} - s_{start}^{(k)}}{r_k}$$
   - Any modification (cutting, reordering, speeding up, or restoring) simply mutates the segment list or speed ratios. Effects automatically and deterministically evaluate to their correct output positions.

---

## 3. Preservation, Suppression, and Restoration

1. **Cutting Content with Attached Effects**:
   - When a segment of video containing a captioned or bleeped phrase is cut, the effect definition is **not deleted**.
   - Instead, the engine detects that the anchor's source interval no longer intersects any active playback segment. The effect is marked `is_suppressed = True` with a documented reason (`"Content range cut"`).
   - If the cut segment is subsequently restored (via undo, redo, or targeted selective restore), the effect automatically resurfaces at the correct playback time.

2. **Partial Phrase Cuts**:
   - If a user cuts a sub-interval of a captioned phrase (e.g., words 3-4 of a 5-word caption), the surviving words remain anchored.
   - The engine updates the active anchor span to the surviving words and emits a structured warning (`"Caption anchor shortened to surviving words"`). If zero words survive, the caption is suppressed.

3. **Sped-Up Captions**:
   - If speech under a caption is sped up (e.g. $2\times$), the spoken duration may drop below readable comprehension.
   - The engine enforces a minimum readable duration threshold (nominally $0.7\,\text{s}$). If the projected duration is under $0.7\,\text{s}$, the caption's visual display window is clamped to $\ge 0.7\,\text{s}$ (bounded by subsequent captions or video bounds), ensuring readability while maintaining exact word synchronization.

4. **Targeted Selective Restore**:
   - Rather than rolling back the entire project to an earlier snapshot, restoring an earlier edit identifies the specific source ranges that were excised by that transaction and re-inserts them into the active timeline at their canonical topological source positions. All later independent edits (such as pricing cuts, speed adjustments, and music additions) remain intact.
