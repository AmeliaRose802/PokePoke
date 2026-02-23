import { useCallback, useEffect, useMemo, useState } from "react";

import type { SetupConfigPayload, SetupStatus } from "../types";
import type { BridgeState } from "../useBridge";

type Step = "git" | "beads" | "config" | "prompts" | "summary";

function guessProjectName(status: SetupStatus | null): string {
  if (!status) return "";
  const root = status.project_root.trim();
  const parts = root.split(/[/\\]/).filter(Boolean);
  return parts[parts.length - 1] ?? "";
}

export function SetupWizard({ bridge }: { bridge: BridgeState }) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("git");

  const [defaultBranch, setDefaultBranch] = useState<string>("main");
  const [scaffoldPrompts, setScaffoldPrompts] = useState<boolean>(false);
  const [creating, setCreating] = useState<boolean>(false);

  const [config, setConfig] = useState<SetupConfigPayload>({
    project_name: "",
    default_model: "claude-opus-4.6",
    fallback_model: "claude-sonnet-4.5",
    max_parallel_agents: 1,
    default_branch: "main",
  });

  const refreshStatus = useCallback(async () => {
    if (!bridge.checkSetupStatus) return;
    try {
      const next = await bridge.checkSetupStatus();
      setStatus(next);

      const guessed = guessProjectName(next);
      setConfig((prev) => ({
        ...prev,
        project_name: prev.project_name || guessed,
      }));

      if (next.is_git_repo && !next.beads_initialized) setStep("beads");
      if (next.is_git_repo && next.beads_initialized && !next.config_exists)
        setStep("config");
      if (next.is_git_repo && next.beads_initialized && next.config_exists)
        setStep("prompts");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [bridge]);

  useEffect(() => {
    if (bridge.connectionStatus !== "connected") return;
    refreshStatus().catch(() => {
      // error is captured in state
    });
  }, [bridge.connectionStatus, refreshStatus]);

  const needsSetup = status?.needs_setup === true;
  const canStart = useMemo(() => {
    if (!status) return false;
    return status.is_git_repo && status.beads_initialized && status.config_exists;
  }, [status]);

  const handleGitInit = useCallback(async () => {
    setCreating(true);
    setError(null);
    try {
      const result = await bridge.gitInit(defaultBranch);
      if (!result?.success) {
        setError(result?.error ?? "git init failed");
        return;
      }
      await refreshStatus();
      setStep("beads");
    } finally {
      setCreating(false);
    }
  }, [bridge, defaultBranch, refreshStatus]);

  const handleBeadsInit = useCallback(async () => {
    setCreating(true);
    setError(null);
    try {
      const result = await bridge.bdInit();
      if (!result?.success) {
        setError("bd init failed");
        return;
      }
      await refreshStatus();
      setStep("config");
    } finally {
      setCreating(false);
    }
  }, [bridge, refreshStatus]);

  const handleCreateConfig = useCallback(async () => {
    setCreating(true);
    setError(null);
    try {
      const result = await bridge.createDefaultConfig({
        ...config,
        default_branch: defaultBranch,
      });
      if (!result?.saved) {
        setError("Failed to create .pokepoke/config.yaml");
        return;
      }
      await refreshStatus();
      setStep("prompts");
    } finally {
      setCreating(false);
    }
  }, [bridge, config, defaultBranch, refreshStatus]);

  const handleScaffoldPrompts = useCallback(async () => {
    setCreating(true);
    setError(null);
    try {
      const result = await bridge.scaffoldPromptOverrides(["beads-item"], false);
      if (!result?.success) {
        setError("Failed to scaffold prompt overrides");
        return;
      }
      await refreshStatus();
      setStep("summary");
    } finally {
      setCreating(false);
    }
  }, [bridge, refreshStatus]);

  const handleStart = useCallback(async () => {
    setCreating(true);
    setError(null);
    try {
      if (scaffoldPrompts) {
        const result = await bridge.scaffoldPromptOverrides(["beads-item"], false);
        if (!result?.success) {
          setError("Failed to scaffold prompt overrides");
          return;
        }
      }
      await bridge.completeSetup();
      await refreshStatus();
    } finally {
      setCreating(false);
    }
  }, [bridge, refreshStatus, scaffoldPrompts]);

  if (!needsSetup) return null;

  return (
    <div className="setup-overlay" role="dialog" aria-modal="true">
      <div className="setup-modal">
        <div className="setup-header">
          <div className="setup-title">First-time setup</div>
          <div className="setup-subtitle">
            This directory isn’t initialized for PokePoke yet.
          </div>
        </div>

        <div className="setup-body">
          <div className="setup-status">
            <div className="setup-status-row">
              <span className="setup-status-label">Project root</span>
              <span className="setup-status-value" title={status?.project_root}>
                {status?.project_root ?? ""}
              </span>
            </div>
            <div className="setup-status-row">
              <span className="setup-status-label">Git</span>
              <span className="setup-status-value">
                {status?.is_git_repo ? "✅" : "❌"}
              </span>
            </div>
            <div className="setup-status-row">
              <span className="setup-status-label">Beads</span>
              <span className="setup-status-value">
                {!status?.beads_installed
                  ? "❌ bd not found"
                  : status?.beads_initialized
                    ? "✅"
                    : "❌"}
              </span>
            </div>
            <div className="setup-status-row">
              <span className="setup-status-label">Config</span>
              <span className="setup-status-value" title={status?.config_path}>
                {status?.config_exists ? "✅" : "❌"}
              </span>
            </div>
          </div>

          {error && <div className="setup-error">{error}</div>}

          {!status?.is_git_repo && step === "git" ? (
            <div className="setup-step">
              <h3>1) Initialize git</h3>
              <p>
                PokePoke projects should be git repositories.
              </p>
              <label className="setup-field">
                Default branch
                <input
                  value={defaultBranch}
                  onChange={(e) => setDefaultBranch(e.target.value)}
                  disabled={creating}
                />
              </label>
              <div className="setup-actions">
                <button onClick={handleGitInit} disabled={creating}>
                  Initialize git repo
                </button>
              </div>
            </div>
          ) : !status?.beads_initialized && step === "beads" ? (
            <div className="setup-step">
              <h3>2) Initialize beads</h3>
              <p>
                Beads is used for task tracking (bd). This will run <code>bd init</code>.
              </p>
              <div className="setup-actions">
                <button
                  onClick={handleBeadsInit}
                  disabled={creating || !status?.beads_installed}
                >
                  Run bd init
                </button>
              </div>
            </div>
          ) : !status?.config_exists && step === "config" ? (
            <div className="setup-step">
              <h3>3) Create .pokepoke/config.yaml</h3>

              <label className="setup-field">
                Project name
                <input
                  value={config.project_name}
                  onChange={(e) =>
                    setConfig((prev) => ({ ...prev, project_name: e.target.value }))
                  }
                  disabled={creating}
                />
              </label>

              <label className="setup-field">
                Default model
                <input
                  value={config.default_model}
                  onChange={(e) =>
                    setConfig((prev) => ({ ...prev, default_model: e.target.value }))
                  }
                  disabled={creating}
                />
              </label>

              <label className="setup-field">
                Max parallel agents
                <input
                  type="number"
                  min={1}
                  value={config.max_parallel_agents}
                  onChange={(e) =>
                    setConfig((prev) => ({
                      ...prev,
                      max_parallel_agents: Math.max(1, Number(e.target.value || 1)),
                    }))
                  }
                  disabled={creating}
                />
              </label>

              <label className="setup-field">
                Default branch
                <input
                  value={defaultBranch}
                  onChange={(e) => setDefaultBranch(e.target.value)}
                  disabled={creating}
                />
              </label>

              <div className="setup-actions">
                <button onClick={handleCreateConfig} disabled={creating}>
                  Create config
                </button>
              </div>
            </div>
          ) : step === "prompts" ? (
            <div className="setup-step">
              <h3>4) Optional: scaffold prompt overrides</h3>
              <p>
                This can copy built-in templates into <code>.pokepoke/prompts/</code> so
                you can customize them.
              </p>
              <label className="setup-checkbox">
                <input
                  type="checkbox"
                  checked={scaffoldPrompts}
                  onChange={(e) => setScaffoldPrompts(e.target.checked)}
                  disabled={creating}
                />
                Scaffold <code>beads-item.md</code> override
              </label>
              <div className="setup-actions">
                <button
                  onClick={() => setStep("summary")}
                  disabled={creating}
                >
                  Continue
                </button>
                <button
                  onClick={handleScaffoldPrompts}
                  disabled={creating}
                  title="Copies now and continues"
                >
                  Copy now
                </button>
              </div>
            </div>
          ) : (
            <div className="setup-step">
              <h3>5) Summary</h3>
              <ul className="setup-summary">
                <li>Git repo: {status?.is_git_repo ? "✅" : "❌"}</li>
                <li>Beads initialized: {status?.beads_initialized ? "✅" : "❌"}</li>
                <li>Config: {status?.config_exists ? "✅" : "❌"}</li>
                <li>Project name: <code>{config.project_name}</code></li>
                <li>Default model: <code>{config.default_model}</code></li>
                <li>Max agents: <code>{config.max_parallel_agents}</code></li>
                <li>Default branch: <code>{defaultBranch}</code></li>
                <li>Scaffold prompts: {scaffoldPrompts ? "✅" : "❌"}</li>
              </ul>

              <div className="setup-actions">
                <button
                  onClick={handleStart}
                  disabled={creating || !canStart}
                  title={!canStart ? "Complete setup steps first" : "Start orchestrator"}
                >
                  Start
                </button>
                <button onClick={refreshStatus} disabled={creating}>
                  Re-check
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
