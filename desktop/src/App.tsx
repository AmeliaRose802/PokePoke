/**
 * PokePoke Desktop App - Main component.
 *
 * Phase 1: Agent status grid + log panels + stats bar.
 * Connects to the Python orchestrator via the pywebview API.
 */

import { useState } from "react";
import { useBridge } from "./useBridge";
import { WorkItemHeader } from "./components/WorkItemHeader";
import { LogPanel } from "./components/LogPanel";
import { StatsBar } from "./components/StatsBar";
import { ConnectionIndicator } from "./components/ConnectionIndicator";
import "./App.css";

function App() {
  const bridge = useBridge();
  const [activePanel, setActivePanel] = useState<"orchestrator" | "agent">(
    "agent"
  );

  return (
    <div className="app">
      {/* Title bar */}
      <div className="app-header">
        <div className="app-title">
          <span className="app-logo">⚡</span>
          PokePoke
        </div>
        <ConnectionIndicator status={bridge.connectionStatus} />
      </div>

      {/* Work item header */}
      <WorkItemHeader
        workItem={bridge.workItem}
        agentName={bridge.agentName}
      />

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

      {/* Stats footer */}
      <StatsBar stats={bridge.stats} />
    </div>
  );
}

export default App;
