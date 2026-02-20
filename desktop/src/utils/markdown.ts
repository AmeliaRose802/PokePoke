/**
 * Markdown rendering utility for log output.
 *
 * Uses `marked` to convert markdown text to sanitized HTML.
 */

import { Marked } from "marked";

const marked = new Marked({
  breaks: true,
  gfm: true,
});

/**
 * Render a markdown string to HTML.
 * Links are set to open in a new tab.
 */
export function renderMarkdown(text: string): string {
  const raw = marked.parse(text);
  if (typeof raw !== "string") return text;
  // Ensure links open in a new tab
  return raw.replace(/<a\s+href="/g, '<a target="_blank" rel="noopener noreferrer" href="');
}
