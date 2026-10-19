import { useState, useEffect, useCallback } from "react";
import { Header } from "./components/Header";
import { VideoPreview } from "./components/VideoPreview";
import { TimelineView } from "./components/TimelineView";
import { StudioDock } from "./components/StudioDock";
import { AutoEditModal } from "./components/AutoEditModal";
import { ExportStudio } from "./components/ExportStudio";
import { MediaPanel } from "./components/MediaPanel";
import {
  Timeline,
  ChatMessage,
  ModelStatus,
  AutoEditPlan,
  EngineResponse,
} from "./types";

export default function App() {
  const [projectId, setProjectId] = useState<string>("proj_interview_001");
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [currentTime, setCurrentTime] = useState<number>(0);

  // Top-Level Navigation View: "editor" (Workspace) vs "export" (Export & Delivery)
  const [activeTab, setActiveTab] = useState<"editor" | "export">("editor");

  // Separate Media Panel state
  const [isMediaPanelOpen, setIsMediaPanelOpen] = useState<boolean>(true);
  const [mediaCount, setMediaCount] = useState<number>(0);

  // Status & Health
  const [apiHealthy, setApiHealthy] = useState<boolean>(false);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [timePolicy, setTimePolicy] = useState<string>("current_edited_time");

  // Chat & Assistant
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [isProcessingPrompt, setIsProcessingPrompt] = useState<boolean>(false);

  // Manual Editing Operation State
  const [isApplyingOp, setIsApplyingOp] = useState<boolean>(false);

  // Auto Edit Modal State
  const [autoEditPlan, setAutoEditPlan] = useState<AutoEditPlan | null>(null);
  const [isApplyingAutoEdit, setIsApplyingAutoEdit] = useState<boolean>(false);

  // Rendering & Preview State
  const [isRendering, setIsRendering] = useState<boolean>(false);
  const [renderedVideoUrl, setRenderedVideoUrl] = useState<string | null>(null);
  const [sourceVideoUrl, setSourceVideoUrl] = useState<string | null>(null);
  const [renderedTimelineHash, setRenderedTimelineHash] = useState<string | null>(null);

  // History & Undo State
  const [isRestoring, setIsRestoring] = useState<boolean>(false);
  const [isTranscribing, setIsTranscribing] = useState<boolean>(false);

  // Helper to normalize backend asset URLs
  const formatAssetUrl = (url?: string | null) => {
    if (!url) return null;
    if (url.startsWith("http://localhost") || url.startsWith("http://127.0.0.1")) {
      try {
        const parsed = new URL(url);
        return parsed.pathname;
      } catch {
        return url;
      }
    }
    return url;
  };

  // 1. Check API Health and Model Status
  const checkHealth = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/health");
      setApiHealthy(res.ok);
    } catch {
      setApiHealthy(false);
    }

    try {
      const resModel = await fetch("/api/v1/model/status");
      if (resModel.ok) {
        const data = await resModel.json();
        setModelStatus(data);
      }
    } catch {
      setModelStatus(null);
    }
  }, []);

  // 2. Fetch Project Timeline
  const loadTimeline = useCallback(async (pid: string) => {
    try {
      const res = await fetch(`/api/v1/projects/${pid}/timeline?t=${Date.now()}`);
      if (res.ok) {
        const data: Timeline = await res.json();
        setTimeline(data);
        setSourceVideoUrl(`/api/v1/projects/${pid}/source-media?v=${Date.now()}`);
      } else if (res.status === 404) {
        // Project doesn't exist yet, create demo project
        createDemoProject(pid);
      }
    } catch (err) {
      console.error("Failed to load timeline:", err);
    }
  }, []);

  // 2b. Fetch Media Library Count
  const refreshMediaCount = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/media");
      if (res.ok) {
        const data = await res.json();
        setMediaCount(data.media?.length || 0);
      }
    } catch (err) {
      console.error("Failed to fetch media count:", err);
    }
  }, []);

  // 3. Fetch SQLite Chat History
  const loadChatHistory = useCallback(async (pid: string) => {
    try {
      const res = await fetch(`/api/v1/projects/${pid}/chat`);
      if (res.ok) {
        const data = await res.json();
        setChatMessages(data.messages || []);
      }
    } catch (err) {
      console.error("Failed to load chat history:", err);
    }
  }, []);

  // 4. Create Demo Interview Project
  const createDemoProject = async (pid: string) => {
    try {
      const form = new FormData();
      form.append("project_id", pid);
      form.append("stt_mode", "mock");

      const res = await fetch("/api/v1/projects/create", {
        method: "POST",
        body: form,
      });

      if (res.ok) {
        const data = await res.json();
        const activePid = data.project_id || pid;
        setProjectId(activePid);
        await loadTimeline(activePid);
        await loadChatHistory(activePid);
        await refreshMediaCount();
      }
    } catch (err) {
      console.error("Failed to create demo project:", err);
    }
  };

  useEffect(() => {
    checkHealth();
    refreshMediaCount();
    loadTimeline(projectId);
    loadChatHistory(projectId);
  }, [projectId, checkHealth, refreshMediaCount, loadTimeline, loadChatHistory]);

  // Handle Natural Language Instruction / Chat
  const handleSendMessage = async (text: string) => {
    if (!text.trim() || isProcessingPrompt) return;
    setIsProcessingPrompt(true);

    const tempUserMsg: ChatMessage = {
      id: Date.now(),
      project_id: projectId,
      role: "user",
      content: text,
      created_at: Date.now() / 1000,
    };
    setChatMessages((prev) => [...prev, tempUserMsg]);

    try {
      const res = await fetch(`/api/v1/projects/${projectId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });

      if (res.ok) {
        const data = await res.json();
        const engineRes: EngineResponse = data.engine_response || data;

        const assistantMsg: ChatMessage = {
          id: Date.now() + 1,
          project_id: projectId,
          role: "assistant",
          content: engineRes.question || engineRes.summary || "Operation processed.",
          metadata: {
            status: engineRes.status,
            operations: engineRes.operations,
            timeline_hash: engineRes.timeline_hash,
            duration_s: engineRes.duration_s,
            question: engineRes.question,
            options: engineRes.options,
            warnings: engineRes.warnings,
            error: engineRes.error,
          },
          created_at: Date.now() / 1000,
        };

        setChatMessages((prev) => [...prev, assistantMsg]);
        await loadTimeline(projectId);
      } else {
        const errData = await res.json().catch(() => ({}));
        const errorMsg: ChatMessage = {
          id: Date.now() + 1,
          project_id: projectId,
          role: "assistant",
          content: `Error: ${errData.detail || "Instruction failed to process."}`,
          metadata: { status: "rejected" },
          created_at: Date.now() / 1000,
        };
        setChatMessages((prev) => [...prev, errorMsg]);
      }
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: Date.now() + 1,
        project_id: projectId,
        role: "assistant",
        content: `Network error: ${err.message}`,
        metadata: { status: "rejected" },
        created_at: Date.now() / 1000,
      };
      setChatMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsProcessingPrompt(false);
    }
  };

  // Handle Manual Direct Operation Execution (Split, Delete, Speed, Add Caption)
  const handleApplyOperation = async (opType: string, details: Record<string, any>, instruction?: string) => {
    setIsApplyingOp(true);
    try {
      const res = await fetch(`/api/v1/projects/${projectId}/operations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation_type: opType,
          details,
          instruction: instruction || `Manual ${opType}`,
        }),
      });

      if (res.ok) {
        await loadTimeline(projectId);
        await loadChatHistory(projectId);
      } else {
        const errData = await res.json().catch(() => ({}));
        alert(`Failed to apply operation: ${errData.detail || errData.message || "Unknown error"}`);
      }
    } catch (err: any) {
      alert(`Operation failed: ${err.message}`);
    } finally {
      setIsApplyingOp(false);
    }
  };

  // Handle Clarification Option Pill Click
  const handleOptionClick = (optionText: string) => {
    handleSendMessage(optionText);
  };

  // Undo / Redo
  const handleUndo = async () => {
    try {
      const res = await fetch(`/api/v1/projects/${projectId}/undo`, { method: "POST" });
      if (res.ok) {
        await loadTimeline(projectId);
        await loadChatHistory(projectId);
      }
    } catch (err) {
      console.error("Undo error:", err);
    }
  };

  const handleRedo = async () => {
    try {
      const res = await fetch(`/api/v1/projects/${projectId}/redo`, { method: "POST" });
      if (res.ok) {
        await loadTimeline(projectId);
        await loadChatHistory(projectId);
      }
    } catch (err) {
      console.error("Redo error:", err);
    }
  };

  // Selective Restore
  const handleSelectiveRestore = async (txId: string) => {
    setIsRestoring(true);
    try {
      const res = await fetch(`/api/v1/projects/${projectId}/transactions/${txId}/restore`, {
        method: "POST",
      });
      if (res.ok) {
        await loadTimeline(projectId);
        await loadChatHistory(projectId);
      }
    } catch (err) {
      console.error("Selective restore error:", err);
    } finally {
      setIsRestoring(false);
    }
  };

  // Auto Edit Workflow
  const handleOpenAutoEdit = async () => {
    try {
      const res = await fetch(`/api/v1/projects/${projectId}/auto-edit/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preset: "clean_up" }),
      });
      if (res.ok) {
        const plan: AutoEditPlan = await res.json();
        setAutoEditPlan(plan);
      }
    } catch (err) {
      console.error("Failed to generate auto edit plan:", err);
    }
  };

  const handleApplyAutoEdit = async (excludedItemIds: string[]) => {
    if (!autoEditPlan) return;
    setIsApplyingAutoEdit(true);
    try {
      const res = await fetch(`/api/v1/projects/${projectId}/auto-edit/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan: autoEditPlan,
          excluded_item_ids: excludedItemIds,
        }),
      });

      if (res.ok) {
        setAutoEditPlan(null);
        await loadTimeline(projectId);
        await loadChatHistory(projectId);
      }
    } catch (err) {
      console.error("Failed to apply auto edit plan:", err);
    } finally {
      setIsApplyingAutoEdit(false);
    }
  };

  // Render Preview / Master Workflow (real FFmpeg job polling)
  const handleRenderMaster = async (
    resolution: string = "1280x720",
    preset: string = "hq",
    burnSubtitles: boolean = true
  ) => {
    setIsRendering(true);
    try {
      const res = await fetch(`/api/v1/projects/${projectId}/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resolution,
          preset,
          burn_subtitles: burnSubtitles,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        const jobId = data.job_id;

        // Poll job status until done
        await new Promise<void>((resolve, reject) => {
          const pollInterval = setInterval(async () => {
            try {
              const jobRes = await fetch(`/api/v1/jobs/${jobId}`);
              if (jobRes.ok) {
                const jobData = await jobRes.json();
                if (jobData.status === "completed") {
                  clearInterval(pollInterval);
                  setIsRendering(false);
                  setRenderedVideoUrl(
                    formatAssetUrl(jobData.result_url) ||
                      `/api/v1/projects/${projectId}/media/render_preview.mp4`
                  );
                  setRenderedTimelineHash(timeline?.timeline_hash || null);
                  resolve();
                } else if (jobData.status === "failed") {
                  clearInterval(pollInterval);
                  setIsRendering(false);
                  alert(`Render failed: ${jobData.error}`);
                  reject(new Error(jobData.error));
                }
              }
            } catch (err) {
              clearInterval(pollInterval);
              setIsRendering(false);
              reject(err);
            }
          }, 1000);
        });
      } else {
        setIsRendering(false);
      }
    } catch (err) {
      console.error("Render request failed:", err);
      setIsRendering(false);
    }
  };

  // Export OTIO
  const handleExportOtio = () => {
    window.open(`/api/v1/projects/${projectId}/export/otio`, "_blank");
  };

  // Upload Media Modal / Input
  const handleUploadMedia = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "video/mp4,video/quicktime,video/webm";
    input.onchange = async (e: any) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const form = new FormData();
      const newPid = `proj_${Date.now().toString(36)}_${Math.random().toString(36).substring(2, 6)}`;
      form.append("project_id", newPid);
      form.append("video_file", file);
      form.append("file", file);
      form.append("transcription_mode", "auto");

      try {
        const res = await fetch("/api/v1/projects/create", {
          method: "POST",
          body: form,
        });
        if (res.ok) {
          const data = await res.json();
          const activePid = data.project_id || newPid;
          setProjectId(activePid);
          await loadTimeline(activePid);
          await loadChatHistory(activePid);
          await refreshMediaCount();
          setCurrentTime(0);
        } else {
          const errData = await res.json().catch(() => ({}));
          alert(`Upload failed: ${errData.detail || errData.message || res.statusText}`);
        }
      } catch (err: any) {
        console.error("Upload failed:", err);
        alert(`Upload error: ${err.message}`);
      }
    };
    input.click();
  };

  // Re-transcribe Project using Faster Whisper or Mock
  const handleTranscribeProject = async (mode: "real" | "mock" = "real") => {
    if (!projectId) return;
    setIsTranscribing(true);
    try {
      const res = await fetch(`/api/v1/projects/${projectId}/transcribe?mode=${mode}`, {
        method: "POST",
      });
      if (res.ok) {
        await loadTimeline(projectId);
      } else {
        const err = await res.json().catch(() => ({}));
        alert(`Transcription failed: ${err.message || err.detail || res.statusText}`);
      }
    } catch (err: any) {
      console.error("Transcription error:", err);
      alert(`Transcription error: ${err.message}`);
    } finally {
      setIsTranscribing(false);
    }
  };

  const handleModelConfigChange = async (provider: string, model?: string) => {
    try {
      const res = await fetch("/api/v1/model/configure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, model }),
      });
      if (res.ok) {
        await checkHealth();
      }
    } catch (err) {
      console.error("Failed to configure model:", err);
    }
  };

  const undoCount = timeline?.transactions?.filter((t) => t.status === "applied").length || 0;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        minHeight: "100vh",
        backgroundColor: "var(--color-bg-app)",
      }}
    >
      {/* 1. Unified Minimalist Glossy Header */}
      <Header
        projectId={projectId}
        modelStatus={modelStatus}
        apiHealthy={apiHealthy}
        timePolicy={timePolicy}
        onTimePolicyToggle={() =>
          setTimePolicy((p) => (p === "current_edited_time" ? "source_time" : "current_edited_time"))
        }
        onModelConfigChange={handleModelConfigChange}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        isRendering={isRendering}
        canUndo={undoCount > 0}
        canRedo={false}
        undoCount={undoCount}
        redoCount={0}
        onUndo={handleUndo}
        onRedo={handleRedo}
        onOpenAutoEdit={handleOpenAutoEdit}
        onExportOtio={handleExportOtio}
        onUploadMedia={handleUploadMedia}
        onNewProject={() => createDemoProject("proj_interview_001")}
        onRefresh={() => {
          loadTimeline(projectId);
          refreshMediaCount();
        }}
        isMediaPanelOpen={isMediaPanelOpen}
        onToggleMediaPanel={() => setIsMediaPanelOpen((v) => !v)}
        mediaCount={mediaCount}
      />

      {/* 2. Main Studio View */}
      {activeTab === "editor" ? (
        <main
          style={{
            flex: 1,
            display: "grid",
            gridTemplateColumns: isMediaPanelOpen
              ? "320px minmax(0, 1fr) 390px"
              : "minmax(0, 1fr) 390px",
            gap: "16px",
            padding: "16px 20px",
            maxWidth: "1920px",
            margin: "0 auto",
            width: "100%",
            boxSizing: "border-box",
            transition: "grid-template-columns 0.2s ease",
          }}
        >
          {/* SEPARATE DEDICATED MEDIA ASSETS PANEL */}
          {isMediaPanelOpen && (
            <div style={{ height: "calc(100vh - 90px)", position: "sticky", top: "72px" }}>
              <MediaPanel
                currentProjectId={projectId}
                onSelectProject={(newPid) => {
                  setProjectId(newPid);
                  loadTimeline(newPid);
                  loadChatHistory(newPid);
                }}
                onUploadMedia={handleUploadMedia}
                onClose={() => setIsMediaPanelOpen(false)}
                onMediaLoaded={setMediaCount}
              />
            </div>
          )}

          {/* CENTRAL WORKSPACE (Video Preview + Multi-Track Timeline) */}
          <div style={{ display: "flex", flexDirection: "column", gap: "16px", minWidth: 0 }}>
            {/* Zero-Render Real-Time Video Preview */}
            <VideoPreview
              timeline={timeline}
              renderedVideoUrl={renderedVideoUrl}
              sourceVideoUrl={sourceVideoUrl}
              currentTime={currentTime}
              onTimeUpdate={setCurrentTime}
              renderedTimelineHash={renderedTimelineHash}
              onReRender={() => handleRenderMaster("1280x720", "preview", true)}
              isRendering={isRendering}
            />

            {/* Interactive Multi-Track Visual Timeline with Direct Edit Tools */}
            <TimelineView
              timeline={timeline}
              currentTime={currentTime}
              onSeek={setCurrentTime}
              onApplyOperation={handleApplyOperation}
              isApplyingOp={isApplyingOp}
            />
          </div>

          {/* RIGHT: Unified Multi-Tool Glossy Side Dock (Copilot, Transcript, History, Specs) */}
          <div style={{ height: "calc(100vh - 90px)", position: "sticky", top: "72px" }}>
            <StudioDock
              projectId={projectId}
              timeline={timeline}
              chatMessages={chatMessages}
              onSendMessage={handleSendMessage}
              isLoading={isProcessingPrompt}
              onOptionClick={handleOptionClick}
              onSeek={setCurrentTime}
              onSelectiveRestore={handleSelectiveRestore}
              isRestoring={isRestoring}
              onSelectProject={(newPid) => {
                setProjectId(newPid);
                loadTimeline(newPid);
                loadChatHistory(newPid);
              }}
              onUploadMedia={handleUploadMedia}
              onTranscribe={handleTranscribeProject}
              isTranscribing={isTranscribing}
            />
          </div>
        </main>
      ) : (
        /* Dedicated Export & Delivery Studio View */
        <ExportStudio
          projectId={projectId}
          timeline={timeline}
          renderedVideoUrl={renderedVideoUrl}
          renderedTimelineHash={renderedTimelineHash}
          isRendering={isRendering}
          onRenderMaster={handleRenderMaster}
          onExportOtio={handleExportOtio}
          onBackToEditor={() => setActiveTab("editor")}
        />
      )}

      {/* Auto Edit Review Modal */}
      {autoEditPlan && (
        <AutoEditModal
          plan={autoEditPlan}
          onClose={() => setAutoEditPlan(null)}
          onApply={handleApplyAutoEdit}
          isApplying={isApplyingAutoEdit}
        />
      )}
    </div>
  );
}
