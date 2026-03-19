/**
 * Tests for toolDescriptions utility functions.
 */

import { describe, expect, it } from "vitest";

import { extractDescriptionFromArgs } from "./toolDescriptions";

describe("extractDescriptionFromArgs", () => {
  describe("JSON format (single quotes)", () => {
    it("extracts path for view tool", () => {
      expect(extractDescriptionFromArgs("view", "{'path': 'README.md'}")).toBe("README.md");
    });

    it("extracts command for powershell tool", () => {
      expect(extractDescriptionFromArgs("powershell", "{'command': 'npm run build'}")).toBe("npm run build");
    });

    it("extracts pattern for grep tool", () => {
      expect(extractDescriptionFromArgs("grep", "{'pattern': 'TODO', 'path': 'src/'}")).toBe("TODO");
    });

    it("extracts path for edit tool", () => {
      expect(extractDescriptionFromArgs("edit", "{'path': 'src/app.ts'}")).toBe("src/app.ts");
    });

    it("extracts path for create tool", () => {
      expect(extractDescriptionFromArgs("create", "{'path': 'src/new.ts'}")).toBe("src/new.ts");
    });

    it("extracts pattern for glob tool", () => {
      expect(extractDescriptionFromArgs("glob", "{'pattern': '**/*.ts'}")).toBe("**/*.ts");
    });

    it("prefers description field over command", () => {
      expect(
        extractDescriptionFromArgs("powershell", "{'description': 'Install deps', 'command': 'npm install'}"),
      ).toBe("Install deps");
    });
  });

  describe("JSON format (double quotes)", () => {
    it("extracts path for view tool", () => {
      expect(extractDescriptionFromArgs("view", '{"path": "README.md"}')).toBe("README.md");
    });

    it("extracts command for powershell tool", () => {
      expect(extractDescriptionFromArgs("powershell", '{"command": "npm test"}')).toBe("npm test");
    });
  });

  describe("regex fallback for non-JSON formats", () => {
    it("extracts path with equals sign syntax", () => {
      expect(extractDescriptionFromArgs("view", 'path="src/file.ts"')).toBe("src/file.ts");
    });

    it("extracts path with colon syntax", () => {
      expect(extractDescriptionFromArgs("view", 'path: "src/file.ts"')).toBe("src/file.ts");
    });

    it("extracts command for powershell with equals", () => {
      expect(extractDescriptionFromArgs("powershell", 'command="npm run build"')).toBe("npm run build");
    });

    it("extracts pattern for grep with single quotes", () => {
      expect(extractDescriptionFromArgs("grep", "pattern='TODO'")).toBe("TODO");
    });

    it("prefers description field in non-JSON", () => {
      expect(extractDescriptionFromArgs("powershell", 'description="Build project", command="npm run build"')).toBe(
        "Build project",
      );
    });

    it("extracts path for apply_patch", () => {
      expect(extractDescriptionFromArgs("apply_patch", 'path="src/index.ts"')).toBe("src/index.ts");
    });

    it("extracts query first line for run_kusto_query", () => {
      expect(extractDescriptionFromArgs("run_kusto_query", 'query="Incidents | where Id > 0"')).toBe(
        "Incidents | where Id > 0",
      );
    });
  });

  describe("edge cases", () => {
    it("returns undefined for empty args", () => {
      expect(extractDescriptionFromArgs("view", "")).toBeUndefined();
    });

    it("returns undefined for undefined args", () => {
      expect(extractDescriptionFromArgs("view", undefined)).toBeUndefined();
    });

    it("returns undefined for unknown tool with no description", () => {
      expect(extractDescriptionFromArgs("unknown_tool", "foo=bar")).toBeUndefined();
    });

    it("returns undefined when no recognizable pattern", () => {
      expect(extractDescriptionFromArgs("view", "just some random text")).toBeUndefined();
    });
  });

  describe("MCP and additional tools - JSON format", () => {
    it("extracts query_name for run_kusto_query", () => {
      expect(extractDescriptionFromArgs("run_kusto_query", "{'query_name': 'GetNodeInfo', 'nodeId': 'abc'}")).toBe(
        "GetNodeInfo",
      );
    });

    it("extracts shellId for read_powershell", () => {
      expect(extractDescriptionFromArgs("read_powershell", "{'shellId': 'shell-1'}")).toBe("shell-1");
    });

    it("extracts shellId for stop_powershell", () => {
      expect(extractDescriptionFromArgs("stop_powershell", "{'shellId': 'shell-2'}")).toBe("shell-2");
    });

    it("extracts incidentId for get_incident_context", () => {
      expect(extractDescriptionFromArgs("get_incident_context", "{'incidentId': '12345'}")).toBe("Incident 12345");
    });

    it("extracts queueName for get_incidents_in_queue", () => {
      expect(extractDescriptionFromArgs("get_incidents_in_queue", "{'queueName': 'DRI\\\\MyQueue'}")).toBe(
        "DRI\\MyQueue",
      );
    });

    it("extracts symptoms for search_similar_incidents", () => {
      expect(
        extractDescriptionFromArgs("search_similar_incidents", "{'symptoms': 'Node unreachable after reboot'}"),
      ).toBe("Node unreachable after reboot");
    });

    it("extracts containerId for resolve_to_nodeid", () => {
      expect(extractDescriptionFromArgs("resolve_to_nodeid", "{'containerId': 'abc-123'}")).toBe("abc-123");
    });

    it("extracts nodeId for check_heartbeat", () => {
      expect(extractDescriptionFromArgs("check_heartbeat", "{'nodeId': 'node-42'}")).toBe("node-42");
    });

    it("extracts nodeId for get_node_status", () => {
      expect(extractDescriptionFromArgs("get_node_status", "{'nodeId': 'node-99'}")).toBe("node-99");
    });

    it("extracts nodeId for check_node_health", () => {
      expect(extractDescriptionFromArgs("check_node_health", "{'node_id': 'n-7'}")).toBe("n-7");
    });

    it("extracts workflowName for run_workflow", () => {
      expect(extractDescriptionFromArgs("run_workflow", "{'workflowName': 'RestartAgent'}")).toBe("RestartAgent");
    });

    it("extracts name for get_workflow_schema", () => {
      expect(extractDescriptionFromArgs("get_workflow_schema", "{'name': 'RestartAgent'}")).toBe("RestartAgent");
    });

    it("extracts name for get_query_schema", () => {
      expect(extractDescriptionFromArgs("get_query_schema", "{'name': 'GetNodeInfo'}")).toBe("GetNodeInfo");
    });

    it("extracts path for read_file", () => {
      expect(extractDescriptionFromArgs("read_file", "{'path': 'src/main.ts'}")).toBe("src/main.ts");
    });

    it("extracts nodeId for check_agent_package", () => {
      expect(extractDescriptionFromArgs("check_agent_package", "{'nodeId': 'node-5'}")).toBe("node-5");
    });
  });

  describe("MCP tools - regex fallback", () => {
    it("extracts incidentId for get_incident_context", () => {
      expect(extractDescriptionFromArgs("get_incident_context", "incidentId='67890'")).toBe("Incident 67890");
    });

    it("extracts nodeId for check_heartbeat with regex", () => {
      expect(extractDescriptionFromArgs("check_heartbeat", 'nodeId="node-abc"')).toBe("node-abc");
    });

    it("extracts workflowName for run_workflow with regex", () => {
      expect(extractDescriptionFromArgs("run_workflow", "workflowName='DiagnoseNode'")).toBe("DiagnoseNode");
    });

    it("extracts query_name for run_kusto_query over inline query", () => {
      expect(extractDescriptionFromArgs("run_kusto_query", "query_name='GetNodeInfo'")).toBe("GetNodeInfo");
    });
  });
});
