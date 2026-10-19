import React, { useRef, useState, useEffect } from "react";
import {
  Film,
  Mic,
  MessageSquare,
  Music,
  Scissors,
  Trash2,
  Plus,
  X,
} from "lucide-react";
import { Timeline, ClipSegment, CaptionEffect, MusicEffect, TranscriptWord } from "../types";

interface TimelineViewProps {
  timeline: Timeline | null;
  currentTime: number;
  onSeek: (timeSec: number) => void;
  onApplyOperation: (opType: string, details: Record<string, any>, instruction?: string) => Promise<void>;
  isApplyingOp?: boolean;
}

export const TimelineView: React.FC<TimelineViewProps> = ({
  timeline,
  currentTime,
  onSeek,
  onApplyOperation,
  isApplyingOp = false,
}) => {
  const tracksLaneRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef(false);

  // Manual Editing States
  const [selectedSegId, setSelectedSegId] = useState<string | null>(null);
  const [inPoint, setInPoint] = useState<number | null>(null);
  const [outPoint, setOutPoint] = useState<number | null>(null);

  // Add Caption Modal State
  const [isCaptionModalOpen, setIsCaptionModalOpen] = useState(false);
  const [captionText, setCaptionText] = useState("");
  const [captionStart, setCaptionStart] = useState<number>(0);
  const [captionEnd, setCaptionEnd] = useState<number>(3);
  const [captionColor, setCaptionColor] = useState("white");
  const [captionFontSize, setCaptionFontSize] = useState(36);
  const [captionPosition, setCaptionPosition] = useState<"bottom" | "top">("bottom");

  // Selected Caption State
  const [selectedCaptionId, setSelectedCaptionId] = useState<string | null>(null);

  const segments = timeline?.segments || [];
  const totalDuration = segments.reduce(
    (acc, s) => acc + (s.source_end_ticks - s.source_start_ticks) / 1000 / (s.speed_ratio || 1.0),
    0
  );

  const safeTotalDuration = Math.max(1, totalDuration);

  // Dynamic seeking calculation accurately against the tracks lane (excluding header labels)
  const handleSeekFromClientX = (clientX: number) => {
    if (!tracksLaneRef.current) return;
    const rect = tracksLaneRef.current.getBoundingClientRect();
    const clickX = clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, clickX / rect.width));
    onSeek(ratio * safeTotalDuration);
  };

  // Dynamic mouse drag handlers for the timeline needle & tracks lane
  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return; // Left click only
    isDraggingRef.current = true;
    handleSeekFromClientX(e.clientX);

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!isDraggingRef.current) return;
      handleSeekFromClientX(moveEvent.clientX);
    };

    const handleMouseUp = () => {
      isDraggingRef.current = false;
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  };

  const playheadPercent = Math.min(100, Math.max(0, (currentTime / safeTotalDuration) * 100));

  // Build segments with computed output start and end times
  let currentOutputS = 0;
  const segmentsWithOutputTime = segments.map((s: ClipSegment, idx: number) => {
    const durS = (s.source_end_ticks - s.source_start_ticks) / 1000 / (s.speed_ratio || 1.0);
    const startS = currentOutputS;
    const endS = currentOutputS + durS;
    currentOutputS = endS;
    return {
      ...s,
      index: idx,
      outStartS: startS,
      outEndS: endS,
      durS,
    };
  });

  const selectedSegment = segmentsWithOutputTime.find((s) => s.segment_id === selectedSegId) || null;
  const selectedCaption = timeline?.effects?.captions?.find((c) => c.id === selectedCaptionId) || null;

  // Split Segment at Current Playhead
  const handleSplitAtPlayhead = async () => {
    await onApplyOperation(
      "split_segment",
      {
        split_seconds: currentTime,
        time_domain: "current_edited_time",
      },
      `Split clip at ${currentTime.toFixed(2)}s`
    );
  };

  // Delete Selected Segment
  const handleDeleteSegment = async (segId: string) => {
    if (!timeline || timeline.segments.length <= 1) {
      alert("Cannot delete the only remaining segment on the timeline.");
      return;
    }
    await onApplyOperation(
      "delete_segment",
      { segment_id: segId },
      `Deleted clip segment ${segId}`
    );
    setSelectedSegId(null);
  };

  // Set Speed for Selected Segment
  const handleSetSegmentSpeed = async (seg: typeof segmentsWithOutputTime[0], newSpeed: number) => {
    await onApplyOperation(
      "speed_range",
      {
        start_seconds: seg.source_start_ticks / 1000,
        end_seconds: seg.source_end_ticks / 1000,
        speed_ratio: newSpeed,
        time_domain: "source_time",
      },
      `Changed ${seg.segment_id} speed to ${newSpeed}x`
    );
  };

  // Cut Selected Range
  const handleCutRange = async () => {
    if (inPoint === null || outPoint === null || outPoint <= inPoint) return;
    await onApplyOperation(
      "cut_range",
      {
        start_seconds: inPoint,
        end_seconds: outPoint,
        time_domain: "current_edited_time",
      },
      `Cut range ${inPoint.toFixed(1)}s to ${outPoint.toFixed(1)}s`
    );
    setInPoint(null);
    setOutPoint(null);
  };

  // Open Add Caption Dialog
  const handleOpenAddCaption = () => {
    setCaptionStart(Math.max(0, parseFloat(currentTime.toFixed(1))));
    setCaptionEnd(Math.min(safeTotalDuration, parseFloat((currentTime + 3.0).toFixed(1))));
    setCaptionText("");
    setIsCaptionModalOpen(true);
  };

  // Map edited output time (seconds) to source ticks
  const mapOutputToSourceTicks = (outSec: number) => {
    if (!segments || segments.length === 0) return Math.round(outSec * 1000);
    let accumOut = 0;
    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i];
      const segStartS = seg.source_start_ticks / 1000;
      const segEndS = seg.source_end_ticks / 1000;
      const speed = Math.max(0.1, seg.speed_ratio || 1.0);
      const segDurOut = (segEndS - segStartS) / speed;

      if (outSec >= accumOut && outSec < accumOut + segDurOut) {
        const deltaOut = outSec - accumOut;
        const srcSec = segStartS + deltaOut * speed;
        return Math.round(srcSec * 1000);
      }
      accumOut += segDurOut;
    }
    const lastSeg = segments[segments.length - 1];
    return lastSeg.source_end_ticks;
  };

  // Submit Add Caption
  const handleSubmitAddCaption = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!captionText.trim()) return;

    const srcStartTicks = mapOutputToSourceTicks(captionStart);
    const srcEndTicks = mapOutputToSourceTicks(captionEnd);

    await onApplyOperation(
      "add_caption",
      {
        text: captionText.trim(),
        source_start_ticks: srcStartTicks,
        source_end_ticks: srcEndTicks,
        start_seconds: captionStart,
        end_seconds: captionEnd,
        color: captionColor,
        font_size: captionFontSize,
        position: captionPosition,
      },
      `Added caption: "${captionText.trim()}"`
    );

    setIsCaptionModalOpen(false);
    setCaptionText("");
  };

  // Keyboard Shortcuts Listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!timeline) return;
      // Don't trigger shortcuts if user is typing in an input or textarea
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;

      if (e.key === "s" || e.key === "S") {
        e.preventDefault();
        handleSplitAtPlayhead();
      } else if (e.key === "i" || e.key === "I") {
        e.preventDefault();
        setInPoint(currentTime);
      } else if (e.key === "o" || e.key === "O") {
        e.preventDefault();
        setOutPoint(currentTime);
      } else if (e.key === "Delete" || e.key === "Backspace") {
        if (selectedSegId) {
          e.preventDefault();
          handleDeleteSegment(selectedSegId);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [currentTime, selectedSegId, timeline]);

  if (!timeline) {
    return (
      <div className="panel" style={{ padding: "24px", textAlign: "center", color: "var(--color-text-muted)" }}>
        No timeline loaded.
      </div>
    );
  }

  return (
    <div
      className="panel"
      style={{
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        border: "1px solid var(--color-border-gloss)",
        boxShadow: "0 16px 36px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.15)",
      }}
    >
      {/* 1. Interactive Manual Editing Toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 14px",
          backgroundColor: "rgba(12, 17, 28, 0.8)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          borderBottom: "1px solid var(--color-border)",
          flexWrap: "wrap",
          gap: "8px",
        }}
      >
        {/* Left: Direct Edit Tools */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          {/* Split at Playhead */}
          <button
            className="btn-secondary"
            onClick={handleSplitAtPlayhead}
            disabled={isApplyingOp}
            title="Split clip at playhead position (Shortcut: S)"
            style={{ padding: "5px 10px", fontSize: "12px", fontWeight: 600 }}
          >
            <Scissors size={13} style={{ color: "var(--color-accent-primary)" }} />
            <span>Split (S)</span>
          </button>

          <div style={{ width: "1px", height: "18px", backgroundColor: "var(--color-border)", margin: "0 2px" }} />

          {/* Mark In */}
          <button
            className={`btn-secondary ${inPoint !== null ? "active" : ""}`}
            onClick={() => setInPoint(currentTime)}
            title="Set In-point at playhead (Shortcut: I)"
            style={{
              padding: "5px 9px",
              fontSize: "12px",
              backgroundColor: inPoint !== null ? "var(--color-selected-bg)" : undefined,
              borderColor: inPoint !== null ? "var(--color-accent-primary)" : undefined,
              color: inPoint !== null ? "var(--color-accent-primary)" : undefined,
            }}
          >
            <span>[ In</span>
            {inPoint !== null && <span style={{ fontSize: "10px", opacity: 0.8 }}>({inPoint.toFixed(1)}s)</span>}
          </button>

          {/* Mark Out */}
          <button
            className={`btn-secondary ${outPoint !== null ? "active" : ""}`}
            onClick={() => setOutPoint(currentTime)}
            title="Set Out-point at playhead (Shortcut: O)"
            style={{
              padding: "5px 9px",
              fontSize: "12px",
              backgroundColor: outPoint !== null ? "var(--color-selected-bg)" : undefined,
              borderColor: outPoint !== null ? "var(--color-accent-primary)" : undefined,
              color: outPoint !== null ? "var(--color-accent-primary)" : undefined,
            }}
          >
            <span>Out ]</span>
            {outPoint !== null && <span style={{ fontSize: "10px", opacity: 0.8 }}>({outPoint.toFixed(1)}s)</span>}
          </button>

          {/* Cut Selected Range */}
          {inPoint !== null && outPoint !== null && outPoint > inPoint && (
            <button
              className="btn-primary"
              onClick={handleCutRange}
              disabled={isApplyingOp}
              title="Delete the highlighted range between In and Out points"
              style={{ padding: "5px 10px", fontSize: "12px", backgroundColor: "#B91C1C", borderColor: "#991B1B" }}
            >
              <Trash2 size={13} />
              <span>Cut Range ({(outPoint - inPoint).toFixed(1)}s)</span>
            </button>
          )}

          {(inPoint !== null || outPoint !== null) && (
            <button
              className="btn-icon"
              onClick={() => {
                setInPoint(null);
                setOutPoint(null);
              }}
              title="Clear In / Out selection"
              style={{ width: "24px", height: "24px" }}
            >
              <X size={12} />
            </button>
          )}

          <div style={{ width: "1px", height: "18px", backgroundColor: "var(--color-border)", margin: "0 2px" }} />

          {/* Add Caption Button */}
          <button
            className="btn-secondary"
            onClick={handleOpenAddCaption}
            title="Add a styled text caption overlay at playhead"
            style={{ padding: "5px 10px", fontSize: "12px" }}
          >
            <Plus size={13} style={{ color: "var(--color-accent-primary)" }} />
            <span>Add Caption</span>
          </button>
        </div>

        {/* Right: Timeline Metrics */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px", fontSize: "12px", color: "var(--color-text-muted)" }}>
          <span><strong>{timeline.segments.length}</strong> clip(s)</span>
          <span><strong>{timeline.effects?.captions?.filter((c) => !c.is_suppressed).length || 0}</strong> caption(s)</span>
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-text-main)", fontWeight: 600 }}>
            Total: {safeTotalDuration.toFixed(1)}s
          </span>
        </div>
      </div>

      {/* 2. Tracks Container: Fixed Left Labels Column + Right Interactive Tracks Lane */}
      <div
        style={{
          display: "flex",
          padding: "10px 14px 14px",
          gap: "10px",
          backgroundColor: "var(--color-surface-panel)",
          userSelect: "none",
        }}
      >
        {/* Left Fixed Column: Track Headers */}
        <div
          style={{
            width: "75px",
            flexShrink: 0,
            display: "flex",
            flexDirection: "column",
            gap: "8px",
          }}
        >
          {/* Top spacer matching time ruler height */}
          <div
            style={{
              height: "22px",
              display: "flex",
              alignItems: "center",
              fontSize: "10px",
              fontWeight: 700,
              color: "var(--color-text-muted)",
              letterSpacing: "0.5px",
            }}
          >
            TRACKS
          </div>

          {/* Track 1 Label: Video Track */}
          <div
            style={{
              height: "36px",
              display: "flex",
              alignItems: "center",
              gap: "5px",
              fontSize: "11px",
              fontWeight: 600,
              color: "var(--color-text-secondary)",
            }}
          >
            <Film size={12} />
            <span>Video</span>
          </div>

          {/* Track 2 Label: Speech */}
          <div
            style={{
              height: "24px",
              display: "flex",
              alignItems: "center",
              gap: "5px",
              fontSize: "11px",
              fontWeight: 600,
              color: "var(--color-text-secondary)",
            }}
          >
            <Mic size={12} />
            <span>Speech</span>
          </div>

          {/* Track 3 Label: Captions */}
          <div
            style={{
              height: "24px",
              display: "flex",
              alignItems: "center",
              gap: "5px",
              fontSize: "11px",
              fontWeight: 600,
              color: "var(--color-text-secondary)",
            }}
          >
            <MessageSquare size={12} />
            <span>Captions</span>
          </div>

          {/* Track 4 Label: Music */}
          <div
            style={{
              height: "22px",
              display: "flex",
              alignItems: "center",
              gap: "5px",
              fontSize: "11px",
              fontWeight: 600,
              color: "var(--color-text-secondary)",
            }}
          >
            <Music size={12} />
            <span>Music</span>
          </div>
        </div>

        {/* Right Column: Clickable & Draggable Tracks Lane */}
        <div
          ref={tracksLaneRef}
          onMouseDown={handleMouseDown}
          style={{
            flex: 1,
            position: "relative",
            minHeight: "160px",
            display: "flex",
            flexDirection: "column",
            gap: "8px",
            cursor: "crosshair",
          }}
        >
          {/* Visual Time Ruler with dynamic tick intervals */}
          <div
            style={{
              height: "22px",
              position: "relative",
              borderBottom: "1px solid var(--color-border-subtle)",
              fontFamily: "var(--font-mono)",
              fontSize: "10px",
              color: "var(--color-text-muted)",
              overflow: "hidden",
            }}
          >
            {(() => {
              let interval = 5;
              if (safeTotalDuration > 600) interval = 120;
              else if (safeTotalDuration > 300) interval = 60;
              else if (safeTotalDuration > 120) interval = 30;
              else if (safeTotalDuration > 60) interval = 15;
              else if (safeTotalDuration > 20) interval = 5;
              else interval = 2;

              const ticks = [];
              for (let t = 0; t <= safeTotalDuration; t += interval) {
                const leftPct = (t / safeTotalDuration) * 100;
                const mins = Math.floor(t / 60);
                const secs = Math.floor(t % 60);
                const label = `${mins}:${secs < 10 ? "0" : ""}${secs}`;
                ticks.push(
                  <div
                    key={t}
                    style={{
                      position: "absolute",
                      left: `${leftPct}%`,
                      top: 0,
                      bottom: 0,
                      transform: leftPct > 95 ? "translateX(-100%)" : "none",
                      pointerEvents: "none",
                    }}
                  >
                    <span style={{ fontSize: "9px", opacity: 0.7, paddingLeft: "2px" }}>{label}</span>
                    <div
                      style={{
                        position: "absolute",
                        bottom: 0,
                        left: 0,
                        width: "1px",
                        height: "5px",
                        backgroundColor: "var(--color-border)",
                      }}
                    />
                  </div>
                );
              }
              return ticks;
            })()}
          </div>

          {/* Visual In/Out Range Highlight Banner */}
          {inPoint !== null && outPoint !== null && outPoint > inPoint && (
            <div
              style={{
                position: "absolute",
                top: "22px",
                bottom: 0,
                left: `${(inPoint / safeTotalDuration) * 100}%`,
                width: `${((outPoint - inPoint) / safeTotalDuration) * 100}%`,
                backgroundColor: "rgba(239, 68, 68, 0.18)",
                borderLeft: "2px solid #EF4444",
                borderRight: "2px solid #EF4444",
                pointerEvents: "none",
                zIndex: 15,
              }}
            >
              <span
                style={{
                  position: "absolute",
                  top: "2px",
                  left: "4px",
                  fontSize: "10px",
                  fontWeight: 700,
                  color: "#B91C1C",
                  backgroundColor: "rgba(255,255,255,0.9)",
                  padding: "1px 4px",
                  borderRadius: "2px",
                }}
              >
                Cut Range: {(outPoint - inPoint).toFixed(1)}s
              </span>
            </div>
          )}

          {/* Vertical Playhead Needle */}
          <div
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: `${playheadPercent}%`,
              width: "2px",
              backgroundColor: "var(--color-accent-primary)",
              zIndex: 25,
              pointerEvents: "none",
              transform: "translateX(-1px)",
            }}
          >
            {/* Playhead Diamond Handle */}
            <div
              style={{
                position: "absolute",
                top: 0,
                left: "-5px",
                width: "12px",
                height: "12px",
                backgroundColor: "var(--color-accent-primary)",
                clipPath: "polygon(0 0, 100% 0, 100% 50%, 50% 100%, 0 50%)",
                boxShadow: "0 2px 4px rgba(0,0,0,0.4)",
              }}
            />
          </div>

          {/* TRACK 1: Video Track with Clickable / Selectable Clips */}
          <div
            style={{
              height: "36px",
              backgroundColor: "var(--color-surface-inset)",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--color-border)",
              position: "relative",
              overflow: "hidden",
              display: "flex",
            }}
          >
            {segmentsWithOutputTime.map((seg) => {
              const widthPct = (seg.durS / safeTotalDuration) * 100;
              const isSpedUp = (seg.speed_ratio || 1.0) !== 1.0;
              const isSelected = seg.segment_id === selectedSegId;

              return (
                <div
                  key={seg.segment_id}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedSegId(isSelected ? null : seg.segment_id);
                  }}
                  title={`Click to select clip ${seg.segment_id}: ${(seg.source_start_ticks / 1000).toFixed(1)}s - ${(seg.source_end_ticks / 1000).toFixed(1)}s (${seg.speed_ratio}x speed)`}
                  style={{
                    width: `${widthPct}%`,
                    height: "100%",
                    backgroundColor: isSelected
                      ? "var(--color-selected-bg)"
                      : isSpedUp
                      ? "#FEF3C7"
                      : "var(--color-surface-panel)",
                    borderRight: "1px solid var(--color-border)",
                    borderTop: isSelected ? "3px solid var(--color-accent-primary)" : "none",
                    borderBottom: isSelected ? "3px solid var(--color-accent-primary)" : "none",
                    boxShadow: isSelected ? "inset 0 0 0 1px var(--color-accent-primary)" : undefined,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0 8px",
                    fontSize: "11px",
                    color: isSelected
                      ? "var(--color-selected-text)"
                      : isSpedUp
                      ? "#92400E"
                      : "var(--color-text-main)",
                    fontWeight: 600,
                    overflow: "hidden",
                    whiteSpace: "nowrap",
                    cursor: "pointer",
                    transition: "all 0.1s ease",
                  }}
                >
                  <span style={{ textOverflow: "ellipsis", overflow: "hidden" }}>{seg.segment_id}</span>
                  <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    {isSpedUp && (
                      <span
                        style={{
                          fontSize: "10px",
                          backgroundColor: "#FDE68A",
                          color: "#78350F",
                          padding: "1px 4px",
                          borderRadius: "2px",
                        }}
                      >
                        {seg.speed_ratio}x
                      </span>
                    )}
                    <span style={{ fontSize: "10px", opacity: 0.7 }}>{seg.durS.toFixed(1)}s</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* TRACK 2: Speech & Transcript Track */}
          <div
            style={{
              height: "24px",
              backgroundColor: "var(--color-surface-inset)",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--color-border)",
              position: "relative",
              overflow: "hidden",
            }}
          >
            {timeline.transcript?.words?.map((word: TranscriptWord) => {
              const startS = word.start_ticks / 1000;
              const endS = word.end_ticks / 1000;
              const leftPct = (startS / safeTotalDuration) * 100;
              const widthPct = Math.max(0.4, ((endS - startS) / safeTotalDuration) * 100);
              const isGuest = word.speaker === "guest";

              return (
                <div
                  key={word.id}
                  title={`${word.speaker}: "${word.word}" (${startS.toFixed(1)}s - ${endS.toFixed(1)}s)`}
                  style={{
                    position: "absolute",
                    left: `${leftPct}%`,
                    width: `${widthPct}%`,
                    height: "100%",
                    backgroundColor: word.is_filler ? "#FCA5A5" : isGuest ? "#BAE6FD" : "#BBF7D0",
                    borderLeft: "1px solid rgba(0,0,0,0.08)",
                  }}
                />
              );
            })}
          </div>

          {/* TRACK 3: Captions Track with Selection & Editing */}
          <div
            style={{
              height: "24px",
              backgroundColor: "var(--color-surface-inset)",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--color-border)",
              position: "relative",
              overflow: "hidden",
            }}
          >
            {timeline.effects?.captions?.filter((c) => !c.is_suppressed).map((cap: CaptionEffect) => {
              const startS = cap.source_start_ticks / 1000;
              const endS = cap.source_end_ticks / 1000;
              const leftPct = (startS / safeTotalDuration) * 100;
              const widthPct = Math.max(1.2, ((endS - startS) / safeTotalDuration) * 100);
              const isSelected = cap.id === selectedCaptionId;

              return (
                <div
                  key={cap.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedCaptionId(isSelected ? null : cap.id);
                  }}
                  title={`Caption: "${cap.text}" (${startS.toFixed(1)}s - ${endS.toFixed(1)}s) [color: ${cap.color}, size: ${cap.font_size}pt]`}
                  style={{
                    position: "absolute",
                    left: `${leftPct}%`,
                    width: `${widthPct}%`,
                    height: "100%",
                    backgroundColor: isSelected ? "var(--color-accent-hover)" : "var(--color-accent-primary)",
                    outline: isSelected ? "2px solid #FACC15" : "none",
                    borderRadius: "2px",
                    color: "#FFFFFF",
                    fontSize: "10px",
                    fontWeight: 600,
                    padding: "2px 6px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    cursor: "pointer",
                  }}
                >
                  {cap.text}
                </div>
              );
            })}
          </div>

          {/* TRACK 4: Background Music & Ducking Track */}
          <div
            style={{
              height: "22px",
              backgroundColor: "var(--color-surface-inset)",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--color-border)",
              position: "relative",
              overflow: "hidden",
            }}
          >
            {timeline.effects?.music?.map((mus: MusicEffect) => {
              const startS = mus.source_start_ticks / 1000;
              const endS = mus.source_end_ticks / 1000;
              const leftPct = (startS / safeTotalDuration) * 100;
              const widthPct = Math.max(1.0, ((endS - startS) / safeTotalDuration) * 100);

              return (
                <div
                  key={mus.id}
                  title={`Background Music (ducking enabled: ${mus.ducking?.enabled ? "yes" : "no"})`}
                  style={{
                    position: "absolute",
                    left: `${leftPct}%`,
                    width: `${widthPct}%`,
                    height: "100%",
                    backgroundColor: "#DDD6FE",
                    borderRadius: "2px",
                    color: "#5B21B6",
                    fontSize: "9px",
                    fontWeight: 600,
                    padding: "2px 6px",
                  }}
                >
                  Music (auto ducked)
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* 3. Selected Clip Inspector & Manual Controls Bar */}
      {selectedSegment && (
        <div
          style={{
            padding: "8px 14px",
            backgroundColor: "var(--color-surface-inset)",
            borderTop: "1px solid var(--color-border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "10px",
            fontSize: "12px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ fontWeight: 600, color: "var(--color-accent-primary)" }}>
              Clip {selectedSegment.segment_id}:
            </span>
            <span style={{ color: "var(--color-text-secondary)" }}>
              Duration: <strong>{selectedSegment.durS.toFixed(2)}s</strong>
            </span>
            <span style={{ color: "var(--color-text-muted)" }}>
              (Source: {(selectedSegment.source_start_ticks / 1000).toFixed(1)}s - {(selectedSegment.source_end_ticks / 1000).toFixed(1)}s)
            </span>
          </div>

          {/* Speed Ratio Controls */}
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ color: "var(--color-text-muted)", fontSize: "11px", fontWeight: 600 }}>Speed:</span>
            {[0.5, 0.75, 1.0, 1.25, 1.5, 2.0].map((rate) => {
              const isActive = (selectedSegment.speed_ratio || 1.0) === rate;
              return (
                <button
                  key={rate}
                  onClick={() => handleSetSegmentSpeed(selectedSegment, rate)}
                  disabled={isApplyingOp}
                  style={{
                    padding: "2px 7px",
                    fontSize: "11px",
                    fontWeight: 600,
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--color-border)",
                    backgroundColor: isActive ? "var(--color-accent-primary)" : "var(--color-surface-panel)",
                    color: isActive ? "#FFFFFF" : "var(--color-text-main)",
                    cursor: "pointer",
                  }}
                >
                  {rate}x
                </button>
              );
            })}

            <div style={{ width: "1px", height: "16px", backgroundColor: "var(--color-border)", margin: "0 4px" }} />

            {/* Delete Clip Button */}
            <button
              onClick={() => handleDeleteSegment(selectedSegment.segment_id)}
              disabled={isApplyingOp || timeline.segments.length <= 1}
              style={{
                padding: "3px 8px",
                fontSize: "11px",
                fontWeight: 600,
                borderRadius: "var(--radius-sm)",
                border: "1px solid #FCA5A5",
                backgroundColor: "#FEF2F2",
                color: "#B91C1C",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "4px",
              }}
              title="Delete this clip segment"
            >
              <Trash2 size={12} />
              <span>Delete Clip</span>
            </button>
          </div>
        </div>
      )}

      {/* 4. Selected Caption Inspector */}
      {selectedCaption && (
        <div
          style={{
            padding: "8px 14px",
            backgroundColor: "var(--color-surface-inset)",
            borderTop: "1px solid var(--color-border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: "12px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontWeight: 600, color: "var(--color-accent-primary)" }}>Caption:</span>
            <span style={{ color: "var(--color-text-main)", fontStyle: "italic" }}>
              "{selectedCaption.text}"
            </span>
            <span style={{ color: "var(--color-text-muted)", fontSize: "11px" }}>
              ({(selectedCaption.source_start_ticks / 1000).toFixed(1)}s - {(selectedCaption.source_end_ticks / 1000).toFixed(1)}s, {selectedCaption.color}, {selectedCaption.font_size}pt)
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            {/* Make Bigger */}
            <button
              className="btn-secondary"
              onClick={() =>
                onApplyOperation(
                  "edit_caption",
                  { caption_id: selectedCaption.id, font_size_delta: 6 },
                  `Made caption "${selectedCaption.text}" bigger`
                )
              }
              style={{ padding: "2px 7px", fontSize: "11px" }}
            >
              Bigger (+6pt)
            </button>

            {/* Change Color to Yellow */}
            <button
              className="btn-secondary"
              onClick={() =>
                onApplyOperation(
                  "edit_caption",
                  { caption_id: selectedCaption.id, color: "yellow" },
                  `Changed caption "${selectedCaption.text}" to yellow`
                )
              }
              style={{ padding: "2px 7px", fontSize: "11px" }}
            >
              Yellow
            </button>

            {/* Change Color to White */}
            <button
              className="btn-secondary"
              onClick={() =>
                onApplyOperation(
                  "edit_caption",
                  { caption_id: selectedCaption.id, color: "white" },
                  `Changed caption "${selectedCaption.text}" to white`
                )
              }
              style={{ padding: "2px 7px", fontSize: "11px" }}
            >
              White
            </button>

            <button
              className="btn-icon"
              onClick={() => setSelectedCaptionId(null)}
              style={{ width: "22px", height: "22px" }}
            >
              <X size={12} />
            </button>
          </div>
        </div>
      )}

      {/* 5. Add Caption Modal */}
      {isCaptionModalOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={() => setIsCaptionModalOpen(false)}
        >
          <div
            className="panel"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "440px",
              backgroundColor: "var(--color-surface-panel)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-lg)",
              padding: "20px",
              boxShadow: "var(--shadow-lg)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <MessageSquare size={16} style={{ color: "var(--color-accent-primary)" }} />
                <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "var(--color-text-main)" }}>
                  Add Caption Overlay
                </h3>
              </div>
              <button className="btn-icon" onClick={() => setIsCaptionModalOpen(false)}>
                <X size={14} />
              </button>
            </div>

            <form onSubmit={handleSubmitAddCaption} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "4px" }}>
                  Caption Text
                </label>
                <input
                  type="text"
                  value={captionText}
                  onChange={(e) => setCaptionText(e.target.value)}
                  placeholder="e.g. Subscribe for more content!"
                  autoFocus
                  required
                  style={{
                    width: "100%",
                    padding: "8px 12px",
                    borderRadius: "var(--radius-md)",
                    border: "1px solid var(--color-border)",
                    fontSize: "13px",
                    backgroundColor: "var(--color-surface-panel)",
                    color: "var(--color-text-main)",
                    boxSizing: "border-box",
                  }}
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "4px" }}>
                    Start Time (s)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max={safeTotalDuration}
                    value={captionStart}
                    onChange={(e) => setCaptionStart(parseFloat(e.target.value) || 0)}
                    style={{
                      width: "100%",
                      padding: "6px 10px",
                      borderRadius: "var(--radius-md)",
                      border: "1px solid var(--color-border)",
                      fontSize: "13px",
                      boxSizing: "border-box",
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "4px" }}>
                    End Time (s)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max={safeTotalDuration}
                    value={captionEnd}
                    onChange={(e) => setCaptionEnd(parseFloat(e.target.value) || 0)}
                    style={{
                      width: "100%",
                      padding: "6px 10px",
                      borderRadius: "var(--radius-md)",
                      border: "1px solid var(--color-border)",
                      fontSize: "13px",
                      boxSizing: "border-box",
                    }}
                  />
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "4px" }}>
                    Font Color
                  </label>
                  <div style={{ display: "flex", gap: "6px" }}>
                    {[
                      { name: "white", hex: "#FFFFFF" },
                      { name: "yellow", hex: "#FACC15" },
                      { name: "green", hex: "#4ADE80" },
                      { name: "cyan", hex: "#38BDF8" },
                      { name: "red", hex: "#F87171" },
                    ].map((col) => (
                      <button
                        type="button"
                        key={col.name}
                        onClick={() => setCaptionColor(col.name)}
                        style={{
                          width: "24px",
                          height: "24px",
                          borderRadius: "var(--radius-full)",
                          backgroundColor: col.hex,
                          border: captionColor === col.name ? "2px solid var(--color-accent-primary)" : "1px solid #CCC",
                          cursor: "pointer",
                        }}
                      />
                    ))}
                  </div>
                </div>

                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "4px" }}>
                    Font Size
                  </label>
                  <select
                    value={captionFontSize}
                    onChange={(e) => setCaptionFontSize(parseInt(e.target.value))}
                    style={{
                      width: "100%",
                      padding: "6px 10px",
                      borderRadius: "var(--radius-md)",
                      border: "1px solid var(--color-border)",
                      fontSize: "13px",
                      boxSizing: "border-box",
                    }}
                  >
                    <option value={24}>24 pt (Small)</option>
                    <option value={28}>28 pt (Medium)</option>
                    <option value={36}>36 pt (Default)</option>
                    <option value={42}>42 pt (Large)</option>
                  </select>
                </div>
              </div>

              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "4px" }}>
                  Position
                </label>
                <div style={{ display: "flex", gap: "8px" }}>
                  <button
                    type="button"
                    onClick={() => setCaptionPosition("bottom")}
                    className={`btn-secondary ${captionPosition === "bottom" ? "active" : ""}`}
                    style={{
                      flex: 1,
                      backgroundColor: captionPosition === "bottom" ? "var(--color-selected-bg)" : undefined,
                      borderColor: captionPosition === "bottom" ? "var(--color-accent-primary)" : undefined,
                      color: captionPosition === "bottom" ? "var(--color-accent-primary)" : undefined,
                      fontWeight: captionPosition === "bottom" ? 600 : 400,
                    }}
                  >
                    Bottom
                  </button>
                  <button
                    type="button"
                    onClick={() => setCaptionPosition("top")}
                    className={`btn-secondary ${captionPosition === "top" ? "active" : ""}`}
                    style={{
                      flex: 1,
                      backgroundColor: captionPosition === "top" ? "var(--color-selected-bg)" : undefined,
                      borderColor: captionPosition === "top" ? "var(--color-accent-primary)" : undefined,
                      color: captionPosition === "top" ? "var(--color-accent-primary)" : undefined,
                      fontWeight: captionPosition === "top" ? 600 : 400,
                    }}
                  >
                    Top
                  </button>
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "8px" }}>
                <button type="button" className="btn-secondary" onClick={() => setIsCaptionModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={isApplyingOp || !captionText.trim()}>
                  <Plus size={14} />
                  <span>Add Caption</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
