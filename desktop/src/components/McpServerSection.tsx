/**
 * MCP Server configuration section for the Settings page.
 *
 * Renders a toggle for MCP enabled, and conditionally shows
 * text inputs for server name and restart script.
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
      <h3 className="settings-section-title">🖧 MCP Server</h3>

      <div className="settings-field">
        <label className="settings-label" htmlFor="mcp-enabled">
          Enable MCP server
        </label>
        <div className="settings-checkbox-row">
          <input
            id="mcp-enabled"
            type="checkbox"
            checked={enabled}
            onChange={(e) => onChange({ enabled: e.target.checked })}
          />
          <span className="settings-hint">Controls MCP server integration and restart script usage.</span>
        </div>
      </div>

      {enabled && (
        <>
          <div className="settings-field">
            <label className="settings-label" htmlFor="mcp-name">
              MCP server name (optional)
            </label>
            <input
              id="mcp-name"
              className="settings-input"
              value={name}
              onChange={(e) => onChange({ name: e.target.value })}
              placeholder="e.g. My MCP Server"
            />
            <span className="settings-hint">Friendly display name for the MCP server.</span>
          </div>
          <div className="settings-field">
            <label className="settings-label" htmlFor="mcp-restart-script">
              Restart script (optional)
            </label>
            <input
              id="mcp-restart-script"
              className="settings-input"
              value={restart_script}
              onChange={(e) => onChange({ restart_script: e.target.value })}
              placeholder="scripts/Restart-MCPServer.ps1"
            />
            <span className="settings-hint">Path to restart the MCP server after configuration changes.</span>
          </div>
        </>
      )}
    </div>
  );
}
