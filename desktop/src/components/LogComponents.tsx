/**
 * React components for rendering log items with collapsible tool/narration blocks.
 *
 * These components consume the processed log items from logProcessor.ts.
 */

import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import diff from "highlight.js/lib/languages/diff";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import powershell from "highlight.js/lib/languages/powershell";
import python from "highlight.js/lib/languages/python";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import { useEffect, useRef } from "react";

hljs.registerLanguage("bash", bash);
hljs.registerLanguage("diff", diff);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("json", json);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("powershell", powershell);
hljs.registerLanguage("python", python);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("yaml", yaml);

import type { LogEntry } from "../types";
import {
  detectLevel,
  formatTime,
  type RenderLogItem,
  type ToolBatch,
  type ToolItem,
  type ToolSummary,
} from "../utils/logProcessor";
import { renderMarkdown } from "../utils/markdown";

// ===================== Render Components =====================

interface LogEntryRendererProps {
  entry: LogEntry;
  keyPrefix: string;
  className?: string;
}

export function LogEntryRenderer({ entry, keyPrefix, className }: LogEntryRendererProps) {
  return (
    <div key={keyPrefix} className={`log-entry ${detectLevel(entry.message)} ${className ?? ""}`.trim()}>
      <span className="log-timestamp">{formatTime(entry.timestamp)}</span>
      <span className="log-message">{entry.message}</span>
    </div>
  );
}

interface ToolDescriptionProps {
  summary: ToolSummary;
}

function ToolDescription({ summary }: ToolDescriptionProps) {
  if (!summary.description) return null;
  return (
    <details className="log-tool-description">
      <summary className="log-tool-description-summary">
        <span className="log-accordion-chevron">▸</span>
        <span className="log-tool-description-label">Description</span>
      </summary>
      <div className="log-tool-description-content">{summary.description}</div>
    </details>
  );
}

interface ToolAccordionProps {
  tool: ToolItem;
  keyPrefix: string;
  nested?: boolean;
}

export function ToolAccordion({ tool, keyPrefix, nested = false }: ToolAccordionProps) {
  const detailsEntries = [tool.entry];
  if (tool.additionalEntries) detailsEntries.push(...tool.additionalEntries);
  if (tool.result) detailsEntries.push(tool.result);
  const nestedClass = nested ? "nested" : "";

  return (
    <details key={keyPrefix} className={`log-accordion ${tool.summary.statusClass ?? ""} ${nestedClass}`.trim()}>
      <summary className="log-accordion-summary">
        <span className="log-accordion-chevron">▸</span>
        <span className="log-timestamp">{formatTime(tool.entry.timestamp)}</span>
        <span className="log-message">{tool.summary.toolLabel}</span>
        {tool.summary.resultSummary && (
          <span className="log-accordion-result">{tool.summary.resultSummary}</span>
        )}
      </summary>
      <div className="log-accordion-details">
        <ToolDescription summary={tool.summary} />
        {detailsEntries.map((entry, detailIndex) => (
          <LogEntryRenderer
            key={`${keyPrefix}-${detailIndex}`}
            entry={entry}
            keyPrefix={`${keyPrefix}-${detailIndex}`}
          />
        ))}
      </div>
    </details>
  );
}

interface NarrationAccordionProps {
  entries: LogEntry[];
  startedAt: number;
  keyPrefix: string;
}

export function NarrationAccordion({ entries, startedAt, keyPrefix }: NarrationAccordionProps) {
  return (
    <details key={keyPrefix} className="log-narration">
      <summary className="log-accordion-summary">
        <span className="log-accordion-chevron">▸</span>
        <span className="log-timestamp">{formatTime(startedAt)}</span>
        <span className="log-message">💭 Narration ({entries.length} lines)</span>
      </summary>
      <div className="log-accordion-details">
        {entries.map((entry, j) => (
          <LogEntryRenderer
            key={`${keyPrefix}-${j}`}
            entry={entry}
            keyPrefix={`${keyPrefix}-${j}`}
          />
        ))}
      </div>
    </details>
  );
}

interface ToolBatchAccordionProps {
  batch: ToolBatch;
  keyPrefix: string;
}

export function ToolBatchAccordion({ batch, keyPrefix }: ToolBatchAccordionProps) {
  const total = batch.expectedTotal ?? batch.totalCalls;
  const progress = `${batch.completedCalls}/${total}`;
  const byTool = batch.groups.map((g) => `${g.toolName}×${g.items.length}`).join(", ");

  // Flatten: single group with single tool → render as simple ToolAccordion
  if (batch.groups.length === 1 && batch.groups[0].items.length === 1) {
    return (
      <ToolAccordion
        key={keyPrefix}
        tool={batch.groups[0].items[0]}
        keyPrefix={keyPrefix}
      />
    );
  }

  // Flatten: single group → skip group accordion, render tools directly
  const singleGroup = batch.groups.length === 1;

  return (
    <details
      key={keyPrefix}
      className={`log-tool-batch ${batch.statusClass ?? ""}`.trim()}
      open={singleGroup}
    >
      <summary className="log-accordion-summary">
        <span className="log-accordion-chevron">▸</span>
        <span className="log-timestamp">{formatTime(batch.startedAt)}</span>
        <span className="log-message">
          🔧 Tool batch ({batch.totalCalls} call{batch.totalCalls === 1 ? "" : "s"})
          {byTool ? ` — ${byTool}` : ""}
        </span>
        <span className="log-accordion-result">{progress}</span>
      </summary>
      <div className="log-accordion-details">
        {batch.groups.map((group, gIndex) => {
          // Flatten: single item in group → render tool directly without group wrapper
          if (group.items.length === 1) {
            return (
              <ToolAccordion
                key={`${keyPrefix}-group-${gIndex}-tool-0`}
                tool={group.items[0]}
                keyPrefix={`${keyPrefix}-group-${gIndex}-tool-0`}
                nested
              />
            );
          }

          return (
            <details
              key={`${keyPrefix}-group-${gIndex}`}
              className={`log-tool-group ${group.statusClass ?? ""}`.trim()}
              open={batch.groups.length === 1}
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
                {group.items.map((tool, tIndex) => (
                  <ToolAccordion
                    key={`${keyPrefix}-group-${gIndex}-tool-${tIndex}`}
                    tool={tool}
                    keyPrefix={`${keyPrefix}-group-${gIndex}-tool-${tIndex}`}
                    nested
                  />
                ))}
              </div>
            </details>
          );
        })}
      </div>
    </details>
  );
}

interface MarkdownBlockProps {
  entries: LogEntry[];
  startedAt: number;
  keyPrefix: string;
}

export function MarkdownBlock({ entries, startedAt, keyPrefix }: MarkdownBlockProps) {
  const markdown = entries.map((e) => e.message).join("\n");
  const html = renderMarkdown(markdown);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;

    el.querySelectorAll("pre code").forEach((block) => {
      hljs.highlightElement(block as HTMLElement);
    });
  }, [html]);

  return (
    <div key={keyPrefix} className="log-entry log-markdown-block">
      <span className="log-timestamp">{formatTime(startedAt)}</span>
      <div
        ref={contentRef}
        className="log-message log-markdown-content"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}

interface CodeBlockAccordionProps {
  startedAt: number;
  keyPrefix: string;
  markdown: string;
  lineCount: number;
  language?: string;
}

export function CodeBlockAccordion({
  startedAt,
  keyPrefix,
  markdown,
  lineCount,
  language,
}: CodeBlockAccordionProps) {
  const html = renderMarkdown(markdown);
  const lineLabel = `${lineCount} line${lineCount === 1 ? "" : "s"}`;
  const codeLabel = language ? `📄 ${language} code block` : "📄 Code block";
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;

    el.querySelectorAll("pre code").forEach((block) => {
      hljs.highlightElement(block as HTMLElement);
    });
  }, [html]);

  return (
    <details key={keyPrefix} className="log-accordion log-code-block">
      <summary className="log-accordion-summary">
        <span className="log-accordion-chevron">▸</span>
        <span className="log-timestamp">{formatTime(startedAt)}</span>
        <span className="log-message">
          {codeLabel} — {lineLabel}
        </span>
      </summary>
      <div className="log-accordion-details">
        <div
          ref={contentRef}
          className="log-message log-markdown-content"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </div>
    </details>
  );
}

interface RenderLogItemsProps {
  items: RenderLogItem[];
}

/**
 * Render processed log items with collapsible tool batches and narrations.
 */
export function RenderLogItems({ items }: RenderLogItemsProps) {
  return (
    <>
      {items.map((item, i) => {
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
    </>
  );
}
