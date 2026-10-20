# Metrics

Measured by `incubrix metrics` (release build).

| Metric | Value |
|---|---|
| Instruction latency, 5-minute video (563 words, 23 instructions) | median 1.7 ms, slowest 12.9 ms ("Add a caption 'Welcome!' when I say welcome to the channel") |
| Instruction latency, 60-minute video (6936 words, 23 instructions) | median 107.0 ms, slowest 433.8 ms ("auto-caption the whole video") |
| Render accuracy (4 renders) | largest length difference 0.49 frames, largest A/V offset 0.00 frames |
| Determinism | 100% of 47 sessions identical across 3 runs |
| Clarification quality | 14 open instructions: 6 asked, 1 stated an assumption, 5 had one candidate and named it, 2 refused with a reason, 0 guessed |
| Word clipping | 0 of 20 cuts' edges inside a word (automatic check against word timings) |
| Cost | speech-to-text $0.00/min (local whisper), language model $0.00/min (rules parser; an optional LLM is billed by its provider) |

## Ambiguous instructions

- "Remove the part about pricing": asked
- "Make that caption red": one candidate, named in the reply
- "Speed up 10x": refused with a reason
- "make it bigger, red and at the top": one candidate, named in the reply
- "change the caption to 'Hello!'": one candidate, named in the reply
- "remove the caption": one candidate, named in the reply
- "make it bigger": refused with a reason
- "put back what I removed": stated an assumption
- "bleep the swearing": one candidate, named in the reply
- "put back what I removed": asked
- "Remove the part about pricing": asked
- "Remove the part about pricing": asked
- "remove the boring bit": asked
- "make it shorter": asked

## 5-minute video, each instruction

- 12.9 ms: Add a caption 'Welcome!' when I say welcome to the channel
- 0.2 ms: Add a caption 'Welcome!' when I say welcome to the channel -> the first one
- 3.2 ms: Cut the first 30 seconds
- 3.7 ms: Remove the part about pricing
- 0.2 ms: Remove the part about pricing -> the first one
- 1.6 ms: Speed up from 1:00 to 1:30 by 2x
- 0.5 ms: Actually, put the intro back
- 0.1 ms: Undo
- 0.1 ms: redo
- 3.2 ms: Make that caption red
- 0.4 ms: remove the ums
- 1.0 ms: remove silences longer than 1 second
- 2.8 ms: cut 2:00 to 2:10
- 3.1 ms: slow down 3:00 to 3:10 by 2x
- 1.7 ms: add a caption 'Late' at 4:00
- 1.7 ms: bleep the word dollars
- 1.2 ms: move 0:40 to 0:50 to the end
- 5.8 ms: keep only 1:00 to 4:30
- 1.5 ms: put back what I removed
- 2.8 ms: put back what I removed -> all of it
- 5.5 ms: auto-caption the whole video
- 2.2 ms: how long is my video now?
- 1.4 ms: undo

## 60-minute video, each instruction

- 16.4 ms: Add a caption 'Welcome!' when I say welcome to the channel
- 2.6 ms: Add a caption 'Welcome!' when I say welcome to the channel -> the first one
- 2.6 ms: Cut the first 30 seconds
- 14.6 ms: Remove the part about pricing
- 1.8 ms: Remove the part about pricing -> the first one
- 1.8 ms: Speed up from 1:00 to 1:30 by 2x
- 2.4 ms: Actually, put the intro back
- 0.2 ms: Undo
- 0.2 ms: redo
- 1.7 ms: Make that caption red
- 5.0 ms: remove the ums
- 107.0 ms: remove silences longer than 1 second
- 283.6 ms: cut 2:00 to 2:10
- 417.2 ms: slow down 3:00 to 3:10 by 2x
- 280.4 ms: add a caption 'Late' at 4:00
- 138.5 ms: bleep the word dollars
- 119.3 ms: move 0:40 to 0:50 to the end
- 269.2 ms: keep only 1:00 to 4:30
- 108.5 ms: put back what I removed
- 195.0 ms: put back what I removed -> all of it
- 433.8 ms: auto-caption the whole video
- 182.0 ms: how long is my video now?
- 130.1 ms: undo
