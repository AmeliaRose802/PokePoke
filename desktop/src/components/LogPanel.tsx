import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { LogEntry } from "../types";
import { processLogsToRenderItems } from "../utils/logProcessor";
import {
  CodeBlockAccordion,
  LogEntryRenderer,
  MarkdownBlock,
  NarrationAccordion,
  ToolAccordion,
  ToolBatchAccordion,
} from "./LogComponents";

interface Props {
  title: string;
  icon: string;
  logs: LogEntry[];
  accentColor: string;
  focused?: boolean;
  onFocus?: () => void;
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

  const renderItems = useMemo(() => processLogsToRenderItems(logs), [logs]);

  const [copySuccess, setCopySuccess] = useState(false);

  const handleCopy = useCallback(async () => {
    const text = logs.map((l) => l.message).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      console.error("Failed to copy logs:", err);
    }
  }, [logs]);

  // Guard: don't steal focus (and trigger re-render) when user is selecting text
  const handleClick = () => {
    if (window.getSelection()?.toString()) return;
    onFocus?.();
  };

  return (
    <div
      ref={panelRef}
      className={`log-panel ${focused ? "focused" : ""}`}
      onClick={handleClick}
    >
      <div className="log-panel-header">
        <span>
          {icon} {title}
        </span>
        <span className="log-panel-header-actions">
          <button
            className={`copy-btn ${copySuccess ? "success" : ""}`}
            onClick={(e) => { e.stopPropagation(); handleCopy(); }}
            title={copySuccess ? "Copied!" : "Copy log output"}
            aria-label={copySuccess ? "Copied!" : "Copy log output"}
          >
            {copySuccess ? "✓" : "📋"}
          </button>
          <span className="log-count">{logs.length} lines</span>
        </span>
      </div>
      <div
        className="log-entries"
        ref={containerRef}
        onScroll={handleScroll}
      >
        {renderItems.map((item, i) => {
          if (item.type === "tool") {
            return (
              <ToolAccordion
                key={`tool-${i}`}
                tool={item.tool}
                keyPrefix={`tool-${i}`}
              />
            );
          }

          if (item.type === "narration") {
            return (
              <NarrationAccordion
                key={`narration-${i}`}
                entries={item.entries}
                startedAt={item.startedAt}
                keyPrefix={`narration-${i}`}
              />
            );
          }

          if (item.type === "tool-batch") {
            return (
              <ToolBatchAccordion
                key={`tool-batch-${i}`}
                batch={item.batch}
                keyPrefix={`tool-batch-${i}`}
              />
            );
          }

          if (item.type === "markdown-block") {
            return (
              <MarkdownBlock
                key={`md-${i}`}
                entries={item.entries}
                startedAt={item.startedAt}
                keyPrefix={`md-${i}`}
              />
            );
          }

          if (item.type === "code-block") {
            return (
              <CodeBlockAccordion
                key={`code-${i}`}
                startedAt={item.startedAt}
                keyPrefix={`code-${i}`}
                markdown={item.markdown}
                lineCount={item.codeLineCount}
                language={item.language}
              />
            );
          }

          return (
            <LogEntryRenderer
              key={`log-${i}`}
              entry={item.entry}
              keyPrefix={`log-${i}`}
            />
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
