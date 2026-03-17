/**
 * Markdown rendering utility for log output.
 *
 * Uses `marked` to convert markdown text to HTML with server-side
 * syntax highlighting via highlight.js, then sanitizes with DOMPurify
 * to prevent XSS from untrusted log content.
 *
 * Code highlighting is performed during HTML generation (not via
 * post-render DOM mutation) to avoid desynchronising React's virtual
 * DOM from the real DOM, which causes "insertBefore" crashes.
 */

import DOMPurify from "dompurify";
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import diff from "highlight.js/lib/languages/diff";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import markdownLang from "highlight.js/lib/languages/markdown";
import powershell from "highlight.js/lib/languages/powershell";
import python from "highlight.js/lib/languages/python";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import { Marked } from "marked";
import { markedHighlight } from "marked-highlight";

hljs.registerLanguage("bash", bash);
hljs.registerLanguage("diff", diff);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("json", json);
hljs.registerLanguage("markdown", markdownLang);
hljs.registerLanguage("powershell", powershell);
hljs.registerLanguage("python", python);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("yaml", yaml);

const marked = new Marked(
  markedHighlight({
    langPrefix: "hljs language-",
    highlight(code, lang) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value;
      }
      return hljs.highlightAuto(code).value;
    },
  }),
  {
    breaks: true,
    gfm: true,
  },
);

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
