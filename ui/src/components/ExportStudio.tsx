import React, { useState } from "react";
import {
  Download,
  Film,
  Sparkles,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  FileCode,
  Settings,
  HardDrive,
  ArrowLeft,
} from "lucide-react";
import { Timeline } from "../types";

interface ExportStudioProps {
  projectId: string;
  timeline: Timeline | null;
  renderedVideoUrl: string | null;
  renderedTimelineHash: string | null;
  isRendering: boolean;
  onRenderMaster: (resolution: string, preset: string, burnSubtitles: boolean) => Promise<void>;
  onExportOtio: () => void;
  onBackToEditor: () => void;
}

export const ExportStudio: React.FC<ExportStudioProps> = ({
  projectId,
  timeline,
  renderedVideoUrl,
  renderedTimelineHash,
  isRendering,
  onRenderMaster,
  onExportOtio,
  onBackToEditor,
}) => {
  const [resolution, setResolution] = useState<string>("1280x720");
  const [preset, setPreset] = useState<string>("hq");
  const [burnSubtitles, setBurnSubtitles] = useState<boolean>(true);
  const [renderProgress, setRenderProgress] = useState<number>(0);

  const totalDuration = timeline
    ? timeline.segments.reduce(
        (acc, s) => acc + (s.source_end_ticks - s.source_start_ticks) / 1000 / (s.speed_ratio || 1.0),
        0
      )
    : 0;

  const isHashMatching =
    renderedVideoUrl !== null &&
    renderedTimelineHash !== null &&
    timeline !== null &&
    renderedTimelineHash === timeline.timeline_hash;

  const handleStartRender = async () => {
    setRenderProgress(10);
    const interval = setInterval(() => {
      setRenderProgress((p) => {
        if (p >= 90) {
          clearInterval(interval);
          return 90;
        }
        return p + 15;
      });
    }, 600);

    try {
      await onRenderMaster(resolution, preset, burnSubtitles);
      setRenderProgress(100);
    } catch {
      setRenderProgress(0);
    } finally {
      clearInterval(interval);
    }
  };

  const formatClock = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}m ${secs.toString().padStart(2, "0")}s`;
  };

  return (
    <div
      style={{
        maxWidth: "1280px",
        margin: "0 auto",
        padding: "24px 20px",
        width: "100%",
        boxSizing: "border-box",
        display: "flex",
        flexDirection: "column",
        gap: "24px",
      }}
    >
      {/* 1. Header & Back Navigation */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "12px",
        }}
      >
        <div>
          <button
            className="btn-secondary"
            onClick={onBackToEditor}
            style={{ marginBottom: "8px", padding: "5px 10px", fontSize: "12px" }}
          >
            <ArrowLeft size={13} />
            <span>Back to Editor Workspace</span>
          </button>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <h1 style={{ fontSize: "24px", fontWeight: 700, margin: 0, color: "var(--color-text-main)" }}>
              Export & Delivery Studio
            </h1>
            <span
              style={{
                fontSize: "12px",
                fontWeight: 600,
                backgroundColor: "var(--color-selected-bg)",
                color: "var(--color-selected-text)",
                padding: "3px 8px",
                borderRadius: "var(--radius-sm)",
              }}
            >
              Master Deliverables
            </span>
          </div>
          <p style={{ margin: "4px 0 0 0", color: "var(--color-text-muted)", fontSize: "14px" }}>
            Render production-grade MP4 video deliverables with burned captions, speed changes, and audio ducking, or export OpenTimelineIO interchange files.
          </p>
        </div>

        {/* Timeline Status Card */}
        <div
          style={{
            backgroundColor: "var(--color-surface-panel)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-md)",
            padding: "10px 16px",
            display: "flex",
            alignItems: "center",
            gap: "16px",
            fontSize: "12px",
          }}
        >
          <div>
            <div style={{ color: "var(--color-text-muted)" }}>Timeline Revision</div>
            <div style={{ fontWeight: 600, fontFamily: "var(--font-mono)", color: "var(--color-text-main)" }}>
              {timeline?.timeline_hash?.substring(0, 8) || "initial"}
            </div>
          </div>
          <div style={{ width: "1px", height: "24px", backgroundColor: "var(--color-border)" }} />
          <div>
            <div style={{ color: "var(--color-text-muted)" }}>Total Runtime</div>
            <div style={{ fontWeight: 600, color: "var(--color-text-main)" }}>{formatClock(totalDuration)}</div>
          </div>
          <div style={{ width: "1px", height: "24px", backgroundColor: "var(--color-border)" }} />
          <div>
            <div style={{ color: "var(--color-text-muted)" }}>Clips / Captions</div>
            <div style={{ fontWeight: 600, color: "var(--color-text-main)" }}>
              {timeline?.segments?.length || 0} clips / {timeline?.effects?.captions?.length || 0} caps
            </div>
          </div>
        </div>
      </div>

      {/* 2. Main 2-Column Grid: Left Render Config & Progress, Right Delivery / Preview */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.1fr 1fr",
          gap: "24px",
        }}
      >
        {/* LEFT COLUMN: Master Render Configuration */}
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          <div
            className="panel"
            style={{
              padding: "20px",
              backgroundColor: "var(--color-surface-panel)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-lg)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px" }}>
              <Settings size={18} style={{ color: "var(--color-accent-primary)" }} />
              <h2 style={{ fontSize: "16px", fontWeight: 700, margin: 0, color: "var(--color-text-main)" }}>
                Master Video Encoding Settings
              </h2>
            </div>

            {/* Resolution Selector */}
            <div style={{ marginBottom: "16px" }}>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "8px" }}>
                Output Resolution
              </label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px" }}>
                {[
                  { id: "1920x1080", label: "1080p FHD", desc: "1920x1080 Full HD" },
                  { id: "1280x720", label: "720p HD", desc: "1280x720 Balanced" },
                  { id: "854x480", label: "480p SD", desc: "854x480 Fast Draft" },
                ].map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setResolution(item.id)}
                    style={{
                      padding: "10px",
                      borderRadius: "var(--radius-md)",
                      border: resolution === item.id ? "2px solid var(--color-accent-primary)" : "1px solid var(--color-border)",
                      backgroundColor: resolution === item.id ? "var(--color-selected-bg)" : "var(--color-surface-panel)",
                      color: resolution === item.id ? "var(--color-selected-text)" : "var(--color-text-main)",
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    <div style={{ fontWeight: 700, fontSize: "13px" }}>{item.label}</div>
                    <div style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "2px" }}>
                      {item.desc}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Quality Preset */}
            <div style={{ marginBottom: "16px" }}>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "8px" }}>
                Encoding Quality Preset
              </label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                {[
                  { id: "hq", label: "High Quality Master", desc: "CRF 18 • High Bitrate • Broadcast Ready" },
                  { id: "preview", label: "Fast Draft", desc: "CRF 24 • Fast Encode • Quick Review" },
                ].map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setPreset(item.id)}
                    style={{
                      padding: "10px",
                      borderRadius: "var(--radius-md)",
                      border: preset === item.id ? "2px solid var(--color-accent-primary)" : "1px solid var(--color-border)",
                      backgroundColor: preset === item.id ? "var(--color-selected-bg)" : "var(--color-surface-panel)",
                      color: preset === item.id ? "var(--color-selected-text)" : "var(--color-text-main)",
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    <div style={{ fontWeight: 700, fontSize: "13px" }}>{item.label}</div>
                    <div style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "2px" }}>
                      {item.desc}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Feature Options */}
            <div style={{ marginBottom: "20px" }}>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "8px" }}>
                Output Processing Options
              </label>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", color: "var(--color-text-main)", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={burnSubtitles}
                    onChange={(e) => setBurnSubtitles(e.target.checked)}
                    style={{ accentColor: "var(--color-accent-primary)" }}
                  />
                  <span>Burn formatted ASS Subtitles (custom colors, sizes, and positions)</span>
                </label>

                <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", color: "var(--color-text-main)", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={true}
                    readOnly
                    style={{ accentColor: "var(--color-accent-primary)" }}
                  />
                  <span>Automatic Speech Audio Ducking on Background Music (Dynamic Sidechain)</span>
                </label>
              </div>
            </div>

            {/* Render Button */}
            <button
              className="btn-primary"
              onClick={handleStartRender}
              disabled={isRendering}
              style={{
                width: "100%",
                padding: "12px",
                fontSize: "14px",
                fontWeight: 700,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
              }}
            >
              {isRendering ? (
                <>
                  <RefreshCw size={16} className="spin" />
                  <span>Encoding Master Video ({resolution})...</span>
                </>
              ) : (
                <>
                  <Sparkles size={16} />
                  <span>Render & Export Master Video</span>
                </>
              )}
            </button>

            {/* Live Render Progress */}
            {isRendering && (
              <div style={{ marginTop: "16px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", marginBottom: "6px" }}>
                  <span style={{ color: "var(--color-text-secondary)", fontWeight: 600 }}>
                    FFmpeg Pipeline Executing...
                  </span>
                  <span style={{ color: "var(--color-accent-primary)", fontWeight: 700 }}>
                    {renderProgress}%
                  </span>
                </div>
                <div
                  style={{
                    height: "8px",
                    width: "100%",
                    backgroundColor: "var(--color-surface-inset)",
                    borderRadius: "var(--radius-full)",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      width: `${renderProgress}%`,
                      backgroundColor: "var(--color-accent-primary)",
                      borderRadius: "var(--radius-full)",
                      transition: "width 0.4s ease",
                    }}
                  />
                </div>
                <div style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "4px" }}>
                  Processing cut intervals, clip speed modifications, audio ducking, and burning subtitle overlays...
                </div>
              </div>
            )}
          </div>

          {/* Timeline Interchange (OpenTimelineIO) */}
          <div
            className="panel"
            style={{
              padding: "20px",
              backgroundColor: "var(--color-surface-panel)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-lg)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
              <FileCode size={18} style={{ color: "var(--color-accent-primary)" }} />
              <h2 style={{ fontSize: "16px", fontWeight: 700, margin: 0, color: "var(--color-text-main)" }}>
                Professional NLE Interchange (.otio)
              </h2>
            </div>
            <p style={{ margin: "0 0 14px 0", fontSize: "13px", color: "var(--color-text-muted)" }}>
              Export this project as an OpenTimelineIO sequence compatible with DaVinci Resolve, Adobe Premiere Pro, and Final Cut Pro. Preserves track hierarchy, edits, and markers.
            </p>
            <button
              className="btn-secondary"
              onClick={onExportOtio}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "8px 14px",
                fontWeight: 600,
              }}
            >
              <Download size={14} />
              <span>Download OpenTimelineIO (.otio)</span>
            </button>
          </div>
        </div>

        {/* RIGHT COLUMN: Rendered Deliverable Hub */}
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          <div
            className="panel"
            style={{
              padding: "20px",
              backgroundColor: "var(--color-surface-panel)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-lg)",
              display: "flex",
              flexDirection: "column",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "14px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <Film size={18} style={{ color: "var(--color-accent-primary)" }} />
                <h2 style={{ fontSize: "16px", fontWeight: 700, margin: 0, color: "var(--color-text-main)" }}>
                  Rendered Deliverable Preview
                </h2>
              </div>

              {renderedVideoUrl && (
                <span
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                    fontSize: "11px",
                    fontWeight: 600,
                    backgroundColor: isHashMatching ? "var(--color-selected-bg)" : "var(--color-warning-bg)",
                    color: isHashMatching ? "var(--color-selected-text)" : "var(--color-warning)",
                    padding: "2px 8px",
                    borderRadius: "var(--radius-sm)",
                  }}
                >
                  {isHashMatching ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                  <span>{isHashMatching ? "Up to date" : "Revision outdated"}</span>
                </span>
              )}
            </div>

            {/* Video Player or Placeholder */}
            <div
              style={{
                width: "100%",
                height: "280px",
                backgroundColor: "var(--color-video-canvas)",
                borderRadius: "var(--radius-md)",
                overflow: "hidden",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                position: "relative",
              }}
            >
              {renderedVideoUrl ? (
                <video
                  src={renderedVideoUrl}
                  controls
                  style={{ width: "100%", height: "100%", objectFit: "contain" }}
                />
              ) : (
                <div style={{ textAlign: "center", color: "#8A988D", padding: "20px" }}>
                  <HardDrive size={36} style={{ opacity: 0.3, marginBottom: "8px" }} />
                  <div style={{ fontSize: "14px", fontWeight: 600 }}>No Master Deliverable Rendered Yet</div>
                  <div style={{ fontSize: "12px", opacity: 0.7, marginTop: "4px" }}>
                    Configure resolution and click "Render & Export Master Video" to produce the finalized MP4.
                  </div>
                </div>
              )}
            </div>

            {/* Action Bar when Video is Available */}
            {renderedVideoUrl && (
              <div
                style={{
                  marginTop: "16px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  backgroundColor: "var(--color-surface-inset)",
                  padding: "12px 16px",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--color-border)",
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: "13px", color: "var(--color-text-main)" }}>
                    Master MP4 Deliverable
                  </div>
                  <div style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "2px" }}>
                    Codec: H.264 / AAC • Ready for Broadcast & Social Distribution
                  </div>
                </div>

                <a
                  href={renderedVideoUrl}
                  download={`IncuBrix_${projectId}_master.mp4`}
                  className="btn-primary"
                  style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: "6px" }}
                >
                  <Download size={14} />
                  <span>Download MP4</span>
                </a>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
