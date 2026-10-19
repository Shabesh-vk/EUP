import React, { useRef, useState, useEffect, useCallback } from "react";
import {
  Play,
  Pause,
  RefreshCw,
  Eye,
  Film,
  Sparkles,
  Volume2,
  VolumeX,
  FastForward,
  Rewind,
  AlertTriangle,
  Maximize2,
  SkipBack,
  SkipForward,
  Scissors,
  CheckCircle2,
} from "lucide-react";
import { Timeline, CaptionEffect } from "../types";

interface VideoPreviewProps {
  timeline: Timeline | null;
  renderedVideoUrl: string | null;
  sourceVideoUrl: string | null;
  currentTime: number;
  onTimeUpdate: (timeSec: number) => void;
  renderedTimelineHash: string | null;
  onReRender: () => void;
  isRendering: boolean;
}

export const VideoPreview: React.FC<VideoPreviewProps> = ({
  timeline,
  renderedVideoUrl,
  sourceVideoUrl,
  currentTime,
  onTimeUpdate,
  renderedTimelineHash,
  onReRender,
  isRendering,
}) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const [viewMode, setViewMode] = useState<"edited" | "source" | "master">("edited");
  const [volume, setVolume] = useState(1.0);
  const [activeSpeedRate, setActiveSpeedRate] = useState(1.0);
  const [cutFlashMessage, setCutFlashMessage] = useState<string | null>(null);
  const [timelineUpdateNotice, setTimelineUpdateNotice] = useState<string | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const currentSegIndexRef = useRef<number>(0);
  const isSeekingRef = useRef<boolean>(false);
  const rafIdRef = useRef<number | null>(null);
  const lastReportedTimeRef = useRef<number>(0);
  const flashTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const noticeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTimelineHashRef = useRef<string | null>(null);

  const segments = timeline?.segments || [];

  // Compute total edited output sequence duration
  const totalEditedDuration = segments.reduce((acc, s) => {
    const durS = (s.source_end_ticks - s.source_start_ticks) / 1000;
    const speed = Math.max(0.1, s.speed_ratio || 1.0);
    return acc + durS / speed;
  }, 0);

  const sourceDuration = timeline?.source_media?.duration_ticks
    ? timeline.source_media.duration_ticks / 1000
    : 0;

  const currentDuration =
    viewMode === "edited"
      ? totalEditedDuration
      : viewMode === "source"
      ? sourceDuration
      : totalEditedDuration || sourceDuration;

  const isMasterOutOfDate =
    viewMode === "master" &&
    renderedTimelineHash !== null &&
    timeline !== null &&
    renderedTimelineHash !== timeline.timeline_hash;

  // Flash cut transition indicator
  const triggerCutFlash = useCallback((msg: string) => {
    if (flashTimeoutRef.current) clearTimeout(flashTimeoutRef.current);
    setCutFlashMessage(msg);
    flashTimeoutRef.current = setTimeout(() => {
      setCutFlashMessage(null);
    }, 1200);
  }, []);

  // Flash timeline edit update notification
  const triggerTimelineNotice = useCallback((msg: string) => {
    if (noticeTimeoutRef.current) clearTimeout(noticeTimeoutRef.current);
    setTimelineUpdateNotice(msg);
    noticeTimeoutRef.current = setTimeout(() => {
      setTimelineUpdateNotice(null);
    }, 2000);
  }, []);

  // Map edited output time (seconds) to source time and segment
  const mapOutputToSource = useCallback(
    (outSec: number) => {
      if (!segments || segments.length === 0) return null;
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
          return { segIndex: i, srcSec, seg, segStartS, segEndS, speed, accumOut };
        }
        accumOut += segDurOut;
      }
      const lastIdx = segments.length - 1;
      const lastSeg = segments[lastIdx];
      const lastStartS = lastSeg.source_start_ticks / 1000;
      const lastEndS = lastSeg.source_end_ticks / 1000;
      const lastSpeed = Math.max(0.1, lastSeg.speed_ratio || 1.0);
      return {
        segIndex: lastIdx,
        srcSec: lastEndS,
        seg: lastSeg,
        segStartS: lastStartS,
        segEndS: lastEndS,
        speed: lastSpeed,
        accumOut: Math.max(0, accumOut - (lastEndS - lastStartS) / lastSpeed),
      };
    },
    [segments]
  );

  // Map source time (seconds) to edited output time
  const mapSourceToOutput = useCallback(
    (srcSec: number, segIdx: number) => {
      if (!segments || segments.length === 0) return null;
      let accumOut = 0;
      for (let i = 0; i < segments.length; i++) {
        const seg = segments[i];
        const segStartS = seg.source_start_ticks / 1000;
        const segEndS = seg.source_end_ticks / 1000;
        const speed = Math.max(0.1, seg.speed_ratio || 1.0);
        const segDurOut = (segEndS - segStartS) / speed;

        if (i === segIdx) {
          const clampedSrc = Math.max(segStartS, Math.min(segEndS, srcSec));
          const deltaSrc = clampedSrc - segStartS;
          return { outSec: accumOut + deltaSrc / speed, segIndex: i };
        }
        accumOut += segDurOut;
      }
      return null;
    },
    [segments]
  );

  // Active source time for captions & audio effects
  const activeMapping = viewMode === "edited" ? mapOutputToSource(currentTime) : null;
  const activeSourceTime = activeMapping ? activeMapping.srcSec : currentTime;

  // Active caption lookup for overlay preview
  const activeCaption = timeline?.effects?.captions?.find((c: CaptionEffect) => {
    if (c.is_suppressed) return false;
    const startS = c.source_start_ticks / 1000;
    const endS = c.source_end_ticks / 1000;
    // Check if activeSourceTime falls within the caption's source range
    if (activeSourceTime >= startS && activeSourceTime <= endS) {
      return true;
    }
    // Fallback: check against output time directly if defined in output domain
    if (currentTime >= startS && currentTime <= endS) {
      return true;
    }
    return false;
  });

  // Check whether current active source frame is in a mute or bleep zone
  const isCurrentFrameMuted = Boolean(
    timeline?.effects?.mutes?.some(
      (m) => activeSourceTime >= m.source_start_ticks / 1000 && activeSourceTime <= m.source_end_ticks / 1000
    )
  );

  const isCurrentFrameBleeped = Boolean(
    timeline?.effects?.bleeps?.some(
      (b) => activeSourceTime >= b.source_start_ticks / 1000 && activeSourceTime <= b.source_end_ticks / 1000
    )
  );

  const hasMusicActive = Boolean(timeline?.effects?.music && timeline.effects.music.length > 0);

  // 1. Reactive Sync: Handle Dashboard Edit Changes and Synchronize Video
  useEffect(() => {
    const vid = videoRef.current;
    if (!vid) return;

    // Detect if timeline hash changed (e.g. from an edit action in dashboard)
    if (timeline?.timeline_hash && timeline.timeline_hash !== lastTimelineHashRef.current) {
      const isInitial = lastTimelineHashRef.current === null;
      lastTimelineHashRef.current = timeline.timeline_hash;
      if (!isInitial) {
        triggerTimelineNotice(`Edit live reflected (${timeline.timeline_hash.substring(0, 7)})`);
      }
    }

    if (viewMode === "edited") {
      if (segments.length === 0) return;

      // Clamp currentTime within new total duration
      const safeTime = Math.max(0, Math.min(totalEditedDuration, currentTime));
      if (safeTime !== currentTime) {
        onTimeUpdate(safeTime);
      }

      const mapping = mapOutputToSource(safeTime);
      if (mapping) {
        currentSegIndexRef.current = mapping.segIndex;

        // When paused or during seek re-position, position video element
        if (!isPlaying && !isSeekingRef.current) {
          if (Math.abs(vid.currentTime - mapping.srcSec) > 0.04) {
            vid.currentTime = mapping.srcSec;
          }
        }

        // Apply segment speed
        if (Math.abs(vid.playbackRate - mapping.speed) > 0.02) {
          vid.playbackRate = mapping.speed;
          vid.defaultPlaybackRate = mapping.speed;
          setActiveSpeedRate(mapping.speed);
        }
      }
    } else {
      if (!isPlaying && Math.abs(vid.currentTime - currentTime) > 0.04) {
        vid.currentTime = currentTime;
      }
    }
  }, [
    currentTime,
    timeline,
    viewMode,
    segments,
    isPlaying,
    totalEditedDuration,
    mapOutputToSource,
    onTimeUpdate,
    triggerTimelineNotice,
  ]);

  // 2. High-Precision Virtual Playback Tick (Real-Time Live Multi-Clip Playback Engine)
  useEffect(() => {
    if (viewMode !== "edited" || !isPlaying || !videoRef.current || segments.length === 0) {
      if (rafIdRef.current) cancelAnimationFrame(rafIdRef.current);
      return;
    }

    const checkPlayback = () => {
      const vid = videoRef.current;
      if (!vid || vid.paused) return;

      // If the browser is in the middle of a seek, do NOT trigger boundary logic
      if (vid.seeking || isSeekingRef.current) {
        rafIdRef.current = requestAnimationFrame(checkPlayback);
        return;
      }

      const curSrc = vid.currentTime;
      let curIdx = currentSegIndexRef.current;
      if (curIdx < 0) curIdx = 0;
      if (curIdx >= segments.length) curIdx = segments.length - 1;
      const curSeg = segments[curIdx];

      const segStartS = curSeg.source_start_ticks / 1000;
      const segEndS = curSeg.source_end_ticks / 1000;
      const curSpeed = Math.max(0.1, curSeg.speed_ratio || 1.0);

      // Ensure playback rate matches current segment's speed ratio
      if (Math.abs(vid.playbackRate - curSpeed) > 0.02) {
        vid.playbackRate = curSpeed;
        vid.defaultPlaybackRate = curSpeed;
        setActiveSpeedRate(curSpeed);
      }

      // Check if current segment reached its end
      if (curSrc >= segEndS - 0.05) {
        if (curIdx + 1 < segments.length) {
          // Immediately leap forward past the cut into the next segment!
          const nextIdx = curIdx + 1;
          const nextSeg = segments[nextIdx];
          currentSegIndexRef.current = nextIdx;
          isSeekingRef.current = true;
          vid.currentTime = nextSeg.source_start_ticks / 1000;
          const nextSpeed = Math.max(0.1, nextSeg.speed_ratio || 1.0);
          vid.playbackRate = nextSpeed;
          setActiveSpeedRate(nextSpeed);
          triggerCutFlash(`Cut Leaped ✂️ (Clip ${nextIdx + 1}/${segments.length})`);
        } else {
          // Reached end of all edited clips
          vid.pause();
          setIsPlaying(false);
          onTimeUpdate(totalEditedDuration);
          return;
        }
      } else if (curSrc < segStartS - 0.1) {
        // Video drifted before segment start, snap back
        isSeekingRef.current = true;
        vid.currentTime = segStartS;
      } else {
        // Within current segment: sync output time to dashboard playhead
        const mapping = mapSourceToOutput(curSrc, curIdx);
        if (mapping) {
          if (Math.abs(mapping.outSec - lastReportedTimeRef.current) >= 0.02) {
            lastReportedTimeRef.current = mapping.outSec;
            onTimeUpdate(mapping.outSec);
          }
        }
      }

      // Live Audio Effects Handling (Mute & Bleep)
      const frameMuted = Boolean(
        timeline?.effects?.mutes?.some(
          (m) => curSrc >= m.source_start_ticks / 1000 && curSrc <= m.source_end_ticks / 1000
        )
      );

      const frameBleeped = Boolean(
        timeline?.effects?.bleeps?.some(
          (b) => curSrc >= b.source_start_ticks / 1000 && curSrc <= b.source_end_ticks / 1000
        )
      );

      const effectiveMute = frameMuted || frameBleeped || volume === 0;
      if (vid.muted !== effectiveMute) {
        vid.muted = effectiveMute;
      }

      rafIdRef.current = requestAnimationFrame(checkPlayback);
    };

    rafIdRef.current = requestAnimationFrame(checkPlayback);

    return () => {
      if (rafIdRef.current) cancelAnimationFrame(rafIdRef.current);
    };
  }, [
    isPlaying,
    viewMode,
    segments,
    timeline,
    volume,
    totalEditedDuration,
    mapSourceToOutput,
    onTimeUpdate,
    triggerCutFlash,
  ]);

  // Spacebar and Arrow Key Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;

      if (e.code === "Space") {
        e.preventDefault();
        togglePlay();
      } else if (e.code === "ArrowLeft") {
        e.preventDefault();
        handleStep(-1.0);
      } else if (e.code === "ArrowRight") {
        e.preventDefault();
        handleStep(1.0);
      } else if (e.key === "j" || e.key === "J") {
        e.preventDefault();
        handleStep(-3.0);
      } else if (e.key === "k" || e.key === "K") {
        e.preventDefault();
        togglePlay();
      } else if (e.key === "l" || e.key === "L") {
        e.preventDefault();
        handleStep(3.0);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isPlaying, currentTime, viewMode, totalEditedDuration]);

  // Toggle Play / Pause
  const togglePlay = () => {
    const vid = videoRef.current;
    if (!vid) return;

    if (isPlaying) {
      vid.pause();
      setIsPlaying(false);
    } else {
      if (viewMode === "edited" && segments.length > 0) {
        // If at or near end, loop back from beginning
        const activeTime = currentTime >= totalEditedDuration - 0.1 ? 0 : currentTime;
        const mapping = mapOutputToSource(activeTime);
        if (mapping) {
          currentSegIndexRef.current = mapping.segIndex;
          isSeekingRef.current = true;
          vid.currentTime = mapping.srcSec;
          vid.playbackRate = mapping.speed;
          setActiveSpeedRate(mapping.speed);
        }
      }
      vid
        .play()
        .then(() => setIsPlaying(true))
        .catch((err) => {
          console.warn("Play interrupted or blocked:", err);
          setIsPlaying(false);
        });
    }
  };

  // Seeking on Scrubber or Step
  const handleSeek = (newTime: number) => {
    const clampedTime = Math.max(0, Math.min(currentDuration || 1, newTime));
    onTimeUpdate(clampedTime);
    lastReportedTimeRef.current = clampedTime;

    const vid = videoRef.current;
    if (!vid) return;

    if (viewMode === "edited") {
      const mapping = mapOutputToSource(clampedTime);
      if (mapping) {
        currentSegIndexRef.current = mapping.segIndex;
        isSeekingRef.current = true;
        vid.currentTime = mapping.srcSec;
        vid.playbackRate = mapping.speed;
        setActiveSpeedRate(mapping.speed);
      }
    } else {
      vid.currentTime = clampedTime;
    }
  };

  const handleStep = (deltaSec: number) => {
    handleSeek(currentTime + deltaSec);
  };

  // Jump to Next / Previous Clip
  const handleJumpClip = (direction: "next" | "prev") => {
    if (!segments || segments.length === 0) return;
    let accumOut = 0;
    const curIdx = currentSegIndexRef.current;

    if (direction === "next") {
      if (curIdx + 1 < segments.length) {
        for (let i = 0; i <= curIdx; i++) {
          const s = segments[i];
          const durS = (s.source_end_ticks - s.source_start_ticks) / 1000 / (s.speed_ratio || 1.0);
          accumOut += durS;
        }
        handleSeek(accumOut + 0.05);
      }
    } else {
      if (curIdx > 0) {
        for (let i = 0; i < curIdx - 1; i++) {
          const s = segments[i];
          const durS = (s.source_end_ticks - s.source_start_ticks) / 1000 / (s.speed_ratio || 1.0);
          accumOut += durS;
        }
        handleSeek(accumOut);
      } else {
        handleSeek(0);
      }
    }
  };

  // Toggle Fullscreen
  const handleToggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  };

  const formatClock = (seconds: number) => {
    if (!seconds || isNaN(seconds)) return "0:00.0";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 10);
    return `${mins}:${secs.toString().padStart(2, "0")}.${ms}`;
  };

  // Determine media URL based on viewMode
  let currentMediaUrl = sourceVideoUrl;
  if (viewMode === "master") {
    currentMediaUrl = renderedVideoUrl || sourceVideoUrl;
  } else {
    currentMediaUrl = sourceVideoUrl;
  }

  // Force video element to reload immediately when currentMediaUrl changes
  useEffect(() => {
    const vid = videoRef.current;
    if (vid) {
      vid.load();
      isSeekingRef.current = false;
      setIsPlaying(false);
    }
  }, [currentMediaUrl]);

  return (
    <div
      ref={containerRef}
      className="panel"
      style={{
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        border: "1px solid var(--color-border-gloss)",
        boxShadow: "0 16px 36px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.15)",
        backgroundColor: "rgba(10, 14, 24, 0.95)",
        position: "relative",
      }}
    >
      {/* 1. View Mode Bar & Real-Time Sync Indicator */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 14px",
          backgroundColor: "rgba(12, 17, 28, 0.85)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          borderBottom: "1px solid var(--color-border)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <button
            onClick={() => {
              setViewMode("edited");
              const mapping = mapOutputToSource(currentTime);
              if (mapping && videoRef.current) {
                videoRef.current.currentTime = mapping.srcSec;
                videoRef.current.playbackRate = mapping.speed;
                setActiveSpeedRate(mapping.speed);
              }
            }}
            className={`chip ${viewMode === "edited" ? "active" : ""}`}
            title="Real-time multi-clip zero-render preview: plays cuts, speed changes, and captions instantly live"
          >
            <Sparkles size={12} style={{ color: viewMode === "edited" ? "#34D399" : "var(--color-accent-primary)" }} />
            <span>Edited Preview (Live)</span>
          </button>

          <button
            onClick={() => {
              setViewMode("source");
              if (videoRef.current) {
                videoRef.current.playbackRate = 1.0;
                setActiveSpeedRate(1.0);
              }
            }}
            className={`chip ${viewMode === "source" ? "active" : ""}`}
            title="Inspect raw unedited camera source file"
          >
            <Eye size={12} />
            <span>Raw Source</span>
          </button>

          {renderedVideoUrl && (
            <button
              onClick={() => {
                setViewMode("master");
                if (videoRef.current) {
                  videoRef.current.playbackRate = 1.0;
                  setActiveSpeedRate(1.0);
                }
              }}
              className={`chip ${viewMode === "master" ? "active" : ""}`}
              title="Watch rendered MP4 export"
            >
              <Film size={12} />
              <span>Master MP4</span>
            </button>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "11.5px" }}>
          {viewMode === "edited" && (
            <span
              style={{
                backgroundColor: "rgba(16, 185, 129, 0.15)",
                color: "#34D399",
                border: "1px solid rgba(16, 185, 129, 0.3)",
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: "var(--radius-full)",
                fontSize: "10.5px",
                display: "flex",
                alignItems: "center",
                gap: "4px",
                boxShadow: "0 0 10px rgba(16, 185, 129, 0.2)",
              }}
            >
              <Sparkles size={10} /> Live Zero-Render
            </span>
          )}

          <span style={{ color: "var(--color-text-muted)" }}>
            Clips: <strong style={{ color: "var(--color-text-main)" }}>{segments.length}</strong>
          </span>

          <span style={{ color: "var(--color-text-muted)" }}>
            Rev:{" "}
            <code className="mono" style={{ color: "#34D399", fontWeight: 600 }}>
              {timeline?.timeline_hash?.substring(0, 7) || "init"}
            </code>
          </span>
        </div>
      </div>

      {/* 2. Out of Date Master Banner */}
      {isMasterOutOfDate && (
        <div
          style={{
            backgroundColor: "rgba(245, 158, 11, 0.15)",
            color: "#F59E0B",
            padding: "6px 14px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: "12px",
            fontWeight: 500,
            borderBottom: "1px solid rgba(245, 158, 11, 0.25)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <AlertTriangle size={14} />
            <span>Master render is outdated due to recent edits. Preview is running live in Zero-Render mode.</span>
          </div>
          <button
            className="btn-primary"
            onClick={onReRender}
            disabled={isRendering}
            style={{ padding: "3px 9px", fontSize: "11px" }}
          >
            {isRendering ? <RefreshCw size={11} className="spin" /> : <RefreshCw size={11} />}
            <span>Update Master</span>
          </button>
        </div>
      )}

      {/* 3. Dark Canvas Video Player */}
      <div
        style={{
          position: "relative",
          width: "100%",
          height: "380px",
          backgroundColor: "#030712",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow: "inset 0 0 40px rgba(0, 0, 0, 0.8)",
          overflow: "hidden",
        }}
      >
        {currentMediaUrl ? (
          <>
            <video
              key={currentMediaUrl || "empty"}
              ref={videoRef}
              src={currentMediaUrl}
              style={{ width: "100%", height: "100%", objectFit: "contain", cursor: "pointer" }}
              onClick={togglePlay}
              onPlay={() => setIsPlaying(true)}
              onPause={() => setIsPlaying(false)}
              onEnded={() => {
                setIsPlaying(false);
                onTimeUpdate(currentDuration);
              }}
              onSeeked={() => {
                isSeekingRef.current = false;
              }}
              onLoadedMetadata={() => {
                isSeekingRef.current = false;
                if (viewMode === "edited" && segments.length > 0) {
                  const mapping = mapOutputToSource(currentTime);
                  if (mapping && videoRef.current) {
                    videoRef.current.currentTime = mapping.srcSec;
                    videoRef.current.playbackRate = mapping.speed;
                    setActiveSpeedRate(mapping.speed);
                  }
                }
              }}
              onTimeUpdate={(e) => {
                if (viewMode === "source" || viewMode === "master") {
                  onTimeUpdate(e.currentTarget.currentTime);
                }
              }}
            />

            {/* Play Button Overlay when Paused */}
            {!isPlaying && (
              <div
                onClick={togglePlay}
                title="Click to Play (Space)"
                style={{
                  position: "absolute",
                  width: "60px",
                  height: "60px",
                  borderRadius: "50%",
                  background: "rgba(16, 185, 129, 0.9)",
                  backdropFilter: "blur(10px)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#FFFFFF",
                  cursor: "pointer",
                  boxShadow: "0 0 28px rgba(16, 185, 129, 0.6), inset 0 1px 1px rgba(255, 255, 255, 0.4)",
                  transition: "transform 0.18s ease",
                  zIndex: 10,
                }}
                onMouseEnter={(e) => (e.currentTarget.style.transform = "scale(1.08)")}
                onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1.0)")}
              >
                <Play size={28} style={{ marginLeft: "3px" }} />
              </div>
            )}
          </>
        ) : (
          <div style={{ textAlign: "center", color: "var(--color-text-muted)" }}>
            <Film size={40} style={{ opacity: 0.3, marginBottom: "10px" }} />
            <div style={{ fontSize: "14px", fontWeight: 700, color: "var(--color-text-main)" }}>
              No Media Loaded
            </div>
            <div style={{ fontSize: "12px", opacity: 0.8, marginTop: "4px" }}>
              Select a video from the Media Library on the left to start editing.
            </div>
          </div>
        )}

        {/* 4. Real-Time Live Subtitle / Caption Overlay */}
        {activeCaption && (
          <div
            style={{
              position: "absolute",
              bottom: activeCaption.position === "bottom" ? "32px" : activeCaption.position === "center" ? "45%" : undefined,
              top: activeCaption.position === "top" ? "32px" : undefined,
              left: "50%",
              transform: activeCaption.position === "center" ? "translate(-50%, -50%)" : "translateX(-50%)",
              color: activeCaption.color || "#FFFFFF",
              fontSize: `${Math.max(18, Math.min(44, activeCaption.font_size || 32))}px`,
              fontWeight: 800,
              textShadow: "0 2px 10px rgba(0,0,0,0.95), 0 0 4px #000000, 0 1px 2px #000000",
              textAlign: "center",
              padding: "6px 20px",
              backgroundColor: "rgba(0, 0, 0, 0.65)",
              backdropFilter: "blur(8px)",
              borderRadius: "var(--radius-md)",
              pointerEvents: "none",
              maxWidth: "85%",
              letterSpacing: "0.5px",
              lineHeight: 1.3,
              border: "1px solid rgba(255, 255, 255, 0.15)",
              zIndex: 20,
              boxShadow: "0 8px 24px rgba(0, 0, 0, 0.6)",
            }}
          >
            {activeCaption.text}
          </div>
        )}

        {/* 5. Live Cut Leap Toast Indicator */}
        {cutFlashMessage && (
          <div
            style={{
              position: "absolute",
              top: "16px",
              left: "50%",
              transform: "translateX(-50%)",
              backgroundColor: "rgba(16, 185, 129, 0.9)",
              color: "#FFFFFF",
              fontSize: "12px",
              fontWeight: 700,
              padding: "5px 14px",
              borderRadius: "var(--radius-full)",
              display: "flex",
              alignItems: "center",
              gap: "6px",
              backdropFilter: "blur(10px)",
              boxShadow: "0 0 20px rgba(16, 185, 129, 0.5)",
              zIndex: 30,
              animation: "fadeIn 0.15s ease",
            }}
          >
            <Scissors size={13} />
            <span>{cutFlashMessage}</span>
          </div>
        )}

        {/* 6. Dashboard Edit Reflected Notification */}
        {timelineUpdateNotice && (
          <div
            style={{
              position: "absolute",
              bottom: "16px",
              left: "16px",
              backgroundColor: "rgba(10, 15, 28, 0.9)",
              color: "#34D399",
              fontSize: "11px",
              fontWeight: 600,
              padding: "4px 10px",
              borderRadius: "var(--radius-sm)",
              display: "flex",
              alignItems: "center",
              gap: "5px",
              border: "1px solid rgba(16, 185, 129, 0.4)",
              backdropFilter: "blur(8px)",
              zIndex: 30,
            }}
          >
            <CheckCircle2 size={12} />
            <span>{timelineUpdateNotice}</span>
          </div>
        )}

        {/* 7. Active Playback Status Badges (Top-Right HUD) */}
        <div
          style={{
            position: "absolute",
            top: "12px",
            right: "12px",
            display: "flex",
            alignItems: "center",
            gap: "6px",
            pointerEvents: "none",
            zIndex: 25,
          }}
        >
          {activeSpeedRate !== 1.0 && viewMode === "edited" && (
            <span
              style={{
                backgroundColor: "rgba(10, 15, 25, 0.9)",
                color: "#FACC15",
                fontSize: "11px",
                fontWeight: 700,
                padding: "3px 9px",
                borderRadius: "var(--radius-sm)",
                display: "flex",
                alignItems: "center",
                gap: "4px",
                border: "1px solid rgba(250, 204, 21, 0.5)",
                backdropFilter: "blur(8px)",
                boxShadow: "0 0 12px rgba(250, 204, 21, 0.25)",
              }}
            >
              <FastForward size={12} /> {activeSpeedRate}x Speed
            </span>
          )}

          {isCurrentFrameMuted && viewMode === "edited" && (
            <span
              style={{
                backgroundColor: "rgba(244, 63, 94, 0.92)",
                color: "#FFFFFF",
                fontSize: "11px",
                fontWeight: 700,
                padding: "3px 9px",
                borderRadius: "var(--radius-sm)",
                display: "flex",
                alignItems: "center",
                gap: "4px",
                backdropFilter: "blur(8px)",
                boxShadow: "0 0 14px rgba(244, 63, 94, 0.45)",
              }}
            >
              <VolumeX size={12} /> Live Muted
            </span>
          )}

          {isCurrentFrameBleeped && viewMode === "edited" && (
            <span
              style={{
                backgroundColor: "rgba(249, 115, 22, 0.92)",
                color: "#FFFFFF",
                fontSize: "11px",
                fontWeight: 700,
                padding: "3px 9px",
                borderRadius: "var(--radius-sm)",
                display: "flex",
                alignItems: "center",
                gap: "4px",
                backdropFilter: "blur(8px)",
                boxShadow: "0 0 14px rgba(249, 115, 22, 0.45)",
              }}
            >
              ⚠️ Bleeped
            </span>
          )}

          {hasMusicActive && viewMode === "edited" && (
            <span
              style={{
                backgroundColor: "rgba(139, 92, 246, 0.9)",
                color: "#FFFFFF",
                fontSize: "11px",
                fontWeight: 600,
                padding: "3px 9px",
                borderRadius: "var(--radius-sm)",
                display: "flex",
                alignItems: "center",
                gap: "4px",
                backdropFilter: "blur(8px)",
              }}
            >
              🎵 BG Music
            </span>
          )}
        </div>
      </div>

      {/* 8. Glossy Transport Controls Bar */}
      <div
        style={{
          padding: "10px 16px",
          display: "flex",
          alignItems: "center",
          gap: "10px",
          backgroundColor: "rgba(12, 17, 28, 0.92)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          borderTop: "1px solid var(--color-border)",
        }}
      >
        {/* Previous Clip Jump */}
        <button
          onClick={() => handleJumpClip("prev")}
          className="btn-icon"
          title="Jump to previous clip boundary"
          style={{ width: "28px", height: "28px" }}
        >
          <SkipBack size={13} />
        </button>

        {/* Step -1s */}
        <button
          onClick={() => handleStep(-1.0)}
          className="btn-icon"
          title="Step back 1 second (Left Arrow)"
          style={{ width: "28px", height: "28px" }}
        >
          <Rewind size={13} />
        </button>

        {/* Primary Play / Pause */}
        <button
          onClick={togglePlay}
          className="btn-primary"
          title={isPlaying ? "Pause (Space)" : "Play (Space)"}
          style={{
            width: "34px",
            height: "34px",
            borderRadius: "var(--radius-full)",
            padding: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {isPlaying ? <Pause size={16} /> : <Play size={16} style={{ marginLeft: "2px" }} />}
        </button>

        {/* Step +1s */}
        <button
          onClick={() => handleStep(1.0)}
          className="btn-icon"
          title="Step forward 1 second (Right Arrow)"
          style={{ width: "28px", height: "28px" }}
        >
          <FastForward size={13} />
        </button>

        {/* Next Clip Jump */}
        <button
          onClick={() => handleJumpClip("next")}
          className="btn-icon"
          title="Jump to next clip boundary"
          style={{ width: "28px", height: "28px" }}
        >
          <SkipForward size={13} />
        </button>

        {/* Volume Mute/Unmute */}
        <button
          onClick={() => {
            if (!videoRef.current) return;
            const nextVol = volume === 0 ? 1 : 0;
            videoRef.current.volume = nextVol;
            setVolume(nextVol);
          }}
          className="btn-icon"
          title={volume === 0 ? "Unmute" : "Mute"}
          style={{ width: "28px", height: "28px" }}
        >
          {volume === 0 ? <VolumeX size={13} /> : <Volume2 size={13} />}
        </button>

        {/* Current Timecode Display */}
        <div
          style={{
            backgroundColor: "rgba(0, 0, 0, 0.5)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-xs)",
            padding: "3px 8px",
          }}
        >
          <span
            className="mono"
            style={{
              fontSize: "12px",
              color: "#34D399",
              fontWeight: 700,
            }}
          >
            {formatClock(currentTime)}
          </span>
        </div>

        {/* High-Precision Scrubber Range Slider */}
        <input
          type="range"
          min={0}
          max={currentDuration || 1}
          step={0.02}
          value={Math.min(currentDuration || 1, Math.max(0, currentTime))}
          onChange={(e) => handleSeek(parseFloat(e.target.value))}
          style={{
            flex: 1,
            accentColor: "#10B981",
            cursor: "pointer",
            height: "5px",
            borderRadius: "9999px",
          }}
        />

        {/* Total Duration Display */}
        <span
          className="mono"
          style={{
            fontSize: "11.5px",
            color: "var(--color-text-muted)",
            minWidth: "55px",
            textAlign: "right",
          }}
        >
          {formatClock(currentDuration)}
        </span>

        {/* Fullscreen Button */}
        <button
          onClick={handleToggleFullscreen}
          className="btn-icon"
          title="Toggle Fullscreen"
          style={{ width: "28px", height: "28px" }}
        >
          <Maximize2 size={13} />
        </button>
      </div>
    </div>
  );
};
