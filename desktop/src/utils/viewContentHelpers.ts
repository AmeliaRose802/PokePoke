/**
 * Utilities for rendering view tool file content as syntax-highlighted code blocks.
 * Handles file extension detection, language mapping, and line number stripping.
 */

import type { ToolItem } from "./logProcessor";

/** Map common file extensions to highlight.js language identifiers. */
const EXTENSION_TO_LANGUAGE: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  py: "python",
  sh: "bash",
  bash: "bash",
  ps1: "powershell",
  psm1: "powershell",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  xml: "xml",
  html: "xml",
  htm: "xml",
  md: "markdown",
  diff: "diff",
  css: "css",
};

/** Extract the file extension (without dot) from a path. */
export function extractFileExtension(filePath: string): string | undefined {
  const match = filePath.match(/\.([a-zA-Z0-9]+)$/);
  return match ? match[1].toLowerCase() : undefined;
}

/** Map a file extension to a highlight.js language name. */
export function extensionToLanguage(ext: string): string | undefined {
  return EXTENSION_TO_LANGUAGE[ext.toLowerCase()];
}

const VIEW_LINE_NUMBER_RE = /^\d+\.\s/;

/**
 * Strip line number prefixes (e.g. "1. ", "42. ") from view tool output lines.
 * Returns the cleaned code and the number of lines stripped.
 */
export function stripViewLineNumbers(lines: string[]): { code: string; lineCount: number } {
  const hasLineNumbers =
    lines.length > 0 && lines.every((line) => VIEW_LINE_NUMBER_RE.test(line) || line.trim() === "");
  if (hasLineNumbers) {
    const stripped = lines.map((line) => (VIEW_LINE_NUMBER_RE.test(line) ? line.replace(VIEW_LINE_NUMBER_RE, "") : line));
    return { code: stripped.join("\n"), lineCount: lines.length };
  }
  return { code: lines.join("\n"), lineCount: lines.length };
}

/** Check if a ToolItem is a view call with file content in additional entries. */
export function isViewToolWithContent(tool: ToolItem): boolean {
  return tool.toolName === "view" && Boolean(tool.additionalEntries) && tool.additionalEntries!.length > 0;
}

/** Extract the file path from a view tool's description or argsText. */
export function extractViewFilePath(tool: ToolItem): string | undefined {
  if (tool.summary.description) return tool.summary.description;
  if (!tool.argsText) return undefined;
  const match = tool.argsText.match(/path\s*[:=]\s*["']([^"']+)["']/i);
  return match ? match[1] : undefined;
}
