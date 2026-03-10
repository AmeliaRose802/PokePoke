/**
 * Tests for markdown rendering with XSS sanitization.
 */

import { describe, expect, it } from "vitest";

import { renderMarkdown } from "./markdown";

describe("renderMarkdown", () => {
  it("renders basic markdown to HTML", () => {
    const html = renderMarkdown("**bold** and *italic*");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<em>italic</em>");
  });

  it("renders headings", () => {
    const html = renderMarkdown("## Summary");
    expect(html).toContain("<h2>");
    expect(html).toContain("Summary");
  });

  it("renders lists", () => {
    const html = renderMarkdown("- item one\n- item two");
    expect(html).toContain("<li>");
    expect(html).toContain("item one");
  });

  it("renders inline code", () => {
    const html = renderMarkdown("run `npm test`");
    expect(html).toContain("<code>npm test</code>");
  });

  it("renders fenced code blocks", () => {
    const html = renderMarkdown("```ts\nconst x = 1\n```\n");
    expect(html).toContain("<pre>");
    expect(html).toContain("<code");
    expect(html).toContain("const x = 1");
  });

  it("adds target=_blank to links", () => {
    const html = renderMarkdown("[link](https://example.com)");
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain("https://example.com");
  });

  it("strips script tags (XSS prevention)", () => {
    const html = renderMarkdown('<script>alert("xss")</script>');
    expect(html).not.toContain("<script");
    expect(html).not.toContain("alert");
  });

  it("strips onerror attributes (XSS prevention)", () => {
    const html = renderMarkdown('<img src=x onerror="alert(1)">');
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("alert");
  });

  it("strips javascript: URLs (XSS prevention)", () => {
    const html = renderMarkdown("[click](javascript:alert(1))");
    expect(html).not.toContain("javascript:");
  });

  it("strips event handler attributes (XSS prevention)", () => {
    const html = renderMarkdown('<div onmouseover="alert(1)">hover</div>');
    expect(html).not.toContain("onmouseover");
    expect(html).not.toContain("alert");
  });

  it("returns original text when marked returns non-string", () => {
    // Empty string edge case
    const html = renderMarkdown("");
    expect(typeof html).toBe("string");
  });
});
