/**
 * Log panel component.
 *
 * Renders a scrollable list of log entries with timestamps,
 * auto-detected log level styling, and auto-scroll to bottom.
 */

import { useEffect, useRef } from "react";
import type { LogEntry } from "../types";

interface Props {
  title: string;
  icon: string;
  logs: LogEntry[];
  accentColor: string;
  focused?: boolean;
  onFocus?: () => void;
}

/** Map log content keywords to CSS class names */
function detectLevel(message: string): string {
  const lower = message.toLowerCase();
  if (lower.includes("error") || lower.includes("failed") || lower.includes("exception"))
    return "log-error";
  if (lower.includes("warn")) return "log-warning";
  if (lower.includes("success") || lower.includes("completed") || message.includes("✅"))
    return "log-success";
  if (lower.includes("debug")) return "log-debug";
  return "log-info";
}

/** Format a unix timestamp to HH:MM:SS */
function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("en-US", { hour12: false });
}

export function LogPanel({
  title,
  icon,
  logs,
  accentColor,
  focused,
  onFocus,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const isUserScrolledUp = useRef(false);

  // Set accent color using CSS custom property
  useEffect(() => {
    if (panelRef.current) {
      panelRef.current.style.setProperty('--accent', accentColor);
    }
  }, [accentColor]);

  // Detect if user has scrolled up
  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const threshold = 50;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
    isUserScrolledUp.current = !atBottom;
  };

  // Auto-scroll to bottom when new logs arrive (unless user scrolled up)
  useEffect(() => {
    if (!isUserScrolledUp.current) {
      bottomRef.current?.scrollIntoView({ behavior: "auto" });
    }
  }, [logs]);

  return (
    <div
      ref={panelRef}
      className={`log-panel ${focused ? "focused" : ""}`}
      onClick={onFocus}
    >
      <div className="log-panel-header">
        <span>
          {icon} {title}
        </span>
        <span className="log-count">{logs.length} lines</span>
      </div>
      <div
        className="log-entries"
        ref={containerRef}
        onScroll={handleScroll}
      >
        {logs.map((entry, i) => (
          <div key={i} className={`log-entry ${detectLevel(entry.message)}`}>
            <span className="log-timestamp">{formatTime(entry.timestamp)}</span>
            <span className="log-message">{entry.message}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
