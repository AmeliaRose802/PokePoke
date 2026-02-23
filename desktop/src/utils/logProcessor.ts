/**
 * Log processing utilities for tool call collapsing and batching.
 * Used by both LogPanel and AgentLogPanel.
 */

import type { LogEntry } from "../types";
import { extractDescriptionFromArgs } from "./toolDescriptions";

export interface ToolSummary {
  toolLabel: string;
  resultSummary?: string;
  statusClass?: string;
}

export interface ToolItem {
  toolName: string;
  argsText?: string;
  entry: LogEntry;
  result?: LogEntry;
  summary: ToolSummary;
  additionalEntries?: LogEntry[];
}

export interface ToolGroup {
  toolName: string;
  toolLabel: string;
  items: ToolItem[];
  statusClass?: string;
  summaryText?: string;
}

export interface ToolBatch {
  header?: LogEntry;
  expectedTotal?: number;
  startedAt: number;
  groups: ToolGroup[];
  totalCalls: number;
  completedCalls: number;
  statusClass?: string;
}

export type RenderLogItem =
  | { type: "log"; entry: LogEntry }
  | { type: "tool"; tool: ToolItem }
  | { type: "tool-batch"; batch: ToolBatch }
  | { type: "narration"; entries: LogEntry[]; startedAt: number }
  | { type: "markdown-block"; entries: LogEntry[]; startedAt: number }
  | {
      type: "code-block";
      entries: LogEntry[];
      startedAt: number;
      markdown: string;
      codeLineCount: number;
      language?: string;
    };

const TOOL_CALL_PATTERN = /^\s*(?:🌿|🔧|\[Tool\])\s*(.*)$/;
const TOOL_RESULT_PATTERN = /^\s*(✅|❌)\s*Result:\s*(.*)$/;
const TOOL_RESULT_FALLBACK = /^\s*\[Result\]\s*(.*)$/i;
const COPILOT_TOOL_BATCH_HEADER = /^\s*\[Copilot\]\s*Calling\s+(\d+)\s+tool\(s\)\.\.\.$/;
const CODE_FENCE_REGEX = /```([^\n`]*)?\n([\s\S]*?)```/m;
const APPLY_PATCH_RE = /apply_patch\s*\(/;
const PATCH_END_RE = /\*{3}\s*End Patch/;
const PATCH_UPDATE_FILE_RE = /\*{3}\s*(?:Update|Add|Delete)\s+File:\s*(.+)/;

export function isToolCallMessage(message: string): boolean {
  return TOOL_CALL_PATTERN.test(message);
}

export function isToolResultMessage(message: string): boolean {
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

export function isNarrationCandidate(message: string): boolean {
  const trimmed = message.trim();
  if (trimmed.length < 6) return false;
  if (isToolCallMessage(trimmed) || isToolResultMessage(trimmed) || isCopilotToolBatchHeader(trimmed))
    return false;
  return /^(now|next|then|after|first|second|third|i\s*(?:'m|am|will)|i\s*need|let'?s)\b/i.test(
    trimmed
  );
}

function isApplyPatchToolCall(message: string): boolean {
  return isToolCallMessage(message) && APPLY_PATCH_RE.test(message);
}

export function parseToolLabel(message: string): string {
  const match = message.match(TOOL_CALL_PATTERN);
  if (!match) return message.trim();
  const rest = match[1].trim();
  const callMatch = rest.match(/^([^(]+)\((.*)\)$/);
  if (!callMatch) return `🌿 ${rest}`;
  const toolName = callMatch[1].trim();
  const description = extractDescriptionFromArgs(toolName, callMatch[2].trim());
  const label = `🌿 ${toolName}`;
  return description ? `${label} - ${truncateText(description, 50)}` : label;
}

function parseToolCallParts(message: string): { toolName: string; argsText?: string } {
  const match = message.match(TOOL_CALL_PATTERN);
  if (!match) return { toolName: message.trim() };
  const callMatch = match[1].trim().match(/^([^(]+)\((.*)\)$/);
  if (callMatch) return { toolName: callMatch[1].trim(), argsText: callMatch[2].trim() };
  const toolName = match[1].trim().split(/\s+/)[0]?.trim() || match[1].trim();
  return { toolName };
}

export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 1)}…`;
}

export function buildToolSummary(callMessage: string, resultMessage?: string): ToolSummary {
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
  if (toolName === "apply_patch") {
    const files = new Set<string>();
    for (const item of items) {
      for (const entry of item.additionalEntries ?? []) {
        const match = entry.message.match(PATCH_UPDATE_FILE_RE);
        if (match) files.add(match[1].trim());
      }
    }
    if (files.size > 0) {
      return `Patched ${files.size} file${files.size === 1 ? "" : "s"}`;
    }
    return `${items.length} patch${items.length === 1 ? "" : "es"}`;
  }

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

/** Map log content keywords to CSS class names */
export function detectLevel(message: string): string {
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
export function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("en-US", { hour12: false });
}

export function processLogsToRenderItems(logs: LogEntry[]): RenderLogItem[] {
  const items: RenderLogItem[] = [];

  function parseToolAt(index: number): { tool: ToolItem; nextIndex: number } {
    const entry = logs[index];
    // Handle multiline apply_patch tool calls
    if (isApplyPatchToolCall(entry.message)) {
      const additionalEntries: LogEntry[] = [];
      const filePaths: string[] = [];
      let j = index + 1;

      while (j < logs.length) {
        const line = logs[j];
        if (isToolCallMessage(line.message) || isCopilotToolBatchHeader(line.message)) break;
        if (isToolResultMessage(line.message)) break;

        const fileMatch = line.message.match(PATCH_UPDATE_FILE_RE);
        if (fileMatch) filePaths.push(fileMatch[1].trim());

        additionalEntries.push(line);

        if (PATCH_END_RE.test(line.message)) {
          j += 1;
          break;
        }
        j += 1;
      }

      const nextEntry = logs[j];
      const result = nextEntry && isToolResultMessage(nextEntry.message) ? nextEntry : undefined;
      const nextIndex = result ? j + 1 : j;

      const fileLabel = filePaths.length > 0
        ? ` — ${filePaths.map(p => p.replace(/^.*[/\\]/, "")).join(", ")}`
        : "";
      const toolLabel = `🌿 apply_patch${fileLabel}`;

      return {
        tool: {
          toolName: "apply_patch",
          entry,
          result,
          additionalEntries,
          summary: {
            toolLabel,
            resultSummary: result ? buildToolSummary("", result.message).resultSummary : undefined,
            statusClass: result ? buildToolSummary("", result.message).statusClass : undefined,
          },
        },
        nextIndex,
      };
    }

    const parts = parseToolCallParts(entry.message);

    // Scan forward past streaming output (e.g. powershell stdout) to find the result
    const intermediateEntries: LogEntry[] = [];
    let j = index + 1;
    while (j < logs.length) {
      const line = logs[j];
      if (isToolCallMessage(line.message) || isCopilotToolBatchHeader(line.message)) break;
      if (TOOL_RESULT_PATTERN.test(line.message) || TOOL_RESULT_FALLBACK.test(line.message)) break;
      intermediateEntries.push(line);
      j += 1;
    }
    const resultEntry = logs[j];
    const result = resultEntry && isToolResultMessage(resultEntry.message) ? resultEntry : undefined;
    const hasIntermediate = result && intermediateEntries.length > 0;
    return {
      tool: {
        toolName: parts.toolName,
        argsText: parts.argsText,
        entry,
        result,
        additionalEntries: hasIntermediate ? intermediateEntries : undefined,
        summary: buildToolSummary(entry.message, result?.message),
      },
      nextIndex: result ? j + 1 : index + 1,
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
        toolLabel: `🌿 ${toolName} ×${slice.length}`,
        items: slice,
        statusClass,
        summaryText,
      });
    }
    return groups;
  }

  function buildBatchFromTools(tools: ToolItem[], startedAt: number, header?: LogEntry, expectedTotal?: number): ToolBatch {
    const groups = buildToolGroups(tools);
    const completedCalls = tools.filter((t) => Boolean(t.result)).length;
    const hasError = tools.some((t) => t.summary.statusClass === "log-error");
    const allDone = tools.every((t) => Boolean(t.result));
    return {
      header, expectedTotal, startedAt, groups,
      totalCalls: tools.length, completedCalls,
      statusClass: hasError ? "log-error" : allDone ? "log-success" : undefined,
    };
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
        items.push({ type: "tool-batch", batch: buildBatchFromTools(tools, startedAt, header, expectedTotal) });
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

      items.push({ type: "tool-batch", batch: buildBatchFromTools(tools, startedAt) });
      continue;
    }

    items.push({ type: "log", entry });
    i += 1;
  }

  return mergeConsecutiveLogEntries(items);
}

/** Merge consecutive plain log entries into markdown blocks for rich rendering. */
function mergeConsecutiveLogEntries(items: RenderLogItem[]): RenderLogItem[] {
  const merged: RenderLogItem[] = [];
  let i = 0;
  while (i < items.length) {
    if (items[i].type !== "log") {
      merged.push(items[i]);
      i += 1;
      continue;
    }
    const block: LogEntry[] = [];
    const startedAt = (items[i] as { type: "log"; entry: LogEntry }).entry.timestamp;
    while (i < items.length && items[i].type === "log") {
      block.push((items[i] as { type: "log"; entry: LogEntry }).entry);
      i += 1;
    }
    if (block.length === 1 && !containsMarkdown(block[0].message)) {
      merged.push({ type: "log", entry: block[0] });
      continue;
    }

    const markdown = block.map((entry) => entry.message).join("\n");
    const codeMetadata = extractCodeFenceMetadata(markdown);
    if (codeMetadata) {
      merged.push({
        type: "code-block",
        entries: block,
        startedAt,
        markdown,
        codeLineCount: codeMetadata.lineCount,
        language: codeMetadata.language,
      });
      continue;
    }

    merged.push({ type: "markdown-block", entries: block, startedAt });
  }
  return merged;
}

/** Check if a string contains markdown syntax worth rendering. */
function containsMarkdown(text: string): boolean {
  return /(?:^#{1,6}\s|[*_]{1,2}\S|\[.+\]\(.+\)|`[^`]+`|^[-*+]\s|^\d+\.\s|^>\s|^```)/m.test(text);
}

interface CodeFenceMetadata {
  language?: string;
  lineCount: number;
}

function extractCodeFenceMetadata(markdown: string): CodeFenceMetadata | undefined {
  const match = markdown.match(CODE_FENCE_REGEX);
  if (!match) return undefined;
  const language = match[1]?.trim() || undefined;
  const codeBody = (match[2] ?? "").replace(/\s+$/, "");
  const lines = codeBody.length === 0 ? 0 : codeBody.split(/\r?\n/).length;
  return {
    language,
    lineCount: Math.max(lines, 1),
  };
}

/** Convert raw string log lines (from AgentInfo) to LogEntry format. */
export function stringsToLogEntries(lines: string[], baseTimestamp: number): LogEntry[] {
  return lines.map((line, index) => ({
    message: line,
    target: "agent" as const,
    style: null,
    timestamp: baseTimestamp + index,
  }));
}
