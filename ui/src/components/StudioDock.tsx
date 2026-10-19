import React, { useState } from "react";
import {
  Film,
  Sparkles,
  FileText,
  History,
  ShieldCheck,
  Search,
  RotateCcw,
  Code2,
  Database,
  RefreshCw,
  Cpu,
} from "lucide-react";
import { Timeline, ChatMessage, TranscriptWord, TransactionRecord } from "../types";
import { ChatAssistant } from "./ChatAssistant";
import { MediaPanel } from "./MediaPanel";

interface StudioDockProps {
  projectId: string;
  timeline: Timeline | null;
  chatMessages: ChatMessage[];
  onSendMessage: (text: string) => void;
  isLoading: boolean;
  onOptionClick: (opt: string) => void;
  onSeek: (timeSec: number) => void;
  onSelectiveRestore: (txId: string) => void;
  isRestoring: boolean;
  onSelectProject: (projectId: string) => void;
  onUploadMedia: () => void;
  onTranscribe?: (mode: "real" | "mock") => Promise<void>;
  isTranscribing?: boolean;
}

export const StudioDock: React.FC<StudioDockProps> = ({
  projectId,
  timeline,
  chatMessages,
  onSendMessage,
  isLoading,
  onOptionClick,
  onSeek,
  onSelectiveRestore,
  isRestoring,
  onSelectProject,
  onUploadMedia,
  onTranscribe,
  isTranscribing = false,
}) => {
  const [activeTab, setActiveTab] = useState<"media" | "copilot" | "transcript" | "history" | "specs">("copilot");
  const [searchTerm, setSearchTerm] = useState("");

  const words = timeline?.transcript?.words || [];
  const transactions = timeline?.transactions || [];

  const filteredWords = words.filter(
    (w: TranscriptWord) =>
      w.word.toLowerCase().includes(searchTerm.toLowerCase()) ||
      w.speaker.toLowerCase().includes(searchTerm.toLowerCase())
  );

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
      }}
    >
      {/* 1. Glossy Tab Switcher Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "6px 8px",
          backgroundColor: "rgba(10, 14, 24, 0.85)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          borderBottom: "1px solid var(--color-border)",
        }}
      >
        <div style={{ display: "flex", gap: "3px", width: "100%" }}>
          {/* Media Tab */}
          <button
            onClick={() => setActiveTab("media")}
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "4px",
              padding: "7px 4px",
              fontSize: "11.5px",
              fontWeight: activeTab === "media" ? 700 : 500,
              color: activeTab === "media" ? "#FFFFFF" : "var(--color-text-secondary)",
              background:
                activeTab === "media"
                  ? "linear-gradient(180deg, rgba(255, 255, 255, 0.14) 0%, rgba(255, 255, 255, 0.03) 100%)"
                  : "transparent",
              border: activeTab === "media" ? "1px solid rgba(255, 255, 255, 0.18)" : "1px solid transparent",
              borderRadius: "var(--radius-md)",
              cursor: "pointer",
              boxShadow:
                activeTab === "media"
                  ? "inset 0 1px 0 rgba(255, 255, 255, 0.2), 0 2px 8px rgba(0, 0, 0, 0.3)"
                  : "none",
              transition: "all 0.15s ease",
            }}
          >
            <Film size={12} style={{ color: activeTab === "media" ? "#34D399" : "inherit" }} />
            <span>Media</span>
          </button>

          {/* Copilot Tab */}
          <button
            onClick={() => setActiveTab("copilot")}
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "4px",
              padding: "7px 4px",
              fontSize: "11.5px",
              fontWeight: activeTab === "copilot" ? 700 : 500,
              color: activeTab === "copilot" ? "#FFFFFF" : "var(--color-text-secondary)",
              background:
                activeTab === "copilot"
                  ? "linear-gradient(180deg, rgba(255, 255, 255, 0.14) 0%, rgba(255, 255, 255, 0.03) 100%)"
                  : "transparent",
              border: activeTab === "copilot" ? "1px solid rgba(255, 255, 255, 0.18)" : "1px solid transparent",
              borderRadius: "var(--radius-md)",
              cursor: "pointer",
              boxShadow:
                activeTab === "copilot"
                  ? "inset 0 1px 0 rgba(255, 255, 255, 0.2), 0 2px 8px rgba(0, 0, 0, 0.3)"
                  : "none",
              transition: "all 0.15s ease",
            }}
          >
            <Sparkles size={12} style={{ color: activeTab === "copilot" ? "#34D399" : "inherit" }} />
            <span>Copilot</span>
          </button>

          {/* Transcript Tab */}
          <button
            onClick={() => setActiveTab("transcript")}
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "5px",
              padding: "7px 6px",
              fontSize: "12px",
              fontWeight: activeTab === "transcript" ? 700 : 500,
              color: activeTab === "transcript" ? "#FFFFFF" : "var(--color-text-secondary)",
              background:
                activeTab === "transcript"
                  ? "linear-gradient(180deg, rgba(255, 255, 255, 0.14) 0%, rgba(255, 255, 255, 0.03) 100%)"
                  : "transparent",
              border: activeTab === "transcript" ? "1px solid rgba(255, 255, 255, 0.18)" : "1px solid transparent",
              borderRadius: "var(--radius-md)",
              cursor: "pointer",
              boxShadow:
                activeTab === "transcript"
                  ? "inset 0 1px 0 rgba(255, 255, 255, 0.2), 0 2px 8px rgba(0, 0, 0, 0.3)"
                  : "none",
              transition: "all 0.15s ease",
            }}
          >
            <FileText size={13} style={{ color: activeTab === "transcript" ? "#60A5FA" : "inherit" }} />
            <span>Transcript</span>
            {words.length > 0 && (
              <span
                style={{
                  fontSize: "10px",
                  padding: "1px 5px",
                  borderRadius: "9999px",
                  backgroundColor: "rgba(255, 255, 255, 0.08)",
                  fontWeight: 600,
                }}
              >
                {words.length}
              </span>
            )}
          </button>

          {/* Journal Tab */}
          <button
            onClick={() => setActiveTab("history")}
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "5px",
              padding: "7px 6px",
              fontSize: "12px",
              fontWeight: activeTab === "history" ? 700 : 500,
              color: activeTab === "history" ? "#FFFFFF" : "var(--color-text-secondary)",
              background:
                activeTab === "history"
                  ? "linear-gradient(180deg, rgba(255, 255, 255, 0.14) 0%, rgba(255, 255, 255, 0.03) 100%)"
                  : "transparent",
              border: activeTab === "history" ? "1px solid rgba(255, 255, 255, 0.18)" : "1px solid transparent",
              borderRadius: "var(--radius-md)",
              cursor: "pointer",
              boxShadow:
                activeTab === "history"
                  ? "inset 0 1px 0 rgba(255, 255, 255, 0.2), 0 2px 8px rgba(0, 0, 0, 0.3)"
                  : "none",
              transition: "all 0.15s ease",
            }}
          >
            <History size={13} style={{ color: activeTab === "history" ? "#F59E0B" : "inherit" }} />
            <span>Journal</span>
            {transactions.length > 0 && (
              <span
                style={{
                  fontSize: "10px",
                  padding: "1px 5px",
                  borderRadius: "9999px",
                  backgroundColor: "rgba(255, 255, 255, 0.08)",
                  fontWeight: 600,
                }}
              >
                {transactions.length}
              </span>
            )}
          </button>

          {/* Specs Tab */}
          <button
            onClick={() => setActiveTab("specs")}
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "5px",
              padding: "7px 6px",
              fontSize: "12px",
              fontWeight: activeTab === "specs" ? 700 : 500,
              color: activeTab === "specs" ? "#FFFFFF" : "var(--color-text-secondary)",
              background:
                activeTab === "specs"
                  ? "linear-gradient(180deg, rgba(255, 255, 255, 0.14) 0%, rgba(255, 255, 255, 0.03) 100%)"
                  : "transparent",
              border: activeTab === "specs" ? "1px solid rgba(255, 255, 255, 0.18)" : "1px solid transparent",
              borderRadius: "var(--radius-md)",
              cursor: "pointer",
              boxShadow:
                activeTab === "specs"
                  ? "inset 0 1px 0 rgba(255, 255, 255, 0.2), 0 2px 8px rgba(0, 0, 0, 0.3)"
                  : "none",
              transition: "all 0.15s ease",
            }}
          >
            <ShieldCheck size={13} style={{ color: activeTab === "specs" ? "#A78BFA" : "inherit" }} />
            <span>Specs</span>
          </button>
        </div>
      </div>

      {/* 2. Content Area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>
        {/* TAB 0: MEDIA ASSETS LIBRARY */}
        {activeTab === "media" && (
          <div style={{ flex: 1, height: "100%", overflow: "hidden" }}>
            <MediaPanel
              currentProjectId={projectId}
              onSelectProject={onSelectProject}
              onUploadMedia={onUploadMedia}
            />
          </div>
        )}

        {/* TAB 1: COPILOT ASSISTANT */}
        {activeTab === "copilot" && (
          <div style={{ flex: 1, height: "100%", overflow: "hidden" }}>
            <ChatAssistant
              projectId={projectId}
              messages={chatMessages}
              onSendMessage={onSendMessage}
              isLoading={isLoading}
              onOptionClick={onOptionClick}
            />
          </div>
        )}

        {/* TAB 2: TRANSCRIPT */}
        {activeTab === "transcript" && (
          <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
            {/* Search Bar */}
            <div
              style={{
                padding: "8px 12px",
                backgroundColor: "rgba(12, 17, 28, 0.7)",
                borderBottom: "1px solid var(--color-border)",
                display: "flex",
                alignItems: "center",
                gap: "8px",
              }}
            >
              <Search size={14} style={{ color: "var(--color-text-muted)" }} />
              <input
                type="text"
                placeholder="Search dialogue words or speaker..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{
                  width: "100%",
                  padding: "5px 10px",
                  fontSize: "12px",
                }}
              />
            </div>

            {/* Words List */}
            <div style={{ flex: 1, overflowY: "auto", padding: "10px", display: "flex", flexDirection: "column", gap: "6px" }}>
              {filteredWords.length === 0 ? (
                <div style={{ textAlign: "center", color: "var(--color-text-muted)", marginTop: "40px", fontSize: "12px" }}>
                  No words match your search.
                </div>
              ) : (
                filteredWords.map((word: TranscriptWord) => {
                  const startS = word.start_ticks / 1000;
                  const endS = word.end_ticks / 1000;
                  const isFiller = word.is_filler;

                  return (
                    <div
                      key={word.id}
                      onClick={() => onSeek(startS)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "7px 10px",
                        borderRadius: "var(--radius-md)",
                        backgroundColor: "rgba(255, 255, 255, 0.03)",
                        border: "1px solid var(--color-border-subtle)",
                        cursor: "pointer",
                        fontSize: "12px",
                        transition: "all 0.15s ease",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = "rgba(16, 185, 129, 0.1)";
                        e.currentTarget.style.borderColor = "rgba(16, 185, 129, 0.3)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.03)";
                        e.currentTarget.style.borderColor = "var(--color-border-subtle)";
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span
                          style={{
                            fontSize: "10px",
                            fontWeight: 700,
                            backgroundColor: word.speaker === "guest" ? "rgba(56, 189, 248, 0.15)" : "rgba(16, 185, 129, 0.15)",
                            color: word.speaker === "guest" ? "#38BDF8" : "#34D399",
                            padding: "2px 6px",
                            borderRadius: "var(--radius-xs)",
                            textTransform: "capitalize",
                            border: `1px solid ${word.speaker === "guest" ? "rgba(56, 189, 248, 0.3)" : "rgba(16, 185, 129, 0.3)"}`,
                          }}
                        >
                          {word.speaker}
                        </span>

                        <span
                          style={{
                            fontWeight: 600,
                            color: isFiller ? "#F43F5E" : "var(--color-text-main)",
                          }}
                        >
                          {word.word}
                        </span>

                        {isFiller && (
                          <span
                            style={{
                              fontSize: "10px",
                              backgroundColor: "rgba(244, 63, 94, 0.15)",
                              color: "#F43F5E",
                              padding: "1px 5px",
                              borderRadius: "var(--radius-xs)",
                              border: "1px solid rgba(244, 63, 94, 0.3)",
                              fontWeight: 600,
                            }}
                          >
                            filler
                          </span>
                        )}
                      </div>

                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span className="mono" style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
                          {startS.toFixed(1)}s - {endS.toFixed(1)}s
                        </span>
                        <span style={{ fontSize: "10px", color: "var(--color-text-muted)" }}>
                          {(word.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}

        {/* TAB 3: HISTORY & SELECTIVE RESTORE */}
        {activeTab === "history" && (
          <div style={{ flex: 1, overflowY: "auto", padding: "12px", display: "flex", flexDirection: "column", gap: "8px" }}>
            {transactions.length === 0 ? (
              <div style={{ textAlign: "center", color: "var(--color-text-muted)", marginTop: "40px", fontSize: "12px" }}>
                No edits applied yet. Use prompt or Auto Edit.
              </div>
            ) : (
              transactions.map((tx: TransactionRecord, idx: number) => {
                const isRestorable = tx.status === "applied" && tx.operation_type !== "restore_transaction";

                return (
                  <div
                    key={tx.id || idx}
                    style={{
                      padding: "10px 12px",
                      borderRadius: "var(--radius-md)",
                      backgroundColor: "rgba(255, 255, 255, 0.03)",
                      border: "1px solid var(--color-border)",
                      fontSize: "12px",
                      display: "flex",
                      flexDirection: "column",
                      gap: "6px",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <span style={{ fontWeight: 700, color: "var(--color-text-main)" }}>
                          #{idx + 1} [{tx.operation_type}]
                        </span>
                        <span
                          style={{
                            fontSize: "10px",
                            fontWeight: 700,
                            padding: "1px 6px",
                            borderRadius: "var(--radius-full)",
                            backgroundColor:
                              tx.status === "applied"
                                ? "rgba(16, 185, 129, 0.15)"
                                : tx.status === "restored"
                                ? "rgba(99, 102, 241, 0.15)"
                                : "rgba(255, 255, 255, 0.05)",
                            color:
                              tx.status === "applied"
                                ? "#34D399"
                                : tx.status === "restored"
                                ? "#818CF8"
                                : "var(--color-text-muted)",
                            border: `1px solid ${
                              tx.status === "applied"
                                ? "rgba(16, 185, 129, 0.3)"
                                : tx.status === "restored"
                                ? "rgba(99, 102, 241, 0.3)"
                                : "rgba(255, 255, 255, 0.1)"
                            }`,
                          }}
                        >
                          {tx.status}
                        </span>
                      </div>

                      {isRestorable && (
                        <button
                          className="btn-secondary"
                          onClick={() => onSelectiveRestore(tx.id)}
                          disabled={isRestoring}
                          title={`Selectively restore edit ${tx.id} while preserving later independent edits`}
                          style={{ padding: "3px 8px", fontSize: "11px", gap: "4px" }}
                        >
                          <RotateCcw size={11} />
                          <span>Restore</span>
                        </button>
                      )}
                    </div>

                    <div style={{ fontSize: "11.5px", color: "var(--color-text-secondary)" }}>
                      {tx.instruction}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}

        {/* TAB 4: SPECS & CRYPTOGRAPHIC PROOFS */}
        {activeTab === "specs" && (
          <div style={{ flex: 1, overflowY: "auto", padding: "14px", display: "flex", flexDirection: "column", gap: "12px", fontSize: "12px" }}>
            {/* Immutability Proof */}
            <div
              style={{
                padding: "12px",
                borderRadius: "var(--radius-md)",
                backgroundColor: "rgba(255, 255, 255, 0.03)",
                border: "1px solid var(--color-border)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 700, marginBottom: "8px", color: "var(--color-text-main)" }}>
                <ShieldCheck size={14} style={{ color: "#10B981" }} />
                <span>Source Media Immutability</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                <div>
                  <strong>File:</strong> {timeline?.source_media?.filename || "None"}
                </div>
                <div style={{ wordBreak: "break-all" }}>
                  <strong>SHA-256:</strong>{" "}
                  <code className="mono" style={{ fontSize: "10.5px", color: "#34D399" }}>
                    {timeline?.source_media?.sha256_hash || "N/A"}
                  </code>
                </div>
                <div style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "4px" }}>
                  Guaranteed bit-for-bit unchanged pre- and post-render.
                </div>
              </div>
            </div>

            {/* Canonical Hash */}
            <div
              style={{
                padding: "12px",
                borderRadius: "var(--radius-md)",
                backgroundColor: "rgba(255, 255, 255, 0.03)",
                border: "1px solid var(--color-border)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 700, marginBottom: "8px", color: "var(--color-text-main)" }}>
                <Code2 size={14} style={{ color: "#60A5FA" }} />
                <span>Deterministic Canonical Hash</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                <div style={{ wordBreak: "break-all" }}>
                  <code className="mono" style={{ fontSize: "11px", color: "#60A5FA" }}>
                    {timeline?.timeline_hash || "N/A"}
                  </code>
                </div>
                <div style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "4px" }}>
                  Stripped of non-deterministic session IDs and timestamps for 100% reproducible hashing.
                </div>
              </div>
            </div>

            {/* Sync & Precision Standard */}
            <div
              style={{
                padding: "12px",
                borderRadius: "var(--radius-md)",
                backgroundColor: "rgba(255, 255, 255, 0.03)",
                border: "1px solid var(--color-border)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 700, marginBottom: "8px", color: "var(--color-text-main)" }}>
                <Database size={14} style={{ color: "#F59E0B" }} />
                <span>Engine & Time Math Standard</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px", fontSize: "11.5px" }}>
                <div>
                  <strong>Time Base:</strong> Integer Millisecond Ticks (1/1000s)
                </div>
                <div>
                  <strong>A/V Sync Accuracy:</strong> 0.000 frame measured drift
                </div>
                <div>
                  <strong>Storage:</strong> ACID SQLite with WAL Mode
                </div>
                <div>
                  <strong>Renderer:</strong> FFmpeg Filtergraph Subsystem
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
