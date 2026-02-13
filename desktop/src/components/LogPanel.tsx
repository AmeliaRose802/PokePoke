/**
 * Log panel component.
 *
 * Renders a scrollable list of log entries with timestamps,
 * auto-detected log level styling, and auto-scroll to bottom.
 */

import { useEffect, useMemo, useRef } from "react";
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

const TOOL_CALL_PATTERN = /^\s*(?:🔧|\[Tool\])\s*(.*)$/;
const TOOL_RESULT_PATTERN = /^\s*(✅|❌)\s*Result:\s*(.*)$/;
const TOOL_RESULT_FALLBACK = /^\s*\[Result\]\s*(.*)$/i;

interface ToolSummary {
  toolLabel: string;
  resultSummary?: string;
  statusClass?: string;
}

interface RenderLogItem {
  type: "log" | "tool";
  entry: LogEntry;
  result?: LogEntry;
  summary?: ToolSummary;
}

function isToolCallMessage(message: string): boolean {
  return TOOL_CALL_PATTERN.test(message);
}

function isToolResultMessage(message: string): boolean {
  return message.includes("Result:") || TOOL_RESULT_FALLBACK.test(message);
}

function parseToolLabel(message: string): string {
  const match = message.match(TOOL_CALL_PATTERN);
  if (!match) return message.trim();
  const rest = match[1].trim();
  const callMatch = rest.match(/^([^(]+)\((.*)\)$/);
  if (!callMatch) return `🔧 ${rest}`;
  return `🔧 ${callMatch[1].trim()}`;
}

function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 1)}…`;
}

function buildToolSummary(callMessage: string, resultMessage?: string): ToolSummary {
  const toolLabel = parseToolLabel(callMessage);
  if (!resultMessage) {
    return { toolLabel };
  }
  const resultMatch = resultMessage.match(TOOL_RESULT_PATTERN);
  const fallbackMatch = resultMessage.match(TOOL_RESULT_FALLBACK);
  const summaryText = resultMatch?.[2] ?? fallbackMatch?.[1] ?? resultMessage.trim();
  const statusEmoji = resultMatch?.[1];
  const statusClass =
    statusEmoji === "✅" ? "log-success" : statusEmoji === "❌" ? "log-error" : undefined;
  const resultSummary = `${statusEmoji ? `${statusEmoji} ` : ""}${truncateText(
    summaryText,
    120
  )}`.trim();
  return {
    toolLabel,
    resultSummary,
    statusClass,
  };
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

  const renderItems = useMemo<RenderLogItem[]>(() => {
    const items: RenderLogItem[] = [];
    for (let i = 0; i < logs.length; i += 1) {
      const entry = logs[i];
      if (isToolCallMessage(entry.message)) {
        const next = logs[i + 1];
        const result = next && isToolResultMessage(next.message) ? next : undefined;
        if (result) {
          i += 1;
        }
        items.push({
          type: "tool",
          entry,
          result,
          summary: buildToolSummary(entry.message, result?.message),
        });
        continue;
      }
      items.push({ type: "log", entry });
    }
    return items;
  }, [logs]);

  const renderLogEntry = (entry: LogEntry, key: string) => (
    <div key={key} className={`log-entry ${detectLevel(entry.message)}`}>
      <span className="log-timestamp">{formatTime(entry.timestamp)}</span>
      <span className="log-message">{entry.message}</span>
    </div>
  );

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
        {renderItems.map((item, i) => {
          if (item.type === "tool" && item.summary) {
            const detailsEntries = [item.entry];
            if (item.result) detailsEntries.push(item.result);
            return (
              <details
                key={`tool-${i}`}
                className={`log-accordion ${item.summary.statusClass ?? ""}`.trim()}
              >
                <summary className="log-accordion-summary">
                  <span className="log-accordion-chevron">▸</span>
                  <span className="log-timestamp">
                    {formatTime(item.entry.timestamp)}
                  </span>
                  <span className="log-message">{item.summary.toolLabel}</span>
                  {item.summary.resultSummary && (
                    <span className="log-accordion-result">
                      {item.summary.resultSummary}
                    </span>
                  )}
                </summary>
                <div className="log-accordion-details">
                  {detailsEntries.map((entry, detailIndex) =>
                    renderLogEntry(entry, `tool-${i}-${detailIndex}`)
                  )}
                </div>
              </details>
            );
          }
          return renderLogEntry(item.entry, `log-${i}`);
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
