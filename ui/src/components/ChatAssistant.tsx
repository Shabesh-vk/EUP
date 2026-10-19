import React, { useState, useRef, useEffect } from "react";
import { Send, Bot, User, AlertCircle, CheckCircle2, HelpCircle } from "lucide-react";
import { ChatMessage } from "../types";

interface ChatAssistantProps {
  projectId: string;
  messages: ChatMessage[];
  onSendMessage: (text: string) => void;
  isLoading: boolean;
  onOptionClick: (optionText: string) => void;
}

export const ChatAssistant: React.FC<ChatAssistantProps> = ({
  projectId: _projectId,
  messages,
  onSendMessage,
  isLoading,
  onOptionClick,
}) => {
  const [inputText, setInputText] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const quickActions = [
    { label: "Clean Up", prompt: "clean up video" },
    { label: "Add Captions", prompt: "add captions to the video" },
    { label: "Make them bigger", prompt: "make them bigger" },
    { label: "Change to yellow", prompt: "change them to yellow" },
    { label: "Undo", prompt: "undo" },
    { label: "What did you change?", prompt: "what did you change?" },
  ];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = inputText.trim();
    if (!trimmed || isLoading) return;
    onSendMessage(trimmed);
    setInputText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden",
      }}
    >
      {/* Quick Action Chips */}
      <div
        style={{
          padding: "8px 12px",
          borderBottom: "1px solid var(--color-border-subtle)",
          backgroundColor: "rgba(10, 14, 24, 0.6)",
          display: "flex",
          gap: "6px",
          overflowX: "auto",
          whiteSpace: "nowrap",
        }}
      >
        {quickActions.map((action) => (
          <button
            key={action.label}
            className="chip"
            onClick={() => onSendMessage(action.prompt)}
            disabled={isLoading}
            style={{ fontSize: "11px", padding: "3px 9px" }}
          >
            <span>{action.label}</span>
          </button>
        ))}
      </div>

      {/* Message History Container */}
      <div
        style={{
          flex: 1,
          padding: "14px",
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: "12px",
        }}
      >
        {messages.length === 0 ? (
          <div
            style={{
              textAlign: "center",
              color: "var(--color-text-muted)",
              marginTop: "40px",
              padding: "0 20px",
            }}
          >
            <Bot size={32} style={{ opacity: 0.35, marginBottom: "8px", color: "var(--color-accent-primary)" }} />
            <div style={{ fontWeight: 600, fontSize: "13px", color: "var(--color-text-main)" }}>
              Natural Language Video Copilot
            </div>
            <div style={{ fontSize: "12px", marginTop: "4px", lineHeight: "1.5" }}>
              Give prompt instructions like <em>"clean up the video"</em>, <em>"add yellow captions"</em>, or <em>"speed up silence 2x"</em>.
            </div>
          </div>
        ) : (
          messages.map((msg) => {
            const isUser = msg.role === "user";
            const meta = msg.metadata;

            return (
              <div
                key={msg.id}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: isUser ? "flex-end" : "flex-start",
                  gap: "4px",
                }}
              >
                {/* Role & Timestamp */}
                <div style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "10.5px", color: "var(--color-text-muted)" }}>
                  {isUser ? <User size={10} /> : <Bot size={10} style={{ color: "#34D399" }} />}
                  <span>{isUser ? "You" : "IncuBrix Copilot"}</span>
                </div>

                {/* Message Bubble */}
                <div
                  style={{
                    maxWidth: "88%",
                    padding: "9px 13px",
                    borderRadius: "var(--radius-lg)",
                    backgroundColor: isUser
                      ? "rgba(16, 185, 129, 0.22)"
                      : "rgba(255, 255, 255, 0.04)",
                    color: isUser ? "#FFFFFF" : "var(--color-text-main)",
                    border: isUser
                      ? "1px solid rgba(16, 185, 129, 0.45)"
                      : "1px solid var(--color-border)",
                    boxShadow: isUser
                      ? "inset 0 1px 0 rgba(255, 255, 255, 0.25), 0 4px 14px rgba(16, 185, 129, 0.15)"
                      : "inset 0 1px 0 rgba(255, 255, 255, 0.08), 0 4px 12px rgba(0, 0, 0, 0.25)",
                    fontSize: "12.5px",
                    lineHeight: "1.45",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {msg.content}

                  {/* Status Indicator Badges */}
                  {meta?.status && (
                    <div
                      style={{
                        marginTop: "6px",
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                        fontSize: "11px",
                        fontWeight: 600,
                        color:
                          meta.status === "applied"
                            ? "#34D399"
                            : meta.status === "needs_clarification"
                            ? "#F59E0B"
                            : "#F43F5E",
                      }}
                    >
                      {meta.status === "applied" && <CheckCircle2 size={12} />}
                      {meta.status === "needs_clarification" && <HelpCircle size={12} />}
                      {meta.status === "rejected" && <AlertCircle size={12} />}
                      <span>
                        {meta.status === "applied"
                          ? "Applied"
                          : meta.status === "needs_clarification"
                          ? "Needs Clarification"
                          : "Rejected"}
                      </span>
                    </div>
                  )}

                  {/* Clarification Pills / Options */}
                  {meta?.options && meta.options.length > 0 && (
                    <div
                      style={{
                        marginTop: "8px",
                        display: "flex",
                        flexDirection: "column",
                        gap: "5px",
                      }}
                    >
                      {meta.options.map((option, idx) => (
                        <button
                          key={idx}
                          onClick={() => onOptionClick(option)}
                          className="btn-secondary"
                          style={{
                            textAlign: "left",
                            fontSize: "11.5px",
                            padding: "6px 10px",
                            borderColor: "var(--color-border-gloss)",
                            backgroundColor: "rgba(255, 255, 255, 0.06)",
                          }}
                        >
                          {option}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Warnings if any */}
                  {meta?.warnings && meta.warnings.length > 0 && (
                    <div
                      style={{
                        marginTop: "6px",
                        fontSize: "11px",
                        color: "#F59E0B",
                      }}
                    >
                      {meta.warnings.map((w, i) => (
                        <div key={i}>⚠️ {w}</div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}

        {isLoading && (
          <div style={{ display: "flex", alignItems: "center", gap: "6px", color: "var(--color-text-muted)", fontSize: "11.5px" }}>
            <Bot size={13} className="spin" style={{ color: "var(--color-accent-primary)" }} />
            <span>Understanding instruction and planning edit...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Box */}
      <form
        onSubmit={handleSubmit}
        style={{
          padding: "10px 12px",
          borderTop: "1px solid var(--color-border)",
          backgroundColor: "rgba(10, 14, 24, 0.8)",
          display: "flex",
          gap: "8px",
          alignItems: "flex-end",
        }}
      >
        <textarea
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type an editing instruction (e.g. 'cut 0 to 5s', 'add captions')..."
          rows={2}
          style={{
            flex: 1,
            padding: "8px 10px",
            fontSize: "12.5px",
            resize: "none",
          }}
        />

        <button
          type="submit"
          className="btn-primary"
          disabled={!inputText.trim() || isLoading}
          style={{ height: "38px", padding: "0 12px" }}
        >
          <Send size={14} />
        </button>
      </form>
    </div>
  );
};
