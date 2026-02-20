import { useEffect, useMemo, useRef } from "react";
import type { LogEntry } from "../types";
import { processLogsToRenderItems } from "../utils/logProcessor";
import {
  LogEntryRenderer,
  ToolAccordion,
  NarrationAccordion,
  ToolBatchAccordion,
  MarkdownBlock,
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
