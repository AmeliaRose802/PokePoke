/**
 * Tests for LogPanel tool-call collapsing.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LogEntry } from "../types";
import { LogPanel } from "./LogPanel";

function mk(ts: number, message: string): LogEntry {
  return { timestamp: ts, message, target: "agent", style: null };
}

describe("LogPanel", () => {
  it("collapses copilot tool batch header + sequential tools into a batch accordion", () => {
    const logs: LogEntry[] = [
      mk(1, "Now I need to search for a pattern."),
      mk(2, "[Copilot] Calling 2 tool(s)..."),
      mk(3, "[Tool] grep({'pattern': 'foo'})"),
      mk(4, "[Result] found"),
      mk(5, "[Tool] grep({'pattern': 'bar'})"),
      mk(6, "[Result] found2"),
      mk(7, "Done."),
    ];

    render(<LogPanel title="Agent" icon="🤖" logs={logs} accentColor="#7dcfff" />);

    // Header should be collapsed away (not rendered as a raw log line)
    expect(screen.queryByText("[Copilot] Calling 2 tool(s)...")).not.toBeInTheDocument();

    // Narration gets collapsed when followed by tool calls
    expect(screen.getByText(/Narration \(1 lines\)/)).toBeInTheDocument();

    // Batch summary present with progress indicator
    expect(screen.getByText(/Tool batch \(2 calls\)/)).toBeInTheDocument();
    expect(screen.getByText("2/2")).toBeInTheDocument();

    // Grouped tool summary present
    expect(screen.getByText("🔧 grep ×2")).toBeInTheDocument();
  });

  it("renders a single tool call as a normal tool accordion", () => {
    const logs: LogEntry[] = [mk(1, "[Tool] view({'path': 'README.md'})"), mk(2, "[Result] ok")];

    render(<LogPanel title="Agent" icon="🤖" logs={logs} accentColor="#7dcfff" />);

    expect(screen.getByText("🔧 view - README.md")).toBeInTheDocument();
    expect(screen.queryByText(/Tool batch/)).not.toBeInTheDocument();
    // Description should also be in a collapsible section
    expect(screen.getByText("Description")).toBeInTheDocument();
  });

  it("flattens single-tool batch to simple tool accordion (no extra nesting)", () => {
    const logs: LogEntry[] = [
      mk(1, "[Copilot] Calling 1 tool(s)..."),
      mk(2, "[Tool] report_intent({'intent': 'Testing'})"),
      mk(3, "✅ Result: Intent logged"),
    ];

    render(<LogPanel title="Agent" icon="🤖" logs={logs} accentColor="#7dcfff" />);

    // Should NOT show batch wrapper or group wrapper for single tool
    expect(screen.queryByText(/Tool batch/)).not.toBeInTheDocument();
    expect(screen.queryByText(/×1/)).not.toBeInTheDocument();

    // Should render as simple tool accordion
    expect(screen.getByText("🔧 report_intent")).toBeInTheDocument();
  });

  it("flattens single-item groups to direct tool accordions", () => {
    const logs: LogEntry[] = [
      mk(1, "[Copilot] Calling 2 tool(s)..."),
      mk(2, "[Tool] view({'path': 'a.txt'})"),
      mk(3, "✅ Result: ok"),
      mk(4, "[Tool] edit({'path': 'b.txt'})"),
      mk(5, "✅ Result: Replaced 1 occurrence"),
    ];

    render(<LogPanel title="Agent" icon="🤖" logs={logs} accentColor="#7dcfff" />);

    // Batch wrapper should exist for multiple tools
    expect(screen.getByText(/Tool batch \(2 calls\)/)).toBeInTheDocument();

    // But group wrappers (×1) should NOT exist for single-item groups
    expect(screen.queryByText(/view ×1/)).not.toBeInTheDocument();
    expect(screen.queryByText(/edit ×1/)).not.toBeInTheDocument();

    // Individual tools should be directly visible within the batch
    expect(screen.getByText("🔧 view - a.txt")).toBeInTheDocument();
    expect(screen.getByText("🔧 edit - b.txt")).toBeInTheDocument();
  });

  it("displays tool call descriptions in accordion titles for various tool types", () => {
    const logs: LogEntry[] = [
      mk(1, "[Copilot] Calling 3 tool(s)..."),
      mk(2, "[Tool] powershell({'command': 'npm run build', 'shellId': 'shell-1'})"),
      mk(3, "✅ Result: Build succeeded"),
      mk(4, "[Tool] grep({'pattern': 'TODO', 'path': 'src/'})"),
      mk(5, "✅ Result: Found 5 matches"),
      mk(6, "[Tool] view({'path': 'src/components/Button.tsx'})"),
      mk(7, "✅ Result: File read"),
    ];

    render(<LogPanel title="Agent" icon="🤖" logs={logs} accentColor="#7dcfff" />);

    // Verify descriptions appear inline in accordion titles
    expect(screen.getByText("🔧 powershell - npm run build")).toBeInTheDocument();
    expect(screen.getByText("🔧 grep - TODO")).toBeInTheDocument();
    expect(screen.getByText("🔧 view - src/components/Button.tsx")).toBeInTheDocument();
    // Descriptions should also appear in collapsible Description sections
    const descLabels = screen.getAllByText("Description");
    expect(descLabels.length).toBe(3);
  });

  it("collapses multiline apply_patch tool call into accordion", () => {
    const logs: LogEntry[] = [
      mk(1, "[Tool] apply_patch({'patch': '*** Begin Patch"),
      mk(2, "*** Update File: src/components/App.tsx"),
      mk(3, "@@ -10,5 +10,5 @@"),
      mk(4, " existing line"),
      mk(5, "-old line"),
      mk(6, "+new line"),
      mk(7, " *** End Patch'})"),
      mk(8, "✅ Result: Applied patch successfully"),
    ];

    render(<LogPanel title="Agent" icon="🤖" logs={logs} accentColor="#7dcfff" />);

    // Should render as a collapsed tool accordion with file name
    expect(screen.getByText(/apply_patch — App\.tsx/)).toBeInTheDocument();

    // Patch content lines should be inside the accordion, not as standalone log entries
    const accordion = document.querySelector("details.log-accordion");
    expect(accordion).not.toBeNull();
    const details = accordion!.querySelector(".log-accordion-details");
    expect(details).not.toBeNull();
    // Patch lines are inside the accordion details
    expect(details!.textContent).toContain("@@ -10,5 +10,5 @@");
    expect(details!.textContent).toContain("-old line");
    expect(details!.textContent).toContain("+new line");

    // There should be no standalone log-entry elements outside the accordion for patch content
    const standaloneEntries = document.querySelectorAll(".log-panel-body > .log-entry");
    for (const entry of standaloneEntries) {
      expect(entry.textContent).not.toContain("@@ -10,5 +10,5 @@");
      expect(entry.textContent).not.toContain("-old line");
    }
  });

  it("renders consecutive markdown lines as formatted HTML", () => {
    const logs: LogEntry[] = [
      mk(1, "## Summary"),
      mk(2, "I made the following **changes**:"),
      mk(3, "- Updated `config.ts`"),
      mk(4, "- Fixed the bug"),
    ];

    render(<LogPanel title="Agent" icon="🤖" logs={logs} accentColor="#7dcfff" />);

    // Markdown should be rendered as HTML elements
    const container = document.querySelector(".log-markdown-content");
    expect(container).not.toBeNull();

    // Check for rendered heading
    const heading = container!.querySelector("h2");
    expect(heading).not.toBeNull();
    expect(heading!.textContent).toBe("Summary");

    // Check for rendered bold text
    const bold = container!.querySelector("strong");
    expect(bold).not.toBeNull();
    expect(bold!.textContent).toBe("changes");

    // Check for rendered list items
    const listItems = container!.querySelectorAll("li");
    expect(listItems.length).toBe(2);

    // Check for rendered inline code
    const code = container!.querySelector("code");
    expect(code).not.toBeNull();
    expect(code!.textContent).toBe("config.ts");
  });

  describe("click-to-focus vs text selection", () => {
    afterEach(() => {
      // Restore any getSelection mocks
      vi.restoreAllMocks();
    });

    it("calls onFocus when clicking with no text selected", () => {
      const onFocus = vi.fn();
      // Ensure getSelection returns empty string
      vi.spyOn(window, "getSelection").mockReturnValue({
        toString: () => "",
      } as unknown as Selection);

      render(<LogPanel title="Agent" icon="🤖" logs={[]} accentColor="#7dcfff" onFocus={onFocus} />);

      fireEvent.click(screen.getByText(/Agent/));
      expect(onFocus).toHaveBeenCalledTimes(1);
    });

    it("does NOT call onFocus when text is selected (preserves copy)", () => {
      const onFocus = vi.fn();
      vi.spyOn(window, "getSelection").mockReturnValue({
        toString: () => "some selected text",
      } as unknown as Selection);

      render(<LogPanel title="Agent" icon="🤖" logs={[]} accentColor="#7dcfff" onFocus={onFocus} />);

      fireEvent.click(screen.getByText(/Agent/));
      expect(onFocus).not.toHaveBeenCalled();
    });
  });

  it("renders view tool file content as a code block instead of plain log entries", () => {
    const logs: LogEntry[] = [
      mk(1, "[Tool] view({'path': 'src/app.ts'})"),
      mk(2, '1. import { hello } from "./hello";'),
      mk(3, "2. "),
      mk(4, "3. hello();"),
      mk(5, "✅ Result: File read successfully"),
    ];

    render(<LogPanel title="Agent" icon="🤖" logs={logs} accentColor="#7dcfff" />);

    // Should render tool accordion
    expect(screen.getByText("🔧 view - src/app.ts")).toBeInTheDocument();

    // Should render a code block container for the view content
    const viewContent = document.querySelector(".log-view-content");
    expect(viewContent).not.toBeNull();

    // Code block should contain a <pre><code> for syntax highlighting
    const pre = viewContent!.querySelector("pre");
    expect(pre).not.toBeNull();
    const code = viewContent!.querySelector("code");
    expect(code).not.toBeNull();

    // Code content should have line numbers stripped
    expect(code!.textContent).toContain('import { hello } from "./hello"');
    expect(code!.textContent).toContain("hello();");
    // Line number prefixes should NOT appear in the code block
    expect(code!.textContent).not.toMatch(/^1\. /m);
  });

  it("does not render view content block for non-view tools with additional entries", () => {
    const logs: LogEntry[] = [
      mk(1, "[Tool] powershell({'command': 'npm test'})"),
      mk(2, "PASS tests/app.test.ts"),
      mk(3, "✅ Result: Tests passed"),
    ];

    render(<LogPanel title="Agent" icon="🤖" logs={logs} accentColor="#7dcfff" />);

    // Should NOT have view content block
    const viewContent = document.querySelector(".log-view-content");
    expect(viewContent).toBeNull();
  });

  it("pairs non-interleaved batch results with correct tool accordions", () => {
    const logs: LogEntry[] = [
      mk(1, "[Copilot] Calling 2 tool(s)..."),
      mk(2, "[Tool] grep({'pattern': 'foo'})"),
      mk(3, "[Tool] view({'path': 'README.md'})"),
      mk(4, "✅ Result: Found 5 matches"),
      mk(5, "✅ Result: File contents shown"),
    ];

    render(<LogPanel title="Agent" icon="🤖" logs={logs} accentColor="#7dcfff" />);

    // Batch should exist with all results paired
    expect(screen.getByText(/Tool batch \(2 calls\)/)).toBeInTheDocument();
    expect(screen.getByText("2/2")).toBeInTheDocument();

    // Each tool accordion should show its own result summary (appears in both summary + details)
    expect(screen.getAllByText(/Found 5 matches/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/File contents shown/).length).toBeGreaterThanOrEqual(1);

    // Results should NOT appear as standalone log entries outside the batch
    const allLogEntries = document.querySelectorAll(".log-panel-body > .log-entry");
    for (const entry of allLogEntries) {
      expect(entry.textContent).not.toContain("Result:");
    }
  });
});
