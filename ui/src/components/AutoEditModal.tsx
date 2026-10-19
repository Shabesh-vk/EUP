import { useState } from "react";
import { Sparkles, X, Check, Volume2, MessageSquare, Clock, Filter } from "lucide-react";
import { AutoEditPlan, AutoEditItem } from "../types";

interface AutoEditModalProps {
  plan: AutoEditPlan | null;
  onClose: () => void;
  onApply: (excludedItemIds: string[]) => void;
  isApplying: boolean;
}

export const AutoEditModal: React.FC<AutoEditModalProps> = ({
  plan,
  onClose,
  onApply,
  isApplying,
}) => {
  const [excludedIds, setExcludedIds] = useState<Set<string>>(new Set());

  if (!plan) return null;

  const toggleExclude = (itemId: string) => {
    const next = new Set(excludedIds);
    if (next.has(itemId)) {
      next.delete(itemId);
    } else {
      next.add(itemId);
    }
    setExcludedIds(next);
  };

  const activeItemsCount = plan.items.filter((it) => !excludedIds.has(it.item_id)).length;

  const netSavedSeconds = Math.max(
    0,
    (plan.current_duration_s || 0) - (plan.estimated_duration_s || 0)
  );

  const getCategoryIcon = (cat: string) => {
    switch (cat) {
      case "silence":
        return <Clock size={14} style={{ color: "var(--color-warning)" }} />;
      case "filler_word":
        return <Filter size={14} style={{ color: "var(--color-danger)" }} />;
      case "auto_caption":
        return <MessageSquare size={14} style={{ color: "var(--color-accent-primary)" }} />;
      case "music":
        return <Volume2 size={14} style={{ color: "#7C3AED" }} />;
      default:
        return <Sparkles size={14} />;
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: "rgba(0, 0, 0, 0.75)",
        backdropFilter: "blur(14px)",
        WebkitBackdropFilter: "blur(14px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        className="panel"
        style={{
          width: "90%",
          maxWidth: "640px",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 24px 60px rgba(0, 0, 0, 0.7), inset 0 1px 0 rgba(255, 255, 255, 0.2)",
          border: "1px solid var(--color-border-gloss)",
          overflow: "hidden",
        }}
      >
        {/* Modal Header */}
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--color-border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            backgroundColor: "var(--color-surface-panel)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <div
              style={{
                backgroundColor: "var(--color-selected-bg)",
                color: "var(--color-accent-primary)",
                padding: "6px",
                borderRadius: "var(--radius-md)",
                display: "flex",
              }}
            >
              <Sparkles size={18} />
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: "16px", color: "var(--color-text-main)" }}>
                Auto Edit: Clean Up Preset
              </div>
              <div style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>
                Review detected improvements before applying as a single atomic transaction
              </div>
            </div>
          </div>

          <button className="btn-icon" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {/* Plan Summary Banner */}
        <div
          style={{
            padding: "12px 20px",
            backgroundColor: "var(--color-surface-inset)",
            borderBottom: "1px solid var(--color-border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: "13px",
          }}
        >
          <div>
            <strong>{activeItemsCount} of {plan.items.length}</strong> actions selected
          </div>
          <div>
            Net time saved: <strong style={{ color: "var(--color-accent-primary)" }}>{netSavedSeconds.toFixed(1)}s</strong>
          </div>
        </div>

        {/* Items List */}
        <div
          style={{
            flex: 1,
            padding: "14px 20px",
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: "8px",
          }}
        >
          {plan.items.length === 0 ? (
            <div style={{ textAlign: "center", padding: "30px", color: "var(--color-text-muted)" }}>
              No clean up actions detected. The media is already clean!
            </div>
          ) : (
            plan.items.map((item: AutoEditItem) => {
              const isExcluded = excludedIds.has(item.item_id);

              return (
                <div
                  key={item.item_id}
                  onClick={() => toggleExclude(item.item_id)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "10px 14px",
                    borderRadius: "var(--radius-md)",
                    backgroundColor: isExcluded ? "var(--color-surface-inset)" : "var(--color-surface-panel)",
                    border: `1px solid ${isExcluded ? "var(--color-border)" : "var(--color-accent-primary)"}`,
                    opacity: isExcluded ? 0.6 : 1.0,
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <input
                      type="checkbox"
                      checked={!isExcluded}
                      onChange={() => {}}
                      style={{ accentColor: "var(--color-accent-primary)", cursor: "pointer" }}
                    />
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        {getCategoryIcon(item.category)}
                        <span style={{ fontWeight: 600, fontSize: "13px", color: "var(--color-text-main)" }}>
                          {item.description}
                        </span>
                      </div>
                      <div style={{ fontSize: "11px", color: "var(--color-text-muted)", marginTop: "2px" }}>
                        Category: {item.category} • Range: {(item.source_start_ticks / 1000).toFixed(1)}s - {(item.source_end_ticks / 1000).toFixed(1)}s
                      </div>
                    </div>
                  </div>

                  <div style={{ textAlign: "right", fontSize: "11px", color: "var(--color-text-secondary)" }}>
                    {item.source_end_ticks > item.source_start_ticks && item.category !== "auto_caption" && item.category !== "music" ? (
                      <span style={{ fontWeight: 600, color: "var(--color-accent-primary)" }}>
                        -{((item.source_end_ticks - item.source_start_ticks) / 1000).toFixed(1)}s
                      </span>
                    ) : (
                      <span>{(item.confidence * 100).toFixed(0)}% conf</span>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Modal Footer */}
        <div
          style={{
            padding: "14px 20px",
            borderTop: "1px solid var(--color-border)",
            backgroundColor: "var(--color-surface-panel)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
            Changes will record as 1 undoable transaction.
          </span>

          <div style={{ display: "flex", gap: "8px" }}>
            <button className="btn-secondary" onClick={onClose} disabled={isApplying}>
              Cancel
            </button>
            <button
              className="btn-primary"
              onClick={() => onApply(Array.from(excludedIds))}
              disabled={isApplying || activeItemsCount === 0}
            >
              <Check size={14} />
              <span>{isApplying ? "Applying..." : `Apply (${activeItemsCount} actions)`}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
