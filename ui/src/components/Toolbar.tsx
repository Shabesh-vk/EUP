import React from "react";
import { Sparkles, Undo2, Redo2, Download, FolderPlus, UploadCloud, RefreshCw, ArrowRight } from "lucide-react";

interface ToolbarProps {
  canUndo: boolean;
  canRedo: boolean;
  undoCount: number;
  redoCount: number;
  onUndo: () => void;
  onRedo: () => void;
  onOpenAutoEdit: () => void;
  onNavigateExport: () => void;
  onExportOtio: () => void;
  onNewProject: () => void;
  onUploadMedia: () => void;
  onRefresh: () => void;
}

export const Toolbar: React.FC<ToolbarProps> = ({
  canUndo,
  canRedo,
  undoCount,
  redoCount,
  onUndo,
  onRedo,
  onOpenAutoEdit,
  onNavigateExport,
  onExportOtio,
  onNewProject,
  onUploadMedia,
  onRefresh,
}) => {
  return (
    <div
      style={{
        backgroundColor: "var(--color-surface-panel)",
        borderBottom: "1px solid var(--color-border)",
        padding: "8px 20px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "12px",
        flexWrap: "wrap",
      }}
    >
      {/* Primary Action Tools: Auto Edit & Linear Undo/Redo */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <button
          className="btn-primary"
          onClick={onOpenAutoEdit}
          title="Review and apply conservative Clean Up preset (silence trimming, filler removal, auto captions, ducked music)"
        >
          <Sparkles size={15} />
          <span>Auto Edit</span>
        </button>

        <div style={{ width: "1px", height: "20px", backgroundColor: "var(--color-border)", margin: "0 4px" }} />

        {/* Linear Undo / Redo */}
        <button
          className="btn-secondary"
          onClick={onUndo}
          disabled={!canUndo}
          title={canUndo ? `Undo last edit (${undoCount} available)` : "Nothing to undo"}
        >
          <Undo2 size={14} />
          <span>Undo</span>
          {undoCount > 0 && (
            <span
              style={{
                fontSize: "11px",
                backgroundColor: "var(--color-surface-inset)",
                padding: "1px 5px",
                borderRadius: "var(--radius-full)",
              }}
            >
              {undoCount}
            </span>
          )}
        </button>

        <button
          className="btn-secondary"
          onClick={onRedo}
          disabled={!canRedo}
          title={canRedo ? `Redo edit (${redoCount} available)` : "Nothing to redo"}
        >
          <Redo2 size={14} />
          <span>Redo</span>
          {redoCount > 0 && (
            <span
              style={{
                fontSize: "11px",
                backgroundColor: "var(--color-surface-inset)",
                padding: "1px 5px",
                borderRadius: "var(--radius-full)",
              }}
            >
              {redoCount}
            </span>
          )}
        </button>
      </div>

      {/* Secondary Project Actions & Navigation to Export */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <button
          className="btn-secondary"
          onClick={onExportOtio}
          title="Export OpenTimelineIO (.otio) interchange format for non-linear editors"
        >
          <Download size={14} />
          <span>Export OTIO</span>
        </button>

        <button
          className="btn-secondary"
          onClick={onUploadMedia}
          title="Upload local MP4/MOV video into a new or active project"
        >
          <UploadCloud size={14} />
          <span>Upload Media</span>
        </button>

        <button
          className="btn-secondary"
          onClick={onNewProject}
          title="Load demo interview project (Worked Example)"
        >
          <FolderPlus size={14} />
          <span>Reset / Demo</span>
        </button>

        <button
          className="btn-icon"
          onClick={onRefresh}
          title="Refresh timeline state"
        >
          <RefreshCw size={15} />
        </button>

        <div style={{ width: "1px", height: "20px", backgroundColor: "var(--color-border)", margin: "0 4px" }} />

        {/* Separate Export Studio Button */}
        <button
          className="btn-primary"
          onClick={onNavigateExport}
          title="Open the dedicated Export & Delivery Studio for master video rendering and formats"
          style={{ padding: "6px 14px", fontSize: "13px" }}
        >
          <span>Export & Delivery</span>
          <ArrowRight size={14} />
        </button>
      </div>
    </div>
  );
};
