/**
 * Markdown rendering utility for log output.
 *
 * Uses `marked` to convert markdown text to HTML, then sanitizes
 * with DOMPurify to prevent XSS from untrusted log content.
 */

import DOMPurify from "dompurify";
import { Marked } from "marked";

const marked = new Marked({
  breaks: true,
  gfm: true,
});

/**
 * Render a markdown string to sanitized HTML.
 * Scripts and dangerous attributes are stripped.  Links open in a new tab.
 */
export function renderMarkdown(text: string): string {
  const raw = marked.parse(text);
  if (typeof raw !== "string") return text;

  const clean = DOMPurify.sanitize(raw, {
    ADD_ATTR: ["target"],
  });

  // Ensure links open in a new tab
  return clean.replace(/<a\s+href="/g, '<a target="_blank" rel="noopener noreferrer" href="');
}
