/**
 * PokePoke Desktop App - Main component.
 *
 * Phase 1: Agent status grid + log panels + stats bar.
 * Connects to the Python orchestrator via the pywebview API.
 */

import "./App.css";
import "highlight.js/styles/github-dark.css";

import { useCallback, useEffect, useState } from "react";

import { AgentLogPanel } from "./components/AgentLogPanel";
import { AgentsPanel } from "./components/AgentsPanel";
import { ConnectionIndicator } from "./components/ConnectionIndicator";
import { LogPanel } from "./components/LogPanel";
import { PromptEditor } from "./components/PromptEditor";
import { SettingsPage } from "./components/SettingsPage";
import { StatsBar } from "./components/StatsBar";
import { StatsPage } from "./components/StatsPage";
import { WorkItemHeader } from "./components/WorkItemHeader";
import type { ModelHistoryEntry } from "./types";
import { useBridge } from "./useBridge";
import { useDocumentTitle } from "./useDocumentTitle";

function App() {
  const bridge = useBridge();
  const [showPrompts, setShowPrompts] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showStatsPage, setShowStatsPage] = useState(false);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [modelHistory, setModelHistory] = useState<ModelHistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [spawnAtLimit, setSpawnAtLimit] = useState(false);
  const repositoryDisplayName = bridge.repositoryName.trim();
  const showRepositoryName = repositoryDisplayName.length > 0;

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

  // Auto-follow: pick the most recently started agent when none is manually selected.
  // Uses started_at (creation time) for stable ordering — volatile fields like
  // last_log_at / last_updated would cause the selection to jump on every poll.
  const autoFollowAgent = (() => {
    if (selectedAgentDetail) return null; // manual selection takes priority
    if (bridge.agents.length === 0) return null;
    const sorted = [...bridge.agents].sort((a, b) => {
      if (a.status === "running" && b.status !== "running") return -1;
      if (b.status === "running" && a.status !== "running") return 1;
      const aTime = a.started_at ?? 0;
      const bTime = b.started_at ?? 0;
      return bTime - aTime;
    });
    return sorted[0] ?? null;
  })();

  // Toggle manual selection: deselect if already manually selected, otherwise select.
  // This correctly handles the auto-follow case where the card appears highlighted
  // but selectedAgentId is still null — clicking should open full-screen, not deselect.
  const handleSelectAgent = useCallback((agentId: string | null) => {
    setSelectedAgentId((prev) => (prev === agentId ? null : agentId));
  }, []);

  const handleOpenPromptEditor = useCallback(() => {
    setShowPrompts(true);
    setShowSettings(false);
  }, []);

  const { getModelHistory } = bridge;

  const handleSpawnAgent = useCallback(async () => {
    const result = await bridge.spawnAgent();
    if (result?.at_limit) {
      setSpawnAtLimit(true);
      // Clear the at-limit indicator after 3 seconds
      setTimeout(() => setSpawnAtLimit(false), 3000);
    }
  }, [bridge]);

  const fallbackAgentLogCount = bridge.agentLogs.length;
  const shouldShowFallbackAgentPanel =
    !selectedAgentDetail && !autoFollowAgent && fallbackAgentLogCount > 0;

  const hasPrimaryAgentOutput =
    selectedAgentDetail !== null ||
    autoFollowAgent !== null ||
    shouldShowFallbackAgentPanel;

  const shouldShowOrchestratorDrawer =
    hasPrimaryAgentOutput && bridge.orchestratorLogs.length > 0;

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
        <div className="app-title-group">
          <div className="app-title">
            <span className="app-logo">🐍</span>
            PokePoke
          </div>
          {showRepositoryName && (
            <div className="app-repo-name" title={repositoryDisplayName}>
              <span className="app-repo-icon" aria-hidden="true">
                📁
              </span>
              <span className="app-repo-text">{repositoryDisplayName}</span>
            </div>
          )}
        </div>
        <div className="app-header-controls">
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
            🌿
          </button>
          <button
            className="prompt-editor-toggle"
            onClick={() => setShowPrompts(true)}
            title="Edit prompt templates"
          >
            🌱
          </button>
          <button
            className="prompt-editor-toggle"
            onClick={() => setShowSettings(true)}
            title="Settings"
          >
            🍃
          </button>
        </div>
      </div>

      {/* Work item header */}
      <WorkItemHeader
        workItem={bridge.workItem}
        agentName={bridge.agentName}
        repositoryName={bridge.repositoryName}
      />

      {/* Main content area with logs and agents panel */}
      <div className="main-content">
        {/* Primary log output + secondary (collapsible) orchestrator log */}
        <div className="log-container">
          {selectedAgentDetail ? (
            <AgentLogPanel
              agent={selectedAgentDetail}
              onClose={() => setSelectedAgentId(null)}
            />
          ) : autoFollowAgent ? (
            <AgentLogPanel
              agent={autoFollowAgent}
              onClose={() => {
                /* no-op: auto-follow has no manual close */
              }}
              showClose={false}
            />
          ) : shouldShowFallbackAgentPanel ? (
            <LogPanel
              title="Agent"
              icon="🐍"
              logs={bridge.agentLogs}
              accentColor="var(--accent-primary)"
            />
          ) : (
            <LogPanel
              title="Orchestrator"
              icon="🌳"
              logs={bridge.orchestratorLogs}
              accentColor="var(--accent-warning)"
            />
          )}

          {shouldShowOrchestratorDrawer ? (
            <details className="orchestrator-collapsible">
              <summary className="orchestrator-collapsible-summary">
                <span className="orchestrator-collapsible-title">
                  🌳 Orchestrator
                </span>
                <span className="log-count">
                  {bridge.orchestratorLogs.length} lines
                </span>
              </summary>
              <div className="orchestrator-collapsible-content">
                <LogPanel
                  title="Orchestrator"
                  icon="🌳"
                  logs={bridge.orchestratorLogs}
                  accentColor="var(--accent-warning)"
                />
              </div>
            </details>
          ) : null}
        </div>

        {/* Agents panel */}
        <AgentsPanel
          agents={bridge.agents}
          currentSessionId={bridge.currentSessionId}
          selectedAgentId={displayedAgentId ?? autoFollowAgent?.agent_id ?? null}
          onSelectAgent={handleSelectAgent}
          onPauseAgent={bridge.pauseAgent}
          onResumeAgent={bridge.resumeAgent}
          onSpawnAgent={handleSpawnAgent}
          orchestratorRunning={bridge.progress.active}
          spawnAtLimit={spawnAtLimit}
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
          onOpenPromptEditor={handleOpenPromptEditor}
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
