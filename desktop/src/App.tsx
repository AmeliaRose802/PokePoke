/**
 * PokePoke Desktop App - Main component.
 *
 * Phase 1: Agent status grid + log panels + stats bar.
 * Connects to the Python orchestrator via the pywebview API.
 */

import { useCallback, useEffect, useState } from "react";
import { useBridge } from "./useBridge";
import { useDocumentTitle } from "./useDocumentTitle";
import { WorkItemHeader } from "./components/WorkItemHeader";
import { LogPanel } from "./components/LogPanel";
import { AgentsPanel } from "./components/AgentsPanel";
import { AgentLogPanel } from "./components/AgentLogPanel";
import { StatsBar } from "./components/StatsBar";
import { ConnectionIndicator } from "./components/ConnectionIndicator";
import { PromptEditor } from "./components/PromptEditor";
import { SettingsPage } from "./components/SettingsPage";
import { StatsPage } from "./components/StatsPage";
import type { ModelHistoryEntry } from "./types";
import "./App.css";

function App() {
  const bridge = useBridge();
  const [activePanel, setActivePanel] = useState<"orchestrator" | "agent">(
    "agent"
  );
  const [showPrompts, setShowPrompts] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showStatsPage, setShowStatsPage] = useState(false);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [modelHistory, setModelHistory] = useState<ModelHistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  // Update browser tab title with current agent and project name
  useDocumentTitle(bridge.agentName, bridge.projectName);

  const hasSelectedAgent =
    selectedAgentId !== null &&
    bridge.agents.some((agent) => agent.agent_id === selectedAgentId);
  const displayedAgentId = hasSelectedAgent ? selectedAgentId : null;
  const selectedAgentDetail =
    displayedAgentId !== null
      ? bridge.agents.find((agent) => agent.agent_id === displayedAgentId) ?? null
      : null;

  // Auto-follow: pick the most recently active agent when none is manually selected
  const autoFollowAgent = (() => {
    if (selectedAgentDetail) return null; // manual selection takes priority
    if (bridge.agents.length === 0) return null;
    // Prefer running agents, then most recently updated
    const sorted = [...bridge.agents].sort((a, b) => {
      if (a.status === "running" && b.status !== "running") return -1;
      if (b.status === "running" && a.status !== "running") return 1;
      const aTime = a.last_log_at ?? a.last_updated ?? 0;
      const bTime = b.last_log_at ?? b.last_updated ?? 0;
      return bTime - aTime;
    });
    return sorted[0] ?? null;
  })();

  const { getModelHistory } = bridge;

  const loadModelHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const history = await getModelHistory(200);
      setModelHistory(history);
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : String(error));
    } finally {
      setHistoryLoading(false);
    }
  }, [getModelHistory]);

  useEffect(() => {
    if (showStatsPage && !historyLoading && modelHistory.length === 0) {
      loadModelHistory().catch(() => {
        // error already captured inside loadModelHistory
      });
    }
  }, [showStatsPage, historyLoading, modelHistory.length, loadModelHistory]);

  return (
    <div className="app">
      {/* Title bar */}
      <div className="app-header">
        <div className="app-title">
          <span className="app-logo">⚡</span>
          PokePoke
        </div>
        <ConnectionIndicator status={bridge.connectionStatus} />
        <button
          className={`finish-after-current-btn${bridge.stopAfterCurrent ? " stopping" : ""}`}
          onClick={() =>
            bridge.stopAfterCurrent
              ? bridge.cancelStopAfterCurrent()
              : bridge.requestStopAfterCurrent()
          }
          title={
            bridge.stopAfterCurrent
              ? "Cancel — continue processing items"
              : "Finish after current item completes"
          }
        >
          {bridge.stopAfterCurrent ? "⏸ Stopping…" : "⏸ Finish after current"}
        </button>
        <button
          className="prompt-editor-toggle"
          onClick={() => setShowStatsPage(true)}
          title="Open stats"
        >
          📈
        </button>
        <button
          className="prompt-editor-toggle"
          onClick={() => setShowPrompts(true)}
          title="Edit prompt templates"
        >
          📝
        </button>
        <button
          className="prompt-editor-toggle"
          onClick={() => setShowSettings(true)}
          title="Settings"
        >
          ⚙
        </button>
      </div>

      {/* Work item header */}
      <WorkItemHeader
        workItem={bridge.workItem}
        agentName={bridge.agentName}
      />

      {/* Main content area with logs and agents panel */}
      <div className="main-content">
        {/* Log panels or selected agent log panel */}
        <div className="log-container">
          {selectedAgentDetail ? (
            <AgentLogPanel
              agent={selectedAgentDetail}
              onClose={() => setSelectedAgentId(null)}
            />
          ) : (
            <>
              <LogPanel
                title="Orchestrator"
                icon="🔧"
                logs={bridge.orchestratorLogs}
                accentColor="#f0ad4e"
                focused={activePanel === "orchestrator"}
                onFocus={() => setActivePanel("orchestrator")}
              />
              {autoFollowAgent ? (
                <AgentLogPanel
                  agent={autoFollowAgent}
                  onClose={() => {/* no-op: auto-follow has no manual close */}}
                  showClose={false}
                />
              ) : (
                <LogPanel
                  title="Agent"
                  icon="🤖"
                  logs={bridge.agentLogs}
                  accentColor="#5cb85c"
                  focused={activePanel === "agent"}
                  onFocus={() => setActivePanel("agent")}
                />
              )}
            </>
          )}
        </div>

        {/* Agents panel */}
        <AgentsPanel
          agents={bridge.agents}
          selectedAgentId={displayedAgentId ?? autoFollowAgent?.agent_id ?? null}
          onSelectAgent={setSelectedAgentId}
        />
      </div>

      {/* Stats footer */}
      <StatsBar
        stats={bridge.stats}
        modelLeaderboard={bridge.modelLeaderboard}
        activeAgentModel={(selectedAgentDetail ?? autoFollowAgent)?.model ?? null}
        onOpenStats={() => setShowStatsPage(true)}
      />

      {/* Prompt editor overlay */}
      {showPrompts && (
        <PromptEditor
          listPrompts={bridge.listPrompts}
          getPrompt={bridge.getPrompt}
          savePrompt={bridge.savePrompt}
          resetPrompt={bridge.resetPrompt}
          onClose={() => setShowPrompts(false)}
        />
      )}

      {/* Settings overlay */}
      {showSettings && (
        <SettingsPage
          getConfig={bridge.getConfig}
          saveConfig={bridge.saveConfig}
          onClose={() => setShowSettings(false)}
        />
      )}

      {showStatsPage && (
        <StatsPage
          stats={bridge.stats}
          modelLeaderboard={bridge.modelLeaderboard}
          activeAgentModel={(selectedAgentDetail ?? autoFollowAgent)?.model ?? null}
          modelHistory={modelHistory}
          historyLoading={historyLoading}
          historyError={historyError}
          onRefreshHistory={loadModelHistory}
          onClose={() => setShowStatsPage(false)}
        />
      )}
    </div>
  );
}

export default App;
