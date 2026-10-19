import React, { useState } from "react";
import { ChevronDown, ChevronUp, Code2, ShieldCheck, Database, FileCode } from "lucide-react";
import { Timeline } from "../types";

interface DeveloperDetailsProps {
  timeline: Timeline | null;
  projectId: string;
}

export const DeveloperDetails: React.FC<DeveloperDetailsProps> = ({
  timeline,
  projectId,
}) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!timeline) return null;

  return (
    <div
      className="panel"
      style={{
        marginTop: "16px",
        overflow: "hidden",
      }}
    >
      {/* Toggle Bar */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        style={{
          width: "100%",
          padding: "10px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          backgroundColor: "var(--color-surface-inset)",
          border: "none",
          cursor: "pointer",
          fontSize: "12px",
          fontWeight: 600,
          color: "var(--color-text-secondary)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <Code2 size={14} style={{ color: "var(--color-accent-primary)" }} />
          <span>Developer Details & Assessment Evidence (Collapsible)</span>
        </div>
        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {/* Expanded Content */}
      {isOpen && (
        <div
          style={{
            padding: "16px",
            backgroundColor: "var(--color-surface-panel)",
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "14px",
            fontSize: "12px",
          }}
        >
          {/* Source Integrity */}
          <div
            style={{
              padding: "12px",
              borderRadius: "var(--radius-md)",
              backgroundColor: "var(--color-surface-inset)",
              border: "1px solid var(--color-border)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 600, marginBottom: "8px", color: "var(--color-text-main)" }}>
              <ShieldCheck size={14} style={{ color: "var(--color-success)" }} />
              <span>Source Media Immutability</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <div>
                <strong>File:</strong> {timeline.source_media.filename}
              </div>
              <div style={{ wordBreak: "break-all" }}>
                <strong>SHA-256:</strong> <code style={{ fontSize: "11px" }}>{timeline.source_media.sha256_hash}</code>
              </div>
              <div>
                <strong>Specs:</strong> {timeline.source_media.width}x{timeline.source_media.height} @ {timeline.source_media.fps}fps, {timeline.source_media.sample_rate || 48000}Hz
              </div>
              <div>
                <strong>Original Duration:</strong> {(timeline.source_media.duration_ticks / 1000).toFixed(2)}s
              </div>
            </div>
          </div>

          {/* Timeline Canonical Hash & Endpoints */}
          <div
            style={{
              padding: "12px",
              borderRadius: "var(--radius-md)",
              backgroundColor: "var(--color-surface-inset)",
              border: "1px solid var(--color-border)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 600, marginBottom: "8px", color: "var(--color-text-main)" }}>
              <Database size={14} style={{ color: "var(--color-accent-primary)" }} />
              <span>Timeline Hash & Verification</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <div style={{ wordBreak: "break-all" }}>
                <strong>Current Hash:</strong> <code style={{ fontSize: "11px" }}>{timeline.timeline_hash}</code>
              </div>
              <div>
                <strong>Schema Version:</strong> {timeline.schema_version}
              </div>
              <div>
                <strong>Active Transactions:</strong> {timeline.transactions.length}
              </div>
              <div style={{ marginTop: "6px" }}>
                <a
                  href={`/api/v1/projects/${projectId}/timeline`}
                  target="_blank"
                  rel="noreferrer"
                  className="btn-secondary"
                  style={{ textDecoration: "none", fontSize: "11px", padding: "3px 8px" }}
                >
                  <FileCode size={12} />
                  <span>View Raw Timeline JSON</span>
                </a>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
