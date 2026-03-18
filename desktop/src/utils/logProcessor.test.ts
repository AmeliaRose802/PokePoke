/**
 * Tests for logProcessor utility functions.
 */

import { describe, expect, it } from "vitest";

import type { LogEntry } from "../types";
import {
  buildToolSummary,
  isToolCallMessage,
  parseToolLabel,
  parseToolLabelAndDescription,
  processLogsToRenderItems,
  stringsToLogEntries,
} from "./logProcessor";
import {
  extensionToLanguage,
  extractFileExtension,
  isViewToolWithContent,
  stripViewLineNumbers,
} from "./viewContentHelpers";

function makeEntries(lines: string[]): LogEntry[] {
  return stringsToLogEntries(lines, 1000);
}

describe("parseToolLabel", () => {
  it("extracts tool name and path for view tool", () => {
    const message = "[Tool] view({'path': 'README.md'})";
    const label = parseToolLabel(message);
    expect(label).toBe("🔧 view - README.md");
  });

  it("extracts tool name and command for powershell tool", () => {
    const message = "[Tool] powershell({'command': 'npm run build', 'shellId': 'shell-1'})";
    const label = parseToolLabel(message);
    expect(label).toContain("🔧 powershell - npm run build");
  });

  it("extracts tool name and pattern for grep tool", () => {
    const message = "[Tool] grep({'pattern': 'TODO', 'path': 'src/'})";
    const label = parseToolLabel(message);
    expect(label).toBe("🔧 grep - TODO");
  });

  it("extracts tool name and path for edit tool", () => {
    const message = "[Tool] edit({'path': 'src/app.ts'})";
    const label = parseToolLabel(message);
    expect(label).toBe("🔧 edit - src/app.ts");
  });

  it("extracts tool name and path for create tool", () => {
    const message = "[Tool] create({'path': 'src/components/NewComponent.tsx'})";
    const label = parseToolLabel(message);
    expect(label).toBe("🔧 create - src/components/NewComponent.tsx");
  });

  it("extracts tool name and pattern for glob tool", () => {
    const message = "[Tool] glob({'pattern': '**/*.ts'})";
    const label = parseToolLabel(message);
    expect(label).toBe("🔧 glob - **/*.ts");
  });

  it("returns just tool name if no description available", () => {
    const message = "[Tool] report_intent({'intent': 'Testing'})";
    const label = parseToolLabel(message);
    expect(label).toBe("🔧 report_intent");
  });

  it("truncates long descriptions", () => {
    const longPath = "a".repeat(100);
    const message = `[Tool] view({'path': '${longPath}'})`;
    const label = parseToolLabel(message);
    expect(label.length).toBeLessThan(message.length);
    expect(label).toContain("…");
  });

  it("parses 🔧 prefixed tool calls", () => {
    const message = "🔧 grep({'pattern': 'TODO', 'path': 'src/'})";
    const label = parseToolLabel(message);
    expect(label).toBe("🔧 grep - TODO");
  });

  it("parses 🔧 prefixed powershell with leading spaces", () => {
    const message = "  🔧 powershell({'command': 'npm install'})";
    const label = parseToolLabel(message);
    expect(label).toContain("🔧 powershell - npm install");
  });

  it("handles messages without Tool prefix", () => {
    const message = "Some other message";
    const label = parseToolLabel(message);
    expect(label).toBe("Some other message");
  });
});

describe("buildToolSummary", () => {
  it("includes description from tool call message as separate field", () => {
    const callMessage = "[Tool] view({'path': 'README.md'})";
    const summary = buildToolSummary(callMessage);
    expect(summary.toolLabel).toBe("🔧 view");
    expect(summary.description).toBe("README.md");
  });

  it("includes both description and result summary", () => {
    const callMessage = "[Tool] grep({'pattern': 'TODO'})";
    const resultMessage = "✅ Result: Found 5 matches";
    const summary = buildToolSummary(callMessage, resultMessage);
    expect(summary.toolLabel).toBe("🔧 grep");
    expect(summary.description).toBe("TODO");
    expect(summary.resultSummary).toBe("✅ Found 5 matches");
  });
  it("handles 🔧 prefixed tool call", () => {
    const callMessage = "🔧 powershell({'command': 'npm run build'})";
    const resultMessage = "✅ Result: Build succeeded";
    const summary = buildToolSummary(callMessage, resultMessage);
    expect(summary.toolLabel).toBe("🔧 powershell");
    expect(summary.description).toBe("npm run build");
    expect(summary.resultSummary).toBe("✅ Build succeeded");
    expect(summary.statusClass).toBe("log-success");
  });
});

describe("parseToolLabelAndDescription", () => {
  it("separates tool name and description for view tool", () => {
    const message = "[Tool] view({'path': 'README.md'})";
    const result = parseToolLabelAndDescription(message);
    expect(result.label).toBe("🔧 view");
    expect(result.description).toBe("README.md");
  });

  it("separates tool name and command for powershell tool", () => {
    const message = "[Tool] powershell({'command': 'npm run build', 'shellId': 'shell-1'})";
    const result = parseToolLabelAndDescription(message);
    expect(result.label).toBe("🔧 powershell");
    expect(result.description).toBe("npm run build");
  });

  it("returns description field when present for powershell", () => {
    const message = `[Tool] powershell({'description': 'Install deps', 'command': 'npm install'})`;
    const result = parseToolLabelAndDescription(message);
    expect(result.label).toBe("🔧 powershell");
    expect(result.description).toBe("Install deps");
  });

  it("returns undefined description when none available", () => {
    const message = "[Tool] report_intent({'intent': 'Testing'})";
    const result = parseToolLabelAndDescription(message);
    expect(result.label).toBe("🔧 report_intent");
    expect(result.description).toBeUndefined();
  });
});

describe("isToolCallMessage", () => {
  it("matches [Tool] prefix", () => {
    expect(isToolCallMessage("[Tool] grep({'pattern': 'foo'})")).toBe(true);
  });

  it("matches 🌿 prefix", () => {
    expect(isToolCallMessage("🌿 view({'path': 'README.md'})")).toBe(true);
  });

  it("matches 🔧 prefix", () => {
    expect(isToolCallMessage("🔧 powershell({'command': 'npm test'})")).toBe(true);
  });

  it("matches 🔧 with leading whitespace", () => {
    expect(isToolCallMessage("  🔧 grep({'pattern': 'TODO'})")).toBe(true);
  });

  it("does not match regular text", () => {
    expect(isToolCallMessage("Installing dependencies...")).toBe(false);
  });
});

describe("processLogsToRenderItems - read tool collapsing", () => {
  it("collapses multi-line file content between tool call and result into accordion", () => {
    const entries = makeEntries([
      "[Tool] view({'path': 'README.md'})",
      "line 1 of file",
      "line 2 of file",
      "✅ Result: File read successfully",
    ]);
    const items = processLogsToRenderItems(entries);

    // Should produce a single tool item, not expanded log entries
    expect(items).toHaveLength(1);
    expect(items[0].type).toBe("tool");

    const tool = (items[0] as { type: "tool"; tool: { additionalEntries?: LogEntry[]; result?: LogEntry } }).tool;
    expect(tool.additionalEntries).toHaveLength(2);
    expect(tool.additionalEntries![0].message).toBe("line 1 of file");
    expect(tool.additionalEntries![1].message).toBe("line 2 of file");
    expect(tool.result?.message).toBe("✅ Result: File read successfully");
  });

  it("collapses file content for 🌿-prefixed tool calls", () => {
    const entries = makeEntries(['🌿 view({"path": "src/app.ts"})', 'import React from "react";', "✅ Result: 1 line"]);
    const items = processLogsToRenderItems(entries);

    expect(items).toHaveLength(1);
    expect(items[0].type).toBe("tool");
    const tool = (items[0] as { type: "tool"; tool: { additionalEntries?: LogEntry[] } }).tool;
    expect(tool.additionalEntries).toHaveLength(1);
  });

  it("batches consecutive tool calls and collapses their content", () => {
    const entries = makeEntries([
      "[Tool] view({'path': 'a.ts'})",
      "file content",
      "✅ Result: ok",
      "[Tool] view({'path': 'b.ts'})",
      "✅ Result: ok",
    ]);
    const items = processLogsToRenderItems(entries);

    // Consecutive tool calls are batched into a tool-batch
    expect(items).toHaveLength(1);
    expect(items[0].type).toBe("tool-batch");
  });

  it("handles tool call with no intermediate content and immediate result", () => {
    const entries = makeEntries(["[Tool] view({'path': 'README.md'})", "✅ Result: File read successfully"]);
    const items = processLogsToRenderItems(entries);

    expect(items).toHaveLength(1);
    expect(items[0].type).toBe("tool");
    const tool = (items[0] as { type: "tool"; tool: { additionalEntries?: LogEntry[] } }).tool;
    expect(tool.additionalEntries).toBeUndefined();
  });
});

describe("processLogsToRenderItems - 🔧 SDK tool format", () => {
  it("collapses a 🔧 tool call with immediate result", () => {
    const entries = makeEntries(["🔧 grep({'pattern': 'TODO'})", "✅ Result: Found 5 matches"]);
    const items = processLogsToRenderItems(entries);
    expect(items).toHaveLength(1);
    expect(items[0].type).toBe("tool");
    if (items[0].type === "tool") {
      expect(items[0].tool.toolName).toBe("grep");
      expect(items[0].tool.result).toBeDefined();
      expect(items[0].tool.summary.resultSummary).toContain("Found 5 matches");
    }
  });

  it("collapses a 🔧 tool call with streaming output before result", () => {
    const entries = makeEntries([
      "🔧 powershell({'command': 'npm install'})",
      "Installing dependencies...",
      "added 100 packages",
      "✅ Result: Packages installed",
    ]);
    const items = processLogsToRenderItems(entries);
    expect(items).toHaveLength(1);
    expect(items[0].type).toBe("tool");
    if (items[0].type === "tool") {
      expect(items[0].tool.toolName).toBe("powershell");
      expect(items[0].tool.result).toBeDefined();
      expect(items[0].tool.additionalEntries).toHaveLength(2);
    }
  });

  it("handles multiple 🔧 tool calls in sequence", () => {
    const entries = makeEntries([
      "🔧 grep({'pattern': 'TODO'})",
      "✅ Result: Found 5 matches",
      "🔧 view({'path': 'README.md'})",
      "✅ Result: File contents shown",
    ]);
    const items = processLogsToRenderItems(entries);
    expect(items).toHaveLength(1);
    expect(items[0].type).toBe("tool-batch");
  });
});

describe("extractFileExtension", () => {
  it("extracts .ts extension", () => {
    expect(extractFileExtension("src/app.ts")).toBe("ts");
  });

  it("extracts .py extension", () => {
    expect(extractFileExtension("main.py")).toBe("py");
  });

  it("extracts .tsx extension", () => {
    expect(extractFileExtension("components/App.tsx")).toBe("tsx");
  });

  it("returns undefined for no extension", () => {
    expect(extractFileExtension("Makefile")).toBeUndefined();
  });

  it("handles paths with dots in directories", () => {
    expect(extractFileExtension("src/v2.0/config.json")).toBe("json");
  });

  it("normalizes to lowercase", () => {
    expect(extractFileExtension("README.MD")).toBe("md");
  });
});

describe("extensionToLanguage", () => {
  it("maps ts to typescript", () => {
    expect(extensionToLanguage("ts")).toBe("typescript");
  });

  it("maps tsx to typescript", () => {
    expect(extensionToLanguage("tsx")).toBe("typescript");
  });

  it("maps py to python", () => {
    expect(extensionToLanguage("py")).toBe("python");
  });

  it("maps json to json", () => {
    expect(extensionToLanguage("json")).toBe("json");
  });

  it("maps ps1 to powershell", () => {
    expect(extensionToLanguage("ps1")).toBe("powershell");
  });

  it("returns undefined for unknown extensions", () => {
    expect(extensionToLanguage("xyz")).toBeUndefined();
  });

  it("is case-insensitive", () => {
    expect(extensionToLanguage("TS")).toBe("typescript");
  });
});

describe("stripViewLineNumbers", () => {
  it("strips line number prefixes from all lines", () => {
    const lines = ["1. first line", "2. second line", "3. third line"];
    const result = stripViewLineNumbers(lines);
    expect(result.code).toBe("first line\nsecond line\nthird line");
    expect(result.lineCount).toBe(3);
  });

  it("handles blank lines mixed with numbered lines", () => {
    const lines = ["1. code", "", "3. more code"];
    const result = stripViewLineNumbers(lines);
    expect(result.code).toBe("code\n\nmore code");
  });

  it("preserves content when no line numbers present", () => {
    const lines = ["no numbers here", "just plain text"];
    const result = stripViewLineNumbers(lines);
    expect(result.code).toBe("no numbers here\njust plain text");
    expect(result.lineCount).toBe(2);
  });

  it("handles single line", () => {
    const lines = ["1. only line"];
    const result = stripViewLineNumbers(lines);
    expect(result.code).toBe("only line");
    expect(result.lineCount).toBe(1);
  });

  it("handles empty array", () => {
    const result = stripViewLineNumbers([]);
    expect(result.code).toBe("");
    expect(result.lineCount).toBe(0);
  });
});

describe("isViewToolWithContent", () => {
  it("returns true for view tool with additional entries", () => {
    const tool = {
      toolName: "view",
      entry: { message: "[Tool] view({'path': 'a.ts'})", target: "agent" as const, style: null, timestamp: 1000 },
      additionalEntries: [{ message: "1. code", target: "agent" as const, style: null, timestamp: 1001 }],
      summary: { toolLabel: "🔧 view" },
    };
    expect(isViewToolWithContent(tool)).toBe(true);
  });

  it("returns false for view tool with no additional entries", () => {
    const tool = {
      toolName: "view",
      entry: { message: "[Tool] view({'path': 'a.ts'})", target: "agent" as const, style: null, timestamp: 1000 },
      summary: { toolLabel: "🔧 view" },
    };
    expect(isViewToolWithContent(tool)).toBe(false);
  });

  it("returns false for non-view tools", () => {
    const tool = {
      toolName: "grep",
      entry: { message: "[Tool] grep({'pattern': 'foo'})", target: "agent" as const, style: null, timestamp: 1000 },
      additionalEntries: [{ message: "match found", target: "agent" as const, style: null, timestamp: 1001 }],
      summary: { toolLabel: "🔧 grep" },
    };
    expect(isViewToolWithContent(tool)).toBe(false);
  });
});
