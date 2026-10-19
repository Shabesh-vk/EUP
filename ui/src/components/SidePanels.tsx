import React, { useState } from "react";
import { FileText, History, RotateCcw, Search } from "lucide-react";
import { Timeline, TranscriptWord, TransactionRecord } from "../types";

interface SidePanelsProps {
  timeline: Timeline | null;
  onSeek: (timeSec: number) => void;
  onSelectiveRestore: (txId: string) => void;
  isRestoring: boolean;
}

export const SidePanels: React.FC<SidePanelsProps> = ({
  timeline,
  onSeek,
  onSelectiveRestore,
  isRestoring,
}) => {
  const [activeTab, setActiveTab] = useState<"transcript" | "history">("transcript");
  const [searchTerm, setSearchTerm] = useState("");

  const words = timeline?.transcript?.words || [];
  const transactions = timeline?.transactions || [];

  const filteredWords = words.filter((w: TranscriptWord) =>
    w.word.toLowerCase().includes(searchTerm.toLowerCase()) ||
    w.speaker.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div
      className="panel"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "360px",
        overflow: "hidden",
      }}
    >
      {/* Tab Navigation Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderBottom: "1px solid var(--color-border)",
          backgroundColor: "var(--color-surface-panel)",
          padding: "0 12px",
        }}
      >
        <div style={{ display: "flex", gap: "4px" }}>
          <button
            onClick={() => setActiveTab("transcript")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              padding: "10px 14px",
              fontSize: "13px",
              fontWeight: activeTab === "transcript" ? 600 : 500,
              color: activeTab === "transcript" ? "var(--color-accent-primary)" : "var(--color-text-secondary)",
              borderBottom: activeTab === "transcript" ? "2px solid var(--color-accent-primary)" : "2px solid transparent",
              background: "none",
              border: "none",
              cursor: "pointer",
            }}
          >
            <FileText size={14} />
            <span>Transcript ({words.length})</span>
          </button>

          <button
            onClick={() => setActiveTab("history")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              padding: "10px 14px",
              fontSize: "13px",
              fontWeight: activeTab === "history" ? 600 : 500,
              color: activeTab === "history" ? "var(--color-accent-primary)" : "var(--color-text-secondary)",
              borderBottom: activeTab === "history" ? "2px solid var(--color-accent-primary)" : "2px solid transparent",
              background: "none",
              border: "none",
              cursor: "pointer",
            }}
          >
            <History size={14} />
            <span>Edit Journal ({transactions.length})</span>
          </button>
        </div>

        {/* Search Bar for Transcript */}
        {activeTab === "transcript" && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              backgroundColor: "var(--color-surface-inset)",
              padding: "3px 8px",
              borderRadius: "var(--radius-full)",
              border: "1px solid var(--color-border)",
            }}
          >
            <Search size={12} style={{ color: "var(--color-text-muted)" }} />
            <input
              type="text"
              placeholder="Search words or speakers..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{
                border: "none",
                background: "transparent",
                outline: "none",
                fontSize: "12px",
                width: "160px",
                color: "var(--color-text-main)",
              }}
            />
          </div>
        )}
      </div>

      {/* Content Area */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px" }}>
        {activeTab === "transcript" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            {filteredWords.length === 0 ? (
              <div style={{ textAlign: "center", color: "var(--color-text-muted)", marginTop: "30px", fontSize: "12px" }}>
                No transcript words match your filter.
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
                      padding: "6px 10px",
                      borderRadius: "var(--radius-md)",
                      backgroundColor: "var(--color-surface-inset)",
                      border: "1px solid var(--color-border-subtle)",
                      cursor: "pointer",
                      fontSize: "12px",
                      transition: "background-color 0.15s ease",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span
                        style={{
                          fontSize: "10px",
                          fontWeight: 600,
                          backgroundColor: word.speaker === "guest" ? "#BAE6FD" : "#E2E8DE",
                          color: word.speaker === "guest" ? "#0369A1" : "var(--color-text-secondary)",
                          padding: "2px 6px",
                          borderRadius: "var(--radius-sm)",
                          textTransform: "capitalize",
                        }}
                      >
                        {word.speaker}
                      </span>

                      <span style={{ fontWeight: 600, color: isFiller ? "var(--color-danger)" : "var(--color-text-main)" }}>
                        {word.word}
                      </span>

                      {isFiller && (
                        <span
                          style={{
                            fontSize: "10px",
                            backgroundColor: "var(--color-danger-bg)",
                            color: "var(--color-danger)",
                            padding: "1px 5px",
                            borderRadius: "var(--radius-sm)",
                          }}
                        >
                          filler
                        </span>
                      )}
                    </div>

                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--color-text-muted)" }}>
                        {startS.toFixed(1)}s - {endS.toFixed(1)}s
                      </span>
                      <span style={{ fontSize: "10px", color: "var(--color-text-muted)" }}>
                        conf: {(word.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}

        {activeTab === "history" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            {transactions.length === 0 ? (
              <div style={{ textAlign: "center", color: "var(--color-text-muted)", marginTop: "30px", fontSize: "12px" }}>
                No edits applied yet. Use the prompt or Auto Edit to modify the timeline.
              </div>
            ) : (
              transactions.map((tx: TransactionRecord, idx: number) => {
                const isRestorable = tx.status === "applied" && tx.operation_type !== "restore_transaction";

                return (
                  <div
                    key={tx.id || idx}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "8px 12px",
                      borderRadius: "var(--radius-md)",
                      backgroundColor: "var(--color-surface-inset)",
                      border: "1px solid var(--color-border)",
                      fontSize: "12px",
                    }}
                  >
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <span style={{ fontWeight: 700, color: "var(--color-text-main)" }}>
                          #{idx + 1} [{tx.operation_type}]
                        </span>
                        <span
                          style={{
                            fontSize: "10px",
                            fontWeight: 600,
                            padding: "1px 5px",
                            borderRadius: "var(--radius-sm)",
                            backgroundColor:
                              tx.status === "applied"
                                ? "var(--color-selected-bg)"
                                : tx.status === "restored"
                                ? "#E0E7FF"
                                : "var(--color-surface-inset)",
                            color:
                              tx.status === "applied"
                                ? "var(--color-selected-text)"
                                : tx.status === "restored"
                                ? "#3730A3"
                                : "var(--color-text-muted)",
                          }}
                        >
                          {tx.status}
                        </span>
                      </div>
                      <div style={{ fontSize: "11px", color: "var(--color-text-secondary)", marginTop: "2px" }}>
                        {tx.instruction}
                      </div>
                    </div>

                    {isRestorable && (
                      <button
                        className="btn-secondary"
                        onClick={() => onSelectiveRestore(tx.id)}
                        disabled={isRestoring}
                        title={`Selectively restore this edit (${tx.id}) without losing later changes`}
                        style={{ padding: "4px 8px", fontSize: "11px" }}
                      >
                        <RotateCcw size={12} />
                        <span>Selective Restore</span>
                      </button>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>
    </div>
  );
};
