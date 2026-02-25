/**
 * Tool description extraction utilities.
 */

/**
 * Extract a human-readable description from tool call arguments.
 * Prioritizes explicit 'description' field, then extracts relevant fields for common tools.
 */
export function extractDescriptionFromArgs(
  toolName: string,
  argsText?: string
): string | undefined {
  if (!argsText) return undefined;

  // Try to parse as JSON - handle both single quotes and double quotes
  try {
    // Convert single quotes to double quotes for JSON parsing
    const jsonStr = argsText.replace(/'/g, '"');
    const json = JSON.parse(jsonStr);
    if (typeof json === "object" && json !== null) {
      // Check for description field
      if (typeof json.description === "string") {
        return json.description;
      }
      // For common tools, extract relevant fields
      if (toolName === "powershell") {
        if (typeof json.command === "string") {
          return json.command;
        }
      }
      if (toolName === "run_kusto_query") {
        if (typeof json.query === "string") {
          const query = json.query.trim();
          // Show first line of query as description
          const firstLine = query.split("\n")[0];
          return firstLine.slice(0, 60);
        }
      }
      // For grep, prioritize pattern over path
      if (toolName === "grep") {
        if (typeof json.pattern === "string") {
          return json.pattern;
        }
        if (typeof json.path === "string") {
          return json.path;
        }
      }
      // For file operations, show the path
      if (["view", "edit", "create", "apply_patch", "glob"].includes(toolName)) {
        if (typeof json.path === "string") {
          return json.path;
        }
        if (typeof json.pattern === "string") {
          return json.pattern;
        }
      }
    }
  } catch {
    // Not JSON, fall back to regex-based extraction below
  }

  // Fallback: try regex-based extraction for when JSON parsing fails
  const extractValue = (key: string): string | undefined => {
    // Try: key="value" or key='value' or key: "value" or key: 'value'
    const patterns = [
      new RegExp(`${key}\\s*[:=]\\s*"([^"]+)"`, 'i'),
      new RegExp(`${key}\\s*[:=]\\s*'([^']+)'`, 'i'),
    ];
    for (const pattern of patterns) {
      const match = argsText.match(pattern);
      if (match) return match[1];
    }
    return undefined;
  };

  // Check for explicit description field first
  const description = extractValue('description');
  if (description) return description;

  // Tool-specific extraction
  switch (toolName) {
    case 'powershell':
      return extractValue('command');
    case 'grep':
      return extractValue('pattern') ?? extractValue('path');
    case 'run_kusto_query': {
      const query = extractValue('query');
      return query ? query.split('\n')[0].slice(0, 60) : undefined;
    }
    case 'view':
    case 'edit':
    case 'create':
    case 'apply_patch':
    case 'glob':
      return extractValue('path') ?? extractValue('pattern');
  }

  return undefined;
}
