/**
 * MCP Server configuration section for the Settings page.
 *
 * Renders a toggle for mcp.enabled, and conditionally shows
 * text inputs for mcp.server_name and mcp.restart_script.
 */

import type { McpServerConfig } from "../types";

interface Props {
  mcpConfig: McpServerConfig;
  onChange: (updates: Partial<McpServerConfig>) => void;
}

export function McpServerSection({ mcpConfig, onChange }: Props) {
  const { enabled = false, name = "", restart_script = "" } = mcpConfig;

  return (
    <div className="settings-section">
      <h3 className="settings-section-title">🔌 MCP Server</h3>

      {/* MCP Enabled Toggle */}
      <div className="settings-field">
        <div className="mcp-toggle-row">
          <label className="settings-label" htmlFor="mcp-enabled">
            Enable MCP Server
          </label>
          <label className="agent-toggle">
            <input
              id="mcp-enabled"
              type="checkbox"
              checked={enabled}
              onChange={(e) => onChange({ enabled: e.target.checked })}
            />
            <span className="toggle-slider"></span>
          </label>
        </div>
        <span className="settings-hint">
          Restart an MCP server between agent runs
        </span>
      </div>

      {enabled && (
        <>
          {/* Server Name */}
          <div className="settings-field">
            <label className="settings-label" htmlFor="mcp-server-name">
              Server Name
            </label>
            <input
              id="mcp-server-name"
              className="settings-input"
              value={name}
              onChange={(e) => onChange({ name: e.target.value })}
              placeholder="e.g. My MCP Server"
            />
            <span className="settings-hint">
              Display name for the MCP server
            </span>
          </div>

          {/* Restart Script */}
          <div className="settings-field">
            <label className="settings-label" htmlFor="mcp-restart-script">
              Restart Script
            </label>
            <input
              id="mcp-restart-script"
              className="settings-input file-path-input"
              value={restart_script}
              onChange={(e) => onChange({ restart_script: e.target.value })}
              placeholder="e.g. scripts/Restart-MCPServer.ps1"
            />
            <span className="settings-hint">
              Path to the script that restarts the MCP server
            </span>
          </div>
        </>
      )}
    </div>
  );
}
