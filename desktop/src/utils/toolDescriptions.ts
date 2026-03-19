/**
 * Tool description extraction utilities.
 */

/**
 * Extract a human-readable description from tool call arguments.
 * Prioritizes explicit 'description' field, then extracts relevant fields for common tools.
 */
export function extractDescriptionFromArgs(toolName: string, argsText?: string): string | undefined {
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
        if (typeof json.query_name === "string") return json.query_name;
        if (typeof json.query === "string") {
          const query = json.query.trim();
          return query.split("\n")[0].slice(0, 60);
        }
      }
      // Shell-related tools: show shellId or command
      if (toolName === "read_powershell" || toolName === "stop_powershell") {
        if (typeof json.shellId === "string") return json.shellId;
        if (typeof json.command === "string") return json.command;
      }
      // MCP incident/queue tools
      if (toolName === "get_incident_context") {
        if (typeof json.incidentId === "string") return `Incident ${json.incidentId}`;
        if (typeof json.incident_id === "string") return `Incident ${json.incident_id}`;
      }
      if (toolName === "get_incidents_in_queue") {
        if (typeof json.queueName === "string") return json.queueName;
        if (typeof json.queue_name === "string") return json.queue_name;
      }
      if (toolName === "search_similar_incidents") {
        if (typeof json.symptoms === "string") return json.symptoms.slice(0, 60);
      }
      // MCP node tools
      if (toolName === "resolve_to_nodeid") {
        const id = json.containerId ?? json.container_id ?? json.vmId ?? json.vm_id ?? json.resourceId;
        if (typeof id === "string") return id;
      }
      if (toolName === "check_heartbeat" || toolName === "get_node_status" || toolName === "check_node_health" || toolName === "check_agent_package") {
        if (typeof json.nodeId === "string") return json.nodeId;
        if (typeof json.node_id === "string") return json.node_id;
      }
      // MCP workflow/task tools
      if (toolName === "run_workflow") {
        if (typeof json.workflowName === "string") return json.workflowName;
        if (typeof json.workflow_name === "string") return json.workflow_name;
      }
      if (toolName === "get_workflow_schema" || toolName === "get_query_schema") {
        if (typeof json.name === "string") return json.name;
      }
      if (toolName === "read_file") {
        if (typeof json.path === "string") return json.path;
        if (typeof json.file === "string") return json.file;
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
    const patterns = [new RegExp(`${key}\\s*[:=]\\s*"([^"]+)"`, "i"), new RegExp(`${key}\\s*[:=]\\s*'([^']+)'`, "i")];
    for (const pattern of patterns) {
      const match = argsText.match(pattern);
      if (match) return match[1];
    }
    return undefined;
  };

  // Check for explicit description field first
  const description = extractValue("description");
  if (description) return description;

  switch (toolName) {
    case "powershell":
      return extractValue("command");
    case "grep":
      return extractValue("pattern") ?? extractValue("path");
    case "run_kusto_query":
      return extractValue("query_name") ?? (() => {
        const q = extractValue("query");
        return q ? q.split("\n")[0].slice(0, 60) : undefined;
      })();
    case "read_powershell":
    case "stop_powershell":
      return extractValue("shellId") ?? extractValue("command");
    case "get_incident_context": {
      const id = extractValue("incidentId") ?? extractValue("incident_id");
      return id ? `Incident ${id}` : undefined;
    }
    case "get_incidents_in_queue":
      return extractValue("queueName") ?? extractValue("queue_name");
    case "search_similar_incidents":
      return extractValue("symptoms")?.slice(0, 60);
    case "resolve_to_nodeid":
      return extractValue("containerId") ?? extractValue("container_id") ?? extractValue("vmId") ?? extractValue("vm_id");
    case "check_heartbeat":
    case "get_node_status":
    case "check_node_health":
    case "check_agent_package":
      return extractValue("nodeId") ?? extractValue("node_id");
    case "run_workflow":
      return extractValue("workflowName") ?? extractValue("workflow_name");
    case "get_workflow_schema":
    case "get_query_schema":
      return extractValue("name");
    case "view":
    case "edit":
    case "create":
    case "apply_patch":
    case "glob":
    case "read_file":
      return extractValue("path") ?? extractValue("pattern");
  }

  return undefined;
}
