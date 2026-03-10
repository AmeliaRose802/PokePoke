import { useState } from "react";

interface Props {
  logsDir: string | null;
}

export function LogsLocationBox({ logsDir }: Props) {
  const [copySuccess, setCopySuccess] = useState(false);

  const handleCopy = async () => {
    if (!logsDir) return;

    try {
      await navigator.clipboard.writeText(logsDir);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      console.error("Failed to copy logs directory:", err);
    }
  };

  if (!logsDir) {
    return null; // Don't show component until logs directory is available
  }

  // Extract just the folder name and parent for display
  const pathParts = logsDir.replace(/\\/g, "/").split("/");
  const displayPath =
    pathParts.length >= 2 ? `.../${pathParts[pathParts.length - 2]}/${pathParts[pathParts.length - 1]}` : logsDir;

  return (
    <div className="logs-location-box">
      <div className="logs-location-content">
        <span className="logs-icon">📁</span>
        <span className="logs-path" title={logsDir}>
          {displayPath}
        </span>
        <button
          className={`copy-btn ${copySuccess ? "success" : ""}`}
          onClick={handleCopy}
          title={copySuccess ? "Copied!" : "Copy full path to clipboard"}
          aria-label={copySuccess ? "Copied!" : "Copy logs directory path"}
        >
          {copySuccess ? "✓" : "📋"}
        </button>
      </div>
    </div>
  );
}
