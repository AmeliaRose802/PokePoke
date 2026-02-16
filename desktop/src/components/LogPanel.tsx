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
const COPILOT_TOOL_BATCH_HEADER = /^\s*\[Copilot\]\s*Calling\s+(\d+)\s+tool\(s\)\.\.\.$/;
interface ToolSummary {
  toolLabel: string;
  resultSummary?: string;
  statusClass?: string;
}
interface ToolItem {
  toolName: string;
  argsText?: string;
  entry: LogEntry;
  result?: LogEntry;
  summary: ToolSummary;
}
interface ToolGroup {
  toolName: string;
  toolLabel: string;
  items: ToolItem[];
  statusClass?: string;
  summaryText?: string;
}
interface ToolBatch {
  header?: LogEntry;
  expectedTotal?: number;
  startedAt: number;
  groups: ToolGroup[];
  totalCalls: number;
  completedCalls: number;
  statusClass?: string;
}
type RenderLogItem =
  | { type: "log"; entry: LogEntry }
  | { type: "tool"; tool: ToolItem }
  | { type: "tool-batch"; batch: ToolBatch }
  | { type: "narration"; entries: LogEntry[]; startedAt: number };

function isToolCallMessage(message: string): boolean {
  return TOOL_CALL_PATTERN.test(message);
}

function isToolResultMessage(message: string): boolean {
  return message.includes("Result:") || TOOL_RESULT_FALLBACK.test(message);
}

function isCopilotToolBatchHeader(message: string): boolean {
  return COPILOT_TOOL_BATCH_HEADER.test(message);
}

function parseCopilotToolBatchHeaderCount(message: string): number | undefined {
  const match = message.match(COPILOT_TOOL_BATCH_HEADER);
  if (!match) return undefined;
  const n = Number(match[1]);
  return Number.isFinite(n) ? n : undefined;
}

function isNarrationCandidate(message: string): boolean {
  const trimmed = message.trim();
  if (trimmed.length < 6) return false;
  if (isToolCallMessage(trimmed) || isToolResultMessage(trimmed) || isCopilotToolBatchHeader(trimmed))
    return false;
  return /^(now|next|then|after|first|second|third|i\s*(?:'m|am|will)|i\s*need|let'?s)\b/i.test(
    trimmed
  );
}

function parseToolLabel(message: string): string {
  const match = message.match(TOOL_CALL_PATTERN);
  if (!match) return message.trim();
  const rest = match[1].trim();
  const callMatch = rest.match(/^([^(]+)\((.*)\)$/);
  if (!callMatch) return `🔧 ${rest}`;
  return `🔧 ${callMatch[1].trim()}`;
}

function parseToolCallParts(message: string): { toolName: string; argsText?: string } {
  const match = message.match(TOOL_CALL_PATTERN);
  if (!match) return { toolName: message.trim() };
  const rest = match[1].trim();
  const callMatch = rest.match(/^([^(]+)\((.*)\)$/);
  if (callMatch) {
    return { toolName: callMatch[1].trim(), argsText: callMatch[2].trim() };
  }
  const toolName = rest.split(/\s+/)[0]?.trim() || rest;
  return { toolName };
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

function extractPathsFromArgs(argsText: string | undefined): string[] {
  if (!argsText) return [];
  const paths: string[] = [];
  const re = /\bpath\b\s*[:=]\s*["']([^"']+)["']/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(argsText)) !== null) {
    paths.push(m[1]);
  }
  return paths;
}

function sumReplacementsFromResults(items: ToolItem[]): number {
  let total = 0;
  for (const item of items) {
    const msg = item.result?.message ?? "";
    const m = msg.match(/Replaced\s+(\d+)\s+occurrences?/i);
    if (m) total += Number(m[1]);
  }
  return Number.isFinite(total) ? total : 0;
}

function buildToolGroupSummary(toolName: string, items: ToolItem[]): string | undefined {
  if (toolName === "edit") {
    const files = new Set(items.flatMap((i) => extractPathsFromArgs(i.argsText)));
    const replacements = sumReplacementsFromResults(items);
    const fileCount = files.size;
    if (replacements > 0 && fileCount > 0) {
      return `Replaced ${replacements} occurrence${replacements === 1 ? "" : "s"} in ${fileCount} file${
        fileCount === 1 ? "" : "s"
      }`;
    }
    if (fileCount > 0) {
      return `Edited ${fileCount} file${fileCount === 1 ? "" : "s"}`;
    }
    return `Edits: ${items.length}`;
  }

  if (toolName === "create") {
    const files = new Set(items.flatMap((i) => extractPathsFromArgs(i.argsText)));
    const fileCount = files.size;
    if (fileCount > 0) {
      return `Created ${fileCount} file${fileCount === 1 ? "" : "s"}`;
    }
  }

  if (toolName === "grep" || toolName === "glob" || toolName === "view") {
    return `${items.length} call${items.length === 1 ? "" : "s"}`;
  }

  return undefined;
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

    function parseToolAt(index: number): { tool: ToolItem; nextIndex: number } {
      const entry = logs[index];
      const parts = parseToolCallParts(entry.message);
      const next = logs[index + 1];
      const result = next && isToolResultMessage(next.message) ? next : undefined;
      const nextIndex = result ? index + 2 : index + 1;
      return {
        tool: {
          toolName: parts.toolName,
          argsText: parts.argsText,
          entry,
          result,
          summary: buildToolSummary(entry.message, result?.message),
        },
        nextIndex,
      };
    }

    function buildToolGroups(tools: ToolItem[]): ToolGroup[] {
      const groups: ToolGroup[] = [];
      let i = 0;
      while (i < tools.length) {
        const toolName = tools[i].toolName;
        const start = i;
        while (i < tools.length && tools[i].toolName === toolName) i += 1;
        const slice = tools.slice(start, i);
        const summaryText = buildToolGroupSummary(toolName, slice);
        const hasError = slice.some((t) => t.summary.statusClass === "log-error");
        const allDone = slice.every((t) => Boolean(t.result));
        const statusClass = hasError ? "log-error" : allDone ? "log-success" : undefined;
        groups.push({
          toolName,
          toolLabel: `🔧 ${toolName} ×${slice.length}`,
          items: slice,
          statusClass,
          summaryText,
        });
      }
      return groups;
    }

    let i = 0;
    while (i < logs.length) {
      const entry = logs[i];

      if (isNarrationCandidate(entry.message)) {
        const narration: LogEntry[] = [];
        const startedAt = entry.timestamp;
        while (
          i < logs.length &&
          isNarrationCandidate(logs[i].message) &&
          !isCopilotToolBatchHeader(logs[i].message)
        ) {
          narration.push(logs[i]);
          i += 1;
        }
        const next = logs[i];
        const followedByTools = Boolean(next) && (isCopilotToolBatchHeader(next.message) || isToolCallMessage(next.message));
        if (followedByTools && narration.length > 0) {
          items.push({ type: "narration", entries: narration, startedAt });
          continue;
        }
        for (const n of narration) items.push({ type: "log", entry: n });
        continue;
      }

      if (isCopilotToolBatchHeader(entry.message)) {
        const expectedTotal = parseCopilotToolBatchHeaderCount(entry.message);
        const header = entry;
        i += 1;

        const tools: ToolItem[] = [];
        const startedAt = logs[i]?.timestamp ?? header.timestamp;
        while (i < logs.length && isToolCallMessage(logs[i].message)) {
          const parsed = parseToolAt(i);
          tools.push(parsed.tool);
          i = parsed.nextIndex;
        }

        if (tools.length > 0) {
          const groups = buildToolGroups(tools);
          const completedCalls = tools.filter((t) => Boolean(t.result)).length;
          const totalCalls = tools.length;
          const hasError = tools.some((t) => t.summary.statusClass === "log-error");
          const allDone = tools.every((t) => Boolean(t.result));
          const statusClass = hasError ? "log-error" : allDone ? "log-success" : undefined;
          items.push({
            type: "tool-batch",
            batch: {
              header,
              expectedTotal,
              startedAt,
              groups,
              totalCalls,
              completedCalls,
              statusClass,
            },
          });
          continue;
        }

        items.push({ type: "log", entry: header });
        continue;
      }

      if (isToolCallMessage(entry.message)) {
        const tools: ToolItem[] = [];
        const startedAt = entry.timestamp;
        while (i < logs.length && isToolCallMessage(logs[i].message)) {
          const parsed = parseToolAt(i);
          tools.push(parsed.tool);
          i = parsed.nextIndex;
        }

        if (tools.length === 1) {
          items.push({ type: "tool", tool: tools[0] });
          continue;
        }

        const groups = buildToolGroups(tools);
        const completedCalls = tools.filter((t) => Boolean(t.result)).length;
        const totalCalls = tools.length;
        const hasError = tools.some((t) => t.summary.statusClass === "log-error");
        const allDone = tools.every((t) => Boolean(t.result));
        const statusClass = hasError ? "log-error" : allDone ? "log-success" : undefined;
        items.push({
          type: "tool-batch",
          batch: {
            startedAt,
            groups,
            totalCalls,
            completedCalls,
            statusClass,
          },
        });
        continue;
      }

      items.push({ type: "log", entry });
      i += 1;
    }

    return items;
  }, [logs]);

  const renderLogEntry = (entry: LogEntry, key: string, className?: string) => (
    <div key={key} className={`log-entry ${detectLevel(entry.message)} ${className ?? ""}`.trim()}>
      <span className="log-timestamp">{formatTime(entry.timestamp)}</span>
      <span className="log-message">{entry.message}</span>
    </div>
  );

  const renderToolAccordion = (tool: ToolItem, key: string, nested = false) => {
    const detailsEntries = [tool.entry];
    if (tool.result) detailsEntries.push(tool.result);
    const nestedClass = nested ? "nested" : "";

    return (
      <details key={key} className={`log-accordion ${tool.summary.statusClass ?? ""} ${nestedClass}`.trim()}>
        <summary className="log-accordion-summary">
          <span className="log-accordion-chevron">▸</span>
          <span className="log-timestamp">{formatTime(tool.entry.timestamp)}</span>
          <span className="log-message">{tool.summary.toolLabel}</span>
          {tool.summary.resultSummary && (
            <span className="log-accordion-result">{tool.summary.resultSummary}</span>
          )}
        </summary>
        <div className="log-accordion-details">
          {detailsEntries.map((entry, detailIndex) =>
            renderLogEntry(entry, `${key}-${detailIndex}`)
          )}
        </div>
      </details>
    );
  };

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
            return renderToolAccordion(item.tool, `tool-${i}`);
          }

          if (item.type === "narration") {
            return (
              <details key={`narration-${i}`} className="log-narration">
                <summary className="log-accordion-summary">
                  <span className="log-accordion-chevron">▸</span>
                  <span className="log-timestamp">{formatTime(item.startedAt)}</span>
                  <span className="log-message">💭 Narration ({item.entries.length} lines)</span>
                </summary>
                <div className="log-accordion-details">
                  {item.entries.map((entry, j) => renderLogEntry(entry, `narration-${i}-${j}`))}
                </div>
              </details>
            );
          }

          if (item.type === "tool-batch") {
            const total = item.batch.expectedTotal ?? item.batch.totalCalls;
            const progress = `${item.batch.completedCalls}/${total}`;
            const byTool = item.batch.groups.map((g) => `${g.toolName}×${g.items.length}`).join(", ");
            return (
              <details
                key={`tool-batch-${i}`}
                className={`log-tool-batch ${item.batch.statusClass ?? ""}`.trim()}
              >
                <summary className="log-accordion-summary">
                  <span className="log-accordion-chevron">▸</span>
                  <span className="log-timestamp">{formatTime(item.batch.startedAt)}</span>
                  <span className="log-message">
                    🔧 Tool batch ({item.batch.totalCalls} call{item.batch.totalCalls === 1 ? "" : "s"})
                    {byTool ? ` — ${byTool}` : ""}
                  </span>
                  <span className="log-accordion-result">{progress}</span>
                </summary>
                <div className="log-accordion-details">
                  {item.batch.groups.map((group, gIndex) => (
                    <details
                      key={`tool-batch-${i}-group-${gIndex}`}
                      className={`log-tool-group ${group.statusClass ?? ""}`.trim()}
                    >
                      <summary className="log-accordion-summary">
                        <span className="log-accordion-chevron">▸</span>
                        <span className="log-timestamp">{formatTime(group.items[0].entry.timestamp)}</span>
                        <span className="log-message">{group.toolLabel}</span>
                        <span className="log-accordion-result">
                          {group.summaryText ?? `${group.items.filter((t) => Boolean(t.result)).length}/${group.items.length}`}
                        </span>
                      </summary>
                      <div className="log-accordion-details">
                        {group.items.map((tool, tIndex) =>
                          renderToolAccordion(tool, `tool-batch-${i}-group-${gIndex}-tool-${tIndex}`, true)
                        )}
                      </div>
                    </details>
                  ))}
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
