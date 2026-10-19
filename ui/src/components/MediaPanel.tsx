import React, { useState, useEffect } from "react";
import {
  Film,
  UploadCloud,
  CheckCircle2,
  Search,
  RefreshCw,
  ArrowRight,
  Play,
  Clock,
  HardDrive,
  Scissors,
  MessageSquare,
  PanelLeftClose,
  Sparkles,
} from "lucide-react";
import { MediaItem } from "../types";

interface MediaPanelProps {
  currentProjectId: string;
  onSelectProject: (projectId: string) => void;
  onUploadMedia: () => void;
  onClose?: () => void;
  onMediaLoaded?: (count: number) => void;
}

export const MediaPanel: React.FC<MediaPanelProps> = ({
  currentProjectId,
  onSelectProject,
  onUploadMedia,
  onClose,
  onMediaLoaded,
}) => {
  const [mediaList, setMediaList] = useState<MediaItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [filterType, setFilterType] = useState<"all" | "active" | "recent">("all");

  const fetchMedia = async () => {
    setIsLoading(true);
    try {
      const res = await fetch("/api/v1/media");
      if (res.ok) {
        const data = await res.json();
        const items: MediaItem[] = data.media || [];
        setMediaList(items);
        if (onMediaLoaded) {
          onMediaLoaded(items.length);
        }
      }
    } catch (err) {
      console.error("Failed to fetch media list:", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchMedia();
  }, [currentProjectId]);

  const filteredMedia = mediaList.filter((m) => {
    const matchesSearch =
      m.filename.toLowerCase().includes(searchTerm.toLowerCase()) ||
      m.project_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (m.resolution && m.resolution.toLowerCase().includes(searchTerm.toLowerCase()));

    if (!matchesSearch) return false;

    if (filterType === "active") {
      return m.project_id === currentProjectId;
    }
    return true;
  });

  const formatDuration = (sec: number) => {
    if (!sec || isNaN(sec)) return "0:00";
    const mins = Math.floor(sec / 60);
    const secs = Math.floor(sec % 60);
    return `${mins}m ${secs.toString().padStart(2, "0")}s`;
  };

  const formatBytes = (bytes: number) => {
    if (!bytes || bytes === 0) return "0 MB";
    const mb = bytes / (1024 * 1024);
    if (mb >= 1000) {
      return `${(mb / 1024).toFixed(2)} GB`;
    }
    return `${mb.toFixed(1)} MB`;
  };

  return (
    <div
      className="panel"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: "680px",
        overflow: "hidden",
        border: "1px solid var(--color-border-gloss)",
        boxShadow: "0 16px 36px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.15)",
        backgroundColor: "rgba(10, 14, 24, 0.95)",
      }}
    >
      {/* 1. Header Toolbar */}
      <div
        style={{
          padding: "10px 14px",
          backgroundColor: "rgba(12, 17, 28, 0.9)",
          borderBottom: "1px solid var(--color-border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "8px",
          backdropFilter: "blur(16px)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div
            style={{
              width: "26px",
              height: "26px",
              borderRadius: "var(--radius-sm)",
              backgroundColor: "rgba(16, 185, 129, 0.2)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#34D399",
            }}
          >
            <Film size={14} />
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: "13px", color: "var(--color-text-main)", display: "flex", alignItems: "center", gap: "6px" }}>
              <span>Media Assets</span>
              <span
                style={{
                  fontSize: "10.5px",
                  padding: "1px 6px",
                  borderRadius: "9999px",
                  backgroundColor: "rgba(16, 185, 129, 0.15)",
                  color: "#34D399",
                  fontWeight: 600,
                  border: "1px solid rgba(16, 185, 129, 0.3)",
                }}
              >
                {mediaList.length}
              </span>
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <button
            className="btn-icon"
            onClick={fetchMedia}
            disabled={isLoading}
            title="Refresh media files"
            style={{ width: "28px", height: "28px" }}
          >
            <RefreshCw size={13} className={isLoading ? "spin" : ""} />
          </button>

          <button
            className="btn-primary"
            onClick={onUploadMedia}
            title="Upload local video (MP4/MOV)"
            style={{ padding: "4px 10px", fontSize: "11.5px", gap: "5px" }}
          >
            <UploadCloud size={13} />
            <span>Upload</span>
          </button>

          {onClose && (
            <button
              className="btn-icon"
              onClick={onClose}
              title="Collapse Media Panel"
              style={{ width: "28px", height: "28px" }}
            >
              <PanelLeftClose size={13} />
            </button>
          )}
        </div>
      </div>

      {/* 2. Search & Filter Bar */}
      <div
        style={{
          padding: "8px 12px",
          backgroundColor: "rgba(14, 19, 32, 0.7)",
          borderBottom: "1px solid var(--color-border)",
          display: "flex",
          flexDirection: "column",
          gap: "8px",
        }}
      >
        <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
          <Search size={13} style={{ position: "absolute", left: "10px", color: "var(--color-text-muted)" }} />
          <input
            type="text"
            placeholder="Search media by filename, ID, resolution..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              width: "100%",
              padding: "6px 10px 6px 30px",
              fontSize: "12px",
              boxSizing: "border-box",
            }}
          />
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "5px" }}>
          <button
            onClick={() => setFilterType("all")}
            className={`chip ${filterType === "all" ? "active" : ""}`}
            style={{ padding: "2px 8px", fontSize: "11px" }}
          >
            All ({mediaList.length})
          </button>
          <button
            onClick={() => setFilterType("active")}
            className={`chip ${filterType === "active" ? "active" : ""}`}
            style={{ padding: "2px 8px", fontSize: "11px" }}
          >
            Active
          </button>
        </div>
      </div>

      {/* 3. Media Items List */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "10px",
          display: "flex",
          flexDirection: "column",
          gap: "8px",
        }}
      >
        {filteredMedia.length === 0 ? (
          <div
            style={{
              textAlign: "center",
              color: "var(--color-text-muted)",
              marginTop: "40px",
              padding: "0 20px",
            }}
          >
            <Film size={34} style={{ opacity: 0.3, marginBottom: "10px" }} />
            <div style={{ fontSize: "13px", fontWeight: 600 }}>No Media Assets Found</div>
            <div style={{ fontSize: "11.5px", marginTop: "4px", color: "var(--color-text-secondary)" }}>
              {searchTerm ? "No media matches your search query." : "Upload your video clips to see them here."}
            </div>
            <button
              className="btn-primary"
              onClick={onUploadMedia}
              style={{ marginTop: "14px", padding: "6px 14px", fontSize: "12px", gap: "6px", margin: "14px auto 0" }}
            >
              <UploadCloud size={14} />
              <span>Upload Video Now</span>
            </button>
          </div>
        ) : (
          filteredMedia.map((item) => {
            const isCurrent = item.project_id === currentProjectId;

            return (
              <div
                key={item.project_id}
                onClick={() => {
                  if (!isCurrent) {
                    onSelectProject(item.project_id);
                  }
                }}
                style={{
                  padding: "10px 12px",
                  borderRadius: "var(--radius-md)",
                  backgroundColor: isCurrent ? "rgba(16, 185, 129, 0.09)" : "rgba(255, 255, 255, 0.03)",
                  border: isCurrent
                    ? "1px solid rgba(16, 185, 129, 0.45)"
                    : "1px solid var(--color-border)",
                  boxShadow: isCurrent
                    ? "0 0 16px rgba(16, 185, 129, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.1)"
                    : "none",
                  display: "flex",
                  flexDirection: "column",
                  gap: "7px",
                  cursor: isCurrent ? "default" : "pointer",
                  transition: "all 0.18s ease",
                  position: "relative",
                }}
                onMouseEnter={(e) => {
                  if (!isCurrent) {
                    e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.06)";
                    e.currentTarget.style.borderColor = "rgba(255, 255, 255, 0.18)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isCurrent) {
                    e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.03)";
                    e.currentTarget.style.borderColor = "var(--color-border)";
                  }
                }}
              >
                {/* Title & Active Badge */}
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "6px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", overflow: "hidden" }}>
                    <div
                      style={{
                        width: "32px",
                        height: "32px",
                        borderRadius: "var(--radius-sm)",
                        backgroundColor: isCurrent ? "#10B981" : "rgba(255, 255, 255, 0.08)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#FFFFFF",
                        flexShrink: 0,
                        boxShadow: isCurrent ? "0 0 10px rgba(16, 185, 129, 0.4)" : "none",
                      }}
                    >
                      {isCurrent ? <Play size={15} style={{ marginLeft: "2px" }} /> : <Film size={15} />}
                    </div>

                    <div style={{ overflow: "hidden" }}>
                      <div
                        style={{
                          fontWeight: 700,
                          fontSize: "12.5px",
                          color: isCurrent ? "#34D399" : "var(--color-text-main)",
                          textOverflow: "ellipsis",
                          overflow: "hidden",
                          whiteSpace: "nowrap",
                        }}
                        title={item.filename}
                      >
                        {item.filename}
                      </div>
                      <div
                        className="mono"
                        style={{ fontSize: "10px", color: "var(--color-text-muted)", marginTop: "1px" }}
                      >
                        {item.project_id}
                      </div>
                    </div>
                  </div>

                  {isCurrent && (
                    <span
                      style={{
                        fontSize: "9.5px",
                        fontWeight: 700,
                        backgroundColor: "rgba(16, 185, 129, 0.25)",
                        color: "#34D399",
                        border: "1px solid rgba(16, 185, 129, 0.5)",
                        borderRadius: "9999px",
                        padding: "2px 7px",
                        display: "flex",
                        alignItems: "center",
                        gap: "3px",
                        flexShrink: 0,
                      }}
                    >
                      <CheckCircle2 size={10} /> Active
                    </span>
                  )}
                </div>

                {/* Metadata Pills */}
                <div style={{ display: "flex", alignItems: "center", gap: "5px", flexWrap: "wrap", fontSize: "10.5px" }}>
                  <span
                    style={{
                      backgroundColor: "rgba(255, 255, 255, 0.06)",
                      padding: "2px 6px",
                      borderRadius: "var(--radius-xs)",
                      color: "var(--color-text-secondary)",
                      display: "flex",
                      alignItems: "center",
                      gap: "3px",
                    }}
                  >
                    <Clock size={10} style={{ color: "#34D399" }} />
                    <span>{formatDuration(item.duration_s || item.source_duration_s)}</span>
                  </span>

                  {item.resolution && (
                    <span
                      style={{
                        backgroundColor: "rgba(255, 255, 255, 0.06)",
                        padding: "2px 6px",
                        borderRadius: "var(--radius-xs)",
                        color: "var(--color-text-secondary)",
                      }}
                    >
                      {item.resolution}
                    </span>
                  )}

                  {item.fps && (
                    <span
                      style={{
                        backgroundColor: "rgba(255, 255, 255, 0.06)",
                        padding: "2px 6px",
                        borderRadius: "var(--radius-xs)",
                        color: "var(--color-text-secondary)",
                      }}
                    >
                      {item.fps} fps
                    </span>
                  )}

                  <span
                    style={{
                      backgroundColor: "rgba(255, 255, 255, 0.06)",
                      padding: "2px 6px",
                      borderRadius: "var(--radius-xs)",
                      color: "var(--color-text-secondary)",
                      display: "flex",
                      alignItems: "center",
                      gap: "3px",
                    }}
                  >
                    <HardDrive size={10} />
                    <span>{formatBytes(item.size_bytes)}</span>
                  </span>

                  {item.segments_count > 0 && (
                    <span
                      style={{
                        backgroundColor: "rgba(255, 255, 255, 0.06)",
                        padding: "2px 6px",
                        borderRadius: "var(--radius-xs)",
                        color: "var(--color-text-secondary)",
                        display: "flex",
                        alignItems: "center",
                        gap: "3px",
                      }}
                    >
                      <Scissors size={10} />
                      <span>{item.segments_count} clips</span>
                    </span>
                  )}

                  {item.captions_count > 0 && (
                    <span
                      style={{
                        backgroundColor: "rgba(255, 255, 255, 0.06)",
                        padding: "2px 6px",
                        borderRadius: "var(--radius-xs)",
                        color: "#FACC15",
                        display: "flex",
                        alignItems: "center",
                        gap: "3px",
                      }}
                    >
                      <MessageSquare size={10} />
                      <span>{item.captions_count} caps</span>
                    </span>
                  )}
                </div>

                {/* Quick Action Button for non-active */}
                {!isCurrent && (
                  <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "2px" }}>
                    <button
                      className="btn-secondary"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectProject(item.project_id);
                      }}
                      style={{ padding: "4px 10px", fontSize: "11px", gap: "5px" }}
                    >
                      <span>Load in Studio</span>
                      <ArrowRight size={11} />
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* 4. Bottom Info Footer */}
      <div
        style={{
          padding: "8px 12px",
          backgroundColor: "rgba(10, 14, 24, 0.8)",
          borderTop: "1px solid var(--color-border)",
          fontSize: "11px",
          color: "var(--color-text-muted)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
          <Sparkles size={11} style={{ color: "#34D399" }} />
          <span>Click any media to open</span>
        </span>
        <button
          onClick={onUploadMedia}
          style={{
            background: "none",
            border: "none",
            color: "#34D399",
            cursor: "pointer",
            fontWeight: 600,
            fontSize: "11px",
            padding: 0,
          }}
        >
          + Add New
        </button>
      </div>
    </div>
  );
};
