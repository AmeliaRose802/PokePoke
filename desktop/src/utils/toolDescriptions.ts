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
    // Not JSON, fall back to string parsing
  }

  return undefined;
}
