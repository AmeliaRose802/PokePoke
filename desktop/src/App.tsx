/**
 * PokePoke Desktop App - Main component.
 *
 * Phase 1: Agent status grid + log panels + stats bar.
 * Connects to the Python orchestrator via the pywebview API.
 */

import { useCallback, useEffect, useState } from "react";
import { useBridge } from "./useBridge";
import { WorkItemHeader } from "./components/WorkItemHeader";
import { LogPanel } from "./components/LogPanel";
import { AgentsPanel } from "./components/AgentsPanel";
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

  const hasSelectedAgent =
    selectedAgentId !== null &&
    bridge.agents.some((agent) => agent.agent_id === selectedAgentId);
  const displayedAgentId = hasSelectedAgent ? selectedAgentId : null;
  const selectedAgentDetail =
    displayedAgentId !== null
      ? bridge.agents.find((agent) => agent.agent_id === displayedAgentId) ?? null
      : null;

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
        repositoryName={bridge.repositoryName}
      />

      {/* Main content area with logs and agents panel */}
      <div className="main-content">
        {/* Log panels */}
        <div className="log-container">
          <LogPanel
            title="Orchestrator"
            icon="🔧"
            logs={bridge.orchestratorLogs}
            accentColor="#f0ad4e"
            focused={activePanel === "orchestrator"}
            onFocus={() => setActivePanel("orchestrator")}
          />
          <LogPanel
            title="Agent"
            icon="🤖"
            logs={bridge.agentLogs}
            accentColor="#5cb85c"
            focused={activePanel === "agent"}
            onFocus={() => setActivePanel("agent")}
          />
        </div>

        {/* Agents panel */}
        <AgentsPanel
          agents={bridge.agents}
          selectedAgentId={displayedAgentId}
          selectedAgentDetail={selectedAgentDetail}
          onSelectAgent={setSelectedAgentId}
        />
      </div>

      {/* Stats footer */}
      <StatsBar
        stats={bridge.stats}
        modelLeaderboard={bridge.modelLeaderboard}
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
