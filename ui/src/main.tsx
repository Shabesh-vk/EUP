import React, { Component, ErrorInfo, ReactNode } from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.tsx';
import './index.css';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught render error:", error, errorInfo);
    this.setState({ error, errorInfo });
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: "40px", fontFamily: "system-ui, sans-serif", color: "#991B1B", backgroundColor: "#FEF2F2", minHeight: "100vh", boxSizing: "border-box" }}>
          <h2 style={{ fontSize: "20px", fontWeight: 700, margin: "0 0 12px 0" }}>Application Error Detected</h2>
          <p style={{ margin: "0 0 16px 0", color: "#374151" }}>A runtime exception occurred while rendering the workspace:</p>
          <pre style={{ whiteSpace: "pre-wrap", background: "#FFFFFF", padding: "16px", borderRadius: "8px", border: "1px solid #FCA5A5", fontSize: "13px", color: "#B91C1C" }}>
            {this.state.error?.toString()}
            {"\n\nComponent Stack:\n"}
            {this.state.errorInfo?.componentStack || "No component stack available"}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: "16px",
              padding: "8px 16px",
              backgroundColor: "#166534",
              color: "#FFF",
              border: "none",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            Reload Editor
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

// Window-level safety catcher
window.addEventListener('error', (event) => {
  const root = document.getElementById('root');
  if (root && root.innerHTML.trim() === '') {
    root.innerHTML = `
      <div style="padding: 40px; font-family: system-ui, sans-serif; color: #991B1B; background-color: #FEF2F2; min-height: 100vh;">
        <h2 style="font-size: 20px; font-weight: 700; margin-bottom: 12px;">Global JavaScript Error</h2>
        <pre style="white-space: pre-wrap; background: #FFF; padding: 16px; border-radius: 8px; border: 1px solid #FCA5A5; font-size: 13px; color: #B91C1C;">
${event.message} at ${event.filename}:${event.lineno}:${event.colno}
        </pre>
        <button onclick="window.location.reload()" style="margin-top: 16px; padding: 8px 16px; background: #166534; color: #FFF; border: none; border-radius: 6px; cursor: pointer;">
          Reload Page
        </button>
      </div>
    `;
  }
});

const rootEl = document.getElementById('root');
if (rootEl) {
  ReactDOM.createRoot(rootEl).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>
  );
}
