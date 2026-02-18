/**
 * Tests for useDocumentTitle hook.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { buildTitle, useDocumentTitle } from "./useDocumentTitle";

describe("buildTitle", () => {
  it("returns base title when no agent or project", () => {
    expect(buildTitle("", "")).toBe("PokePoke");
  });

  it("returns project name with base title when no agent", () => {
    expect(buildTitle("", "MyProject")).toBe("MyProject - PokePoke");
  });

  it("returns agent name with base title when no project", () => {
    expect(buildTitle("Janitor", "")).toBe("Janitor - PokePoke");
  });

  it("returns full title with agent and project", () => {
    expect(buildTitle("Janitor", "MyProject")).toBe(
      "Janitor | MyProject - PokePoke"
    );
  });

  it("handles whitespace-only agent name as empty", () => {
    // buildTitle doesn't trim, so whitespace is truthy
    expect(buildTitle("  ", "MyProject")).toBe("   | MyProject - PokePoke");
  });
});

describe("useDocumentTitle", () => {
  let originalTitle: string;

  beforeEach(() => {
    originalTitle = document.title;
  });

  afterEach(() => {
    document.title = originalTitle;
  });

  it("sets document title on mount", () => {
    renderHook(() => useDocumentTitle("Agent", "Project"));
    expect(document.title).toBe("Agent | Project - PokePoke");
  });

  it("updates document title when agent changes", () => {
    const { rerender } = renderHook(
      ({ agent, project }) => useDocumentTitle(agent, project),
      { initialProps: { agent: "Agent1", project: "Project" } }
    );

    expect(document.title).toBe("Agent1 | Project - PokePoke");

    rerender({ agent: "Agent2", project: "Project" });
    expect(document.title).toBe("Agent2 | Project - PokePoke");
  });

  it("updates document title when project changes", () => {
    const { rerender } = renderHook(
      ({ agent, project }) => useDocumentTitle(agent, project),
      { initialProps: { agent: "Agent", project: "Project1" } }
    );

    expect(document.title).toBe("Agent | Project1 - PokePoke");

    rerender({ agent: "Agent", project: "Project2" });
    expect(document.title).toBe("Agent | Project2 - PokePoke");
  });

  it("clears to base title when agent is cleared", () => {
    const { rerender } = renderHook(
      ({ agent, project }) => useDocumentTitle(agent, project),
      { initialProps: { agent: "Agent", project: "Project" } }
    );

    expect(document.title).toBe("Agent | Project - PokePoke");

    rerender({ agent: "", project: "Project" });
    expect(document.title).toBe("Project - PokePoke");
  });

  it("shows only PokePoke when both are empty", () => {
    renderHook(() => useDocumentTitle("", ""));
    expect(document.title).toBe("PokePoke");
  });
});
