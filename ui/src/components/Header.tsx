import React, { useState } from "react";
import {
  Layers,
  Cpu,
  Clock,
  Sparkles,
  Undo2,
  Redo2,
  Download,
  UploadCloud,
  FolderPlus,
  RefreshCw,
  Film,
  X,
  ChevronDown,
} from "lucide-react";
import { ModelStatus } from "../types";

interface HeaderProps {
  projectId: string;
  modelStatus: ModelStatus | null;
  apiHealthy: boolean;
  timePolicy: string;
  onTimePolicyToggle?: () => void;
  onModelConfigChange?: (provider: string, model?: string) => Promise<void>;
  activeTab: "editor" | "export";
  onTabChange: (tab: "editor" | "export") => void;
  isRendering?: boolean;
  canUndo?: boolean;
  canRedo?: boolean;
  undoCount?: number;
  redoCount?: number;
  onUndo?: () => void;
  onRedo?: () => void;
  onOpenAutoEdit?: () => void;
  onExportOtio?: () => void;
  onUploadMedia?: () => void;
  onNewProject?: () => void;
  onRefresh?: () => void;
  isMediaPanelOpen?: boolean;
  onToggleMediaPanel?: () => void;
  mediaCount?: number;
}

export const Header: React.FC<HeaderProps> = ({
  projectId,
  modelStatus,
  apiHealthy,
  timePolicy,
  onTimePolicyToggle,
  onModelConfigChange,
  activeTab,
  onTabChange,
  isRendering = false,
  canUndo = false,
  canRedo = false,
  undoCount = 0,
  redoCount = 0,
  onUndo,
  onRedo,
  onOpenAutoEdit,
  onExportOtio,
  onUploadMedia,
  onNewProject,
  onRefresh,
  isMediaPanelOpen = true,
  onToggleMediaPanel,
  mediaCount,
}) => {
  const [isConfigOpen, setIsConfigOpen] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<string>(modelStatus?.active_provider || "ollama");
  const [selectedModel, setSelectedModel] = useState<string>(modelStatus?.model || "qwen2.5:1.5b");
  const [isUpdating, setIsUpdating] = useState(false);
  const [showToolsMenu, setShowToolsMenu] = useState(false);

  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!onModelConfigChange) return;
    setIsUpdating(true);
    try {
      await onModelConfigChange(selectedProvider, selectedModel);
      setIsConfigOpen(false);
    } finally {
      setIsUpdating(false);
    }
  };

  const getProviderLabel = () => {
    if (!modelStatus) return "Connecting...";
    if (modelStatus.active_provider === "ollama") {
      return `Ollama: ${modelStatus.model || "Qwen"}`;
    }
    if (modelStatus.active_provider === "gemini") {
      return "Gemini NLU";
    }
    return "Rule Engine";
  };

  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 50,
        backgroundColor: "rgba(11, 15, 25, 0.78)",
        backdropFilter: "blur(24px) saturate(190%)",
        WebkitBackdropFilter: "blur(24px) saturate(190%)",
        borderBottom: "1px solid var(--color-border-gloss)",
        boxShadow: "0 8px 32px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.15)",
        padding: "8px 20px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "16px",
      }}
    >
      {/* LEFT: Brand Identity & Active Project Pill */}
      <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
        {/* Glowing Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div
            style={{
              width: "34px",
              height: "34px",
              borderRadius: "10px",
              background: "linear-gradient(135deg, #10B981 0%, #047857 100%)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow: "0 0 16px rgba(16, 185, 129, 0.4), inset 0 1px 1px rgba(255, 255, 255, 0.4)",
              color: "#FFFFFF",
            }}
          >
            <Layers size={18} />
          </div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span
                style={{
                  fontWeight: 800,
                  fontSize: "16px",
                  letterSpacing: "-0.02em",
                  background: "linear-gradient(180deg, #FFFFFF 0%, #CBD5E1 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                }}
              >
                IncuBrix
              </span>
              <span
                style={{
                  fontSize: "10px",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  padding: "2px 6px",
                  borderRadius: "9999px",
                  background: "rgba(16, 185, 129, 0.15)",
                  color: "#34D399",
                  border: "1px solid rgba(16, 185, 129, 0.3)",
                }}
              >
                Studio
              </span>
            </div>
          </div>
        </div>

        {/* Project Pill */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            backgroundColor: "rgba(255, 255, 255, 0.04)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "var(--radius-full)",
            padding: "4px 12px",
            boxShadow: "inset 0 1px 0 rgba(255, 255, 255, 0.1)",
          }}
        >
          <span style={{ fontSize: "11.5px", color: "var(--color-text-muted)" }}>Project:</span>
          <span
            className="mono"
            style={{
              fontSize: "12px",
              fontWeight: 600,
              color: "var(--color-text-main)",
            }}
          >
            {projectId}
          </span>
        </div>

        {/* Live Connectivity Pulse */}
        <div
          title={apiHealthy ? "API Service Connected" : "API Service Disconnected"}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            padding: "4px 10px",
            borderRadius: "var(--radius-full)",
            backgroundColor: "rgba(255, 255, 255, 0.03)",
            border: "1px solid var(--color-border)",
            fontSize: "11px",
            color: apiHealthy ? "#34D399" : "#F43F5E",
          }}
        >
          <span
            style={{
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              backgroundColor: apiHealthy ? "#10B981" : "#F43F5E",
              boxShadow: apiHealthy ? "0 0 8px #10B981" : "0 0 8px #F43F5E",
            }}
          />
          <span style={{ fontWeight: 600 }}>{apiHealthy ? "Live" : "Offline"}</span>
        </div>

        {/* Media Panel Toggle Button */}
        {onToggleMediaPanel && (
          <button
            onClick={onToggleMediaPanel}
            title={isMediaPanelOpen ? "Hide Media Assets Panel" : "Show Media Assets Panel"}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              padding: "4px 11px",
              borderRadius: "var(--radius-full)",
              backgroundColor: isMediaPanelOpen ? "rgba(16, 185, 129, 0.16)" : "rgba(255, 255, 255, 0.04)",
              border: isMediaPanelOpen ? "1px solid rgba(16, 185, 129, 0.45)" : "1px solid var(--color-border)",
              color: isMediaPanelOpen ? "#34D399" : "var(--color-text-secondary)",
              cursor: "pointer",
              fontSize: "11.5px",
              fontWeight: 600,
              boxShadow: isMediaPanelOpen ? "0 0 10px rgba(16, 185, 129, 0.2)" : "none",
              transition: "all 0.15s ease",
            }}
          >
            <Film size={12} style={{ color: isMediaPanelOpen ? "#10B981" : "inherit" }} />
            <span>Media Library</span>
            {mediaCount !== undefined && (
              <span
                style={{
                  fontSize: "10px",
                  fontWeight: 700,
                  padding: "1px 6px",
                  borderRadius: "9999px",
                  backgroundColor: isMediaPanelOpen ? "rgba(16, 185, 129, 0.25)" : "rgba(255, 255, 255, 0.1)",
                  color: isMediaPanelOpen ? "#A7F3D0" : "var(--color-text-muted)",
                }}
              >
                {mediaCount}
              </span>
            )}
          </button>
        )}
      </div>

      {/* CENTER: Minimalist Glossy Mode Segment Switcher */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          backgroundColor: "rgba(8, 12, 20, 0.8)",
          borderRadius: "var(--radius-full)",
          padding: "3px",
          border: "1px solid var(--color-border-gloss)",
          boxShadow: "inset 0 1px 2px rgba(0, 0, 0, 0.6), 0 4px 16px rgba(0, 0, 0, 0.4)",
        }}
      >
        <button
          onClick={() => onTabChange("editor")}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "7px",
            padding: "6px 16px",
            fontSize: "12.5px",
            fontWeight: activeTab === "editor" ? 600 : 500,
            borderRadius: "var(--radius-full)",
            border: activeTab === "editor" ? "1px solid rgba(255, 255, 255, 0.2)" : "1px solid transparent",
            background:
              activeTab === "editor"
                ? "linear-gradient(180deg, rgba(255, 255, 255, 0.14) 0%, rgba(255, 255, 255, 0.03) 100%)"
                : "transparent",
            color: activeTab === "editor" ? "#FFFFFF" : "var(--color-text-secondary)",
            boxShadow:
              activeTab === "editor"
                ? "inset 0 1px 0 rgba(255, 255, 255, 0.25), 0 4px 12px rgba(0, 0, 0, 0.3)"
                : "none",
            cursor: "pointer",
            transition: "all 0.18s ease",
          }}
        >
          <Film size={14} style={{ color: activeTab === "editor" ? "#34D399" : "inherit" }} />
          <span>Editor Studio</span>
        </button>

        <button
          onClick={() => onTabChange("export")}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "7px",
            padding: "6px 16px",
            fontSize: "12.5px",
            fontWeight: activeTab === "export" ? 600 : 500,
            borderRadius: "var(--radius-full)",
            border: activeTab === "export" ? "1px solid rgba(255, 255, 255, 0.2)" : "1px solid transparent",
            background:
              activeTab === "export"
                ? "linear-gradient(180deg, rgba(255, 255, 255, 0.14) 0%, rgba(255, 255, 255, 0.03) 100%)"
                : "transparent",
            color: activeTab === "export" ? "#FFFFFF" : "var(--color-text-secondary)",
            boxShadow:
              activeTab === "export"
                ? "inset 0 1px 0 rgba(255, 255, 255, 0.25), 0 4px 12px rgba(0, 0, 0, 0.3)"
                : "none",
            cursor: "pointer",
            transition: "all 0.18s ease",
          }}
        >
          <Download size={14} style={{ color: activeTab === "export" ? "#34D399" : "inherit" }} />
          <span>Export & Delivery</span>
          {isRendering && (
            <span
              style={{
                fontSize: "10px",
                fontWeight: 700,
                padding: "2px 6px",
                borderRadius: "var(--radius-full)",
                background: "linear-gradient(135deg, #F59E0B 0%, #D97706 100%)",
                color: "#FFFFFF",
                boxShadow: "0 0 10px rgba(245, 158, 11, 0.5)",
              }}
            >
              Rendering
            </span>
          )}
        </button>
      </div>

      {/* RIGHT: Quick Action Tools & Model Settings */}
      <div style={{ display: "flex", alignItems: "center", gap: "9px" }}>
        {/* Reference Clock Policy Toggle */}
        <button
          onClick={onTimePolicyToggle}
          title="Toggle reference clock time policy"
          style={{
            background: "linear-gradient(180deg, rgba(255, 255, 255, 0.06) 0%, rgba(255, 255, 255, 0.01) 100%)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-full)",
            padding: "5px 11px",
            display: "flex",
            alignItems: "center",
            gap: "5px",
            fontSize: "11.5px",
            color: "var(--color-text-secondary)",
            cursor: "pointer",
            boxShadow: "inset 0 1px 0 rgba(255, 255, 255, 0.1)",
            transition: "all 0.15s ease",
          }}
        >
          <Clock size={12} style={{ color: "#10B981" }} />
          <span style={{ fontWeight: 500 }}>
            {timePolicy === "current_edited_time" ? "Edited Time" : "Source Time"}
          </span>
        </button>

        {/* AI Model Badge & Config Trigger */}
        <button
          onClick={() => {
            setSelectedProvider(modelStatus?.active_provider || "ollama");
            setSelectedModel(modelStatus?.model || "qwen2.5:1.5b");
            setIsConfigOpen(true);
          }}
          title="Click to configure AI Model provider"
          style={{
            background: "linear-gradient(180deg, rgba(255, 255, 255, 0.06) 0%, rgba(255, 255, 255, 0.01) 100%)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-full)",
            padding: "5px 11px",
            display: "flex",
            alignItems: "center",
            gap: "6px",
            fontSize: "11.5px",
            color: "var(--color-text-main)",
            cursor: "pointer",
            boxShadow: "inset 0 1px 0 rgba(255, 255, 255, 0.1)",
            transition: "all 0.15s ease",
          }}
        >
          <Cpu size={12} style={{ color: modelStatus?.connected ? "#10B981" : "#F59E0B" }} />
          <span style={{ fontWeight: 600 }}>{getProviderLabel()}</span>
          <span
            style={{
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              backgroundColor: modelStatus?.connected ? "#10B981" : "#F59E0B",
              boxShadow: modelStatus?.connected ? "0 0 6px #10B981" : "0 0 6px #F59E0B",
            }}
          />
        </button>

        <div style={{ width: "1px", height: "18px", backgroundColor: "rgba(255, 255, 255, 0.1)" }} />

        {/* Auto Edit Action Button */}
        {onOpenAutoEdit && (
          <button
            className="btn-primary"
            onClick={onOpenAutoEdit}
            title="Clean Up Video (removes silence & fillers, auto captions, ducked music)"
            style={{ padding: "5px 12px", fontSize: "12px" }}
          >
            <Sparkles size={13} />
            <span>Auto Edit</span>
          </button>
        )}

        {/* Undo / Redo Segmented Pill */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            backgroundColor: "rgba(255, 255, 255, 0.05)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-md)",
            overflow: "hidden",
            boxShadow: "inset 0 1px 0 rgba(255, 255, 255, 0.1)",
          }}
        >
          <button
            onClick={onUndo}
            disabled={!canUndo}
            title={canUndo ? `Undo edit (${undoCount} available)` : "Nothing to undo"}
            style={{
              background: "none",
              border: "none",
              color: canUndo ? "var(--color-text-main)" : "var(--color-text-muted)",
              padding: "5px 8px",
              display: "flex",
              alignItems: "center",
              gap: "4px",
              cursor: canUndo ? "pointer" : "not-allowed",
              fontSize: "11px",
              transition: "background 0.15s ease",
            }}
          >
            <Undo2 size={13} />
            {undoCount > 0 && <span style={{ fontWeight: 700 }}>{undoCount}</span>}
          </button>
          <div style={{ width: "1px", height: "14px", backgroundColor: "rgba(255, 255, 255, 0.1)" }} />
          <button
            onClick={onRedo}
            disabled={!canRedo}
            title={canRedo ? `Redo edit (${redoCount} available)` : "Nothing to redo"}
            style={{
              background: "none",
              border: "none",
              color: canRedo ? "var(--color-text-main)" : "var(--color-text-muted)",
              padding: "5px 8px",
              display: "flex",
              alignItems: "center",
              gap: "4px",
              cursor: canRedo ? "pointer" : "not-allowed",
              fontSize: "11px",
              transition: "background 0.15s ease",
            }}
          >
            <Redo2 size={13} />
            {redoCount > 0 && <span style={{ fontWeight: 700 }}>{redoCount}</span>}
          </button>
        </div>

        {/* Utilities Menu Dropdown Toggle */}
        <div style={{ position: "relative" }}>
          <button
            className="btn-secondary"
            onClick={() => setShowToolsMenu((v) => !v)}
            title="More Studio Tools"
            style={{ padding: "5px 9px", fontSize: "11.5px", gap: "4px" }}
          >
            <span>Tools</span>
            <ChevronDown size={12} />
          </button>

          {showToolsMenu && (
            <div
              style={{
                position: "absolute",
                top: "calc(100% + 8px)",
                right: 0,
                width: "190px",
                backgroundColor: "rgba(14, 20, 32, 0.95)",
                backdropFilter: "blur(20px)",
                WebkitBackdropFilter: "blur(20px)",
                border: "1px solid var(--color-border-gloss)",
                borderRadius: "var(--radius-md)",
                boxShadow: "0 12px 32px rgba(0, 0, 0, 0.6), inset 0 1px 0 rgba(255, 255, 255, 0.15)",
                padding: "6px",
                zIndex: 100,
                display: "flex",
                flexDirection: "column",
                gap: "2px",
              }}
            >
              <button
                className="btn-secondary"
                onClick={() => {
                  setShowToolsMenu(false);
                  onUploadMedia?.();
                }}
                style={{
                  width: "100%",
                  justifyContent: "flex-start",
                  border: "none",
                  background: "none",
                  boxShadow: "none",
                  padding: "7px 10px",
                  fontSize: "12px",
                }}
              >
                <UploadCloud size={14} style={{ color: "#34D399" }} />
                <span>Upload Local Video</span>
              </button>

              <button
                className="btn-secondary"
                onClick={() => {
                  setShowToolsMenu(false);
                  onExportOtio?.();
                }}
                style={{
                  width: "100%",
                  justifyContent: "flex-start",
                  border: "none",
                  background: "none",
                  boxShadow: "none",
                  padding: "7px 10px",
                  fontSize: "12px",
                }}
              >
                <Download size={14} style={{ color: "#60A5FA" }} />
                <span>Export OTIO Timeline</span>
              </button>

              <button
                className="btn-secondary"
                onClick={() => {
                  setShowToolsMenu(false);
                  onNewProject?.();
                }}
                style={{
                  width: "100%",
                  justifyContent: "flex-start",
                  border: "none",
                  background: "none",
                  boxShadow: "none",
                  padding: "7px 10px",
                  fontSize: "12px",
                }}
              >
                <FolderPlus size={14} style={{ color: "#F59E0B" }} />
                <span>Reset to Demo Project</span>
              </button>

              <div style={{ height: "1px", backgroundColor: "rgba(255, 255, 255, 0.08)", margin: "4px 0" }} />

              <button
                className="btn-secondary"
                onClick={() => {
                  setShowToolsMenu(false);
                  onRefresh?.();
                }}
                style={{
                  width: "100%",
                  justifyContent: "flex-start",
                  border: "none",
                  background: "none",
                  boxShadow: "none",
                  padding: "7px 10px",
                  fontSize: "12px",
                }}
              >
                <RefreshCw size={14} style={{ color: "var(--color-text-secondary)" }} />
                <span>Refresh Timeline</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Model Configuration Modal */}
      {isConfigOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0,0,0,0.7)",
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={() => setIsConfigOpen(false)}
        >
          <div
            className="panel"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "460px",
              padding: "22px",
              boxShadow: "var(--shadow-lg)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <Cpu size={18} style={{ color: "var(--color-accent-primary)" }} />
                <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "var(--color-text-main)" }}>
                  AI Model Configuration
                </h3>
              </div>
              <button className="btn-icon" onClick={() => setIsConfigOpen(false)}>
                <X size={14} />
              </button>
            </div>

            <form onSubmit={handleSaveConfig} style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
              <div>
                <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "6px" }}>
                  Active NLU Provider
                </label>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                  <button
                    type="button"
                    onClick={() => setSelectedProvider("ollama")}
                    className={`btn-secondary ${selectedProvider === "ollama" ? "active" : ""}`}
                    style={{
                      padding: "8px",
                      fontSize: "12px",
                      fontWeight: 600,
                      backgroundColor: selectedProvider === "ollama" ? "var(--color-selected-bg)" : undefined,
                      borderColor: selectedProvider === "ollama" ? "var(--color-accent-primary)" : undefined,
                      color: selectedProvider === "ollama" ? "var(--color-accent-primary)" : undefined,
                    }}
                  >
                    <span>🦙 Ollama (Local)</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setSelectedProvider("semantic_rule")}
                    className={`btn-secondary ${selectedProvider === "semantic_rule" ? "active" : ""}`}
                    style={{
                      padding: "8px",
                      fontSize: "12px",
                      fontWeight: 600,
                      backgroundColor: selectedProvider === "semantic_rule" ? "var(--color-selected-bg)" : undefined,
                      borderColor: selectedProvider === "semantic_rule" ? "var(--color-accent-primary)" : undefined,
                      color: selectedProvider === "semantic_rule" ? "var(--color-accent-primary)" : undefined,
                    }}
                  >
                    <span>⚡ Semantic Rules</span>
                  </button>
                </div>
              </div>

              {selectedProvider === "ollama" && (
                <div>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "6px" }}>
                    Ollama Model Name
                  </label>
                  <input
                    type="text"
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                    placeholder="e.g. qwen2.5:1.5b, llama3.2"
                    style={{
                      width: "100%",
                      padding: "8px 10px",
                      fontSize: "13px",
                    }}
                  />
                </div>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "8px" }}>
                <button type="button" className="btn-secondary" onClick={() => setIsConfigOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary" disabled={isUpdating}>
                  {isUpdating ? "Connecting..." : "Save & Connect"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </header>
  );
};
