/**
 * Tests for SettingsPage component.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConfigResponse, ProjectConfig } from "../types";
import { SettingsPage } from "./SettingsPage";

describe("SettingsPage", () => {
  const mockGetConfig = vi.fn();
  const mockSaveConfig = vi.fn();
  const mockOnClose = vi.fn();

  const defaultConfig: ProjectConfig = {
    project_name: "TestProject",
    models: {
      default: "claude-sonnet-4.5",
      fallback: "claude-sonnet-4",
      candidate_models: ["gpt-5", "gpt-5-codex"],
      ab_testing_enabled: true,
    },
    mcp_server: {
      enabled: true,
      restart_script: "scripts/Restart-MCPServer.ps1",
      name: "ICM MCP",
    },
    maintenance: {
      agents: [
        {
          name: "Janitor",
          enabled: true,
          frequency: 5,
          prompt_file: "janitor.md",
          needs_worktree: false,
          merge_changes: false,
        },
      ],
    },
  };

  const defaultConfigResponse: ConfigResponse = {
    path: "/test/.pokepoke/config.yaml",
    config: defaultConfig,
    exists: true,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetConfig.mockResolvedValue(defaultConfigResponse);
    mockSaveConfig.mockResolvedValue(true);
  });

  it("should display loading state initially", () => {
    mockGetConfig.mockImplementation(() => new Promise(() => {})); // never resolves
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    expect(screen.getByText("Loading configuration…")).toBeInTheDocument();
  });

  it("should load and display configuration", async () => {
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    expect(mockGetConfig).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Default Model")).toHaveValue("claude-sonnet-4.5");
    expect(screen.getByLabelText("Fallback Model")).toHaveValue("claude-sonnet-4");
  });

  it("should display MCP server configuration", async () => {
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const mcpToggle = screen.getByLabelText("Enable MCP server");
    expect(mcpToggle).toBeChecked();
    expect(screen.getByLabelText("MCP server name (optional)")).toHaveValue("ICM MCP");
    expect(screen.getByLabelText("Restart script (optional)")).toHaveValue("scripts/Restart-MCPServer.ps1");
  });

  it("should toggle between single-model and A/B testing modes", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const abToggle = screen.getByLabelText("Enable A/B testing mode");
    const defaultInput = screen.getByLabelText("Default Model");
    const fallbackInput = screen.getByLabelText("Fallback Model");

    expect(abToggle).toBeChecked();
    expect(defaultInput).toBeDisabled();
    expect(fallbackInput).toBeDisabled();
    expect(screen.getByPlaceholderText("Add model…")).toBeEnabled();
    expect(screen.getByText("Ignored while A/B testing is active")).toBeInTheDocument();

    await user.click(abToggle);

    expect(abToggle).not.toBeChecked();
    expect(defaultInput).not.toBeDisabled();
    expect(fallbackInput).not.toBeDisabled();
    expect(screen.queryByPlaceholderText("Add model…")).not.toBeInTheDocument();
    expect(screen.getByText("Enable A/B testing to configure candidate models")).toBeInTheDocument();
    expect(screen.getByText("Primary model for agent tasks")).toBeInTheDocument();
  });

  it("should hide MCP inputs when MCP server disabled", async () => {
    const disabledMcpConfig: ConfigResponse = {
      ...defaultConfigResponse,
      config: {
        ...defaultConfig,
        mcp_server: {
          enabled: false,
          name: "",
          restart_script: "",
        },
      },
    };
    mockGetConfig.mockResolvedValueOnce(disabledMcpConfig);

    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    expect(screen.getByLabelText("Enable MCP server")).not.toBeChecked();
    expect(screen.queryByLabelText("MCP server name (optional)")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Restart script (optional)")).not.toBeInTheDocument();
  });

  it("should display error when config fails to load", async () => {
    mockGetConfig.mockResolvedValue(null);

    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.getByText("Could not load configuration.")).toBeInTheDocument();
    });
  });

  it("should call onClose when close button clicked", async () => {
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const closeButton = screen.getByText("⚙️ Settings").parentElement?.querySelector(".prompt-close-btn");
    expect(closeButton).toBeInTheDocument();
    await userEvent.click(closeButton!);

    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it("should mark dirty when default model changed", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Enable A/B testing mode"));

    const input = screen.getByLabelText("Default Model");
    await user.clear(input);
    await user.type(input, "gpt-5.2");

    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("should mark dirty when fallback model changed", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Enable A/B testing mode"));

    const input = screen.getByLabelText("Fallback Model");
    await user.clear(input);
    await user.type(input, "gpt-5.1");

    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("should add candidate model chip on Enter", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const chipInput = screen.getByPlaceholderText("Add model…");
    await user.type(chipInput, "claude-opus-4.5{Enter}");

    expect(screen.getByText("claude-opus-4.5")).toBeInTheDocument();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("should remove candidate model chip when x clicked", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const gpt5Chip = screen.getByText("gpt-5").closest(".chip");
    expect(gpt5Chip).toBeInTheDocument();

    const removeButton = gpt5Chip!.querySelector(".chip-remove");
    await user.click(removeButton!);

    expect(screen.queryByText("gpt-5")).not.toBeInTheDocument();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("should not add duplicate candidate models", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const chipInput = screen.getByPlaceholderText("Add model…");
    await user.type(chipInput, "gpt-5{Enter}");

    // Should still only have one gpt-5 chip
    const chips = screen.getAllByText("gpt-5");
    expect(chips.length).toBe(1);
  });

  it("should show Add All button when A/B testing is enabled and not all models added", async () => {
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: "Add All" })).toBeInTheDocument();
  });

  it("should add all known models when Add All is clicked", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Add All" }));

    // All KNOWN_MODELS should appear as chips
    expect(screen.getByText("claude-opus-4.5")).toBeInTheDocument();
    expect(screen.getByText("claude-opus-4.6")).toBeInTheDocument();
    expect(screen.getByText("claude-sonnet-4")).toBeInTheDocument();
    expect(screen.getByText("gpt-5")).toBeInTheDocument();
    expect(screen.getByText("gpt-5.2-codex")).toBeInTheDocument();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("should hide Add All button when all models are already added", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Add All" }));

    // Add All button should disappear since all models are now present
    expect(screen.queryByRole("button", { name: "Add All" })).not.toBeInTheDocument();
  });

  it("should not show Add All button when A/B testing is disabled", async () => {
    const disabledAbConfig: ConfigResponse = {
      ...defaultConfigResponse,
      config: {
        ...defaultConfig,
        models: { ...defaultConfig.models, ab_testing_enabled: false, candidate_models: [] },
      },
    };
    mockGetConfig.mockResolvedValue(disabledAbConfig);

    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: "Add All" })).not.toBeInTheDocument();
  });

  it("should display maintenance agents", async () => {
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    expect(screen.getByText("Janitor")).toBeInTheDocument();
    expect(screen.getByText("📄 janitor.md")).toBeInTheDocument();
  });

  it("should toggle maintenance agent enabled state", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const agentCard = screen.getByText("Janitor").closest(".agent-config") as HTMLElement | null;
    expect(agentCard).toBeTruthy();
    const toggle = within(agentCard!).getByRole("checkbox");
    expect(toggle).toBeChecked();

    await user.click(toggle);

    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("should update maintenance agent frequency", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const frequencyInput = screen.getByDisplayValue("5");
    await user.clear(frequencyInput);
    await user.type(frequencyInput, "10");

    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("should save configuration successfully", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Enable A/B testing mode"));

    const input = screen.getByLabelText("Default Model");
    await user.clear(input);
    await user.type(input, "gpt-5.2");

    const saveButton = screen.getByText("💾 Save");
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockSaveConfig).toHaveBeenCalledTimes(1);
    });

    const savedConfig = mockSaveConfig.mock.calls[0][0];
    expect(savedConfig.models.default).toBe("gpt-5.2");
    expect(savedConfig.models.ab_testing_enabled).toBe(false);
    expect(savedConfig.mcp_server?.restart_script).toBe("scripts/Restart-MCPServer.ps1");

    expect(screen.getByText("Saved")).toBeInTheDocument();
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
  });

  it("should display error message on save failure", async () => {
    const user = userEvent.setup();
    mockSaveConfig.mockResolvedValue(false);

    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Enable A/B testing mode"));

    const input = screen.getByLabelText("Default Model");
    await user.type(input, "x");

    const saveButton = screen.getByText("💾 Save");
    await user.click(saveButton);

    await waitFor(() => {
      expect(screen.getByText("Save failed")).toBeInTheDocument();
    });
  });

  it("should reset changes when reset clicked", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Enable A/B testing mode"));

    const input = screen.getByLabelText("Default Model");
    await user.clear(input);
    await user.type(input, "changed-model");

    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();

    const resetButton = screen.getByText("↩ Reset");
    await user.click(resetButton);

    expect(screen.getByText("Reset to saved values")).toBeInTheDocument();
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Default Model")).toHaveValue("claude-sonnet-4.5");
  });

  it("should disable save button when not dirty", async () => {
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const saveButton = screen.getByText("💾 Save");
    expect(saveButton).toBeDisabled();
  });

  it("should disable reset button when not dirty", async () => {
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const resetButton = screen.getByText("↩ Reset");
    expect(resetButton).toBeDisabled();
  });

  it("should show loading state on save button during save", async () => {
    const user = userEvent.setup();
    mockSaveConfig.mockImplementation(() => new Promise((resolve) => setTimeout(() => resolve(true), 100)));

    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Enable A/B testing mode"));

    const input = screen.getByLabelText("Default Model");
    await user.type(input, "x");

    const saveButton = screen.getByText("💾 Save");
    await user.click(saveButton);

    expect(screen.getByText("…")).toBeInTheDocument();
  });

  it("should handle empty maintenance agents array", async () => {
    const emptyConfig = {
      ...defaultConfigResponse,
      config: {
        ...defaultConfig,
        maintenance: {
          agents: [],
        },
      },
    };
    mockGetConfig.mockResolvedValue(emptyConfig);

    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    expect(screen.getByText("No maintenance agents configured")).toBeInTheDocument();
  });

  it("should add chip on blur if input has value", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const chipInput = screen.getByPlaceholderText("Add model…");
    await user.type(chipInput, "new-model");
    await user.tab(); // triggers blur

    expect(screen.getByText("new-model")).toBeInTheDocument();
  });

  it("should remove last chip on backspace with empty input", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const chipInput = screen.getByPlaceholderText("Add model…");

    // Should have gpt-5-codex as last chip
    expect(screen.getByText("gpt-5-codex")).toBeInTheDocument();

    await user.click(chipInput);
    await user.keyboard("{Backspace}");

    expect(screen.queryByText("gpt-5-codex")).not.toBeInTheDocument();
  });

  it("should include all configuration sections in save", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Enable A/B testing mode"));

    const input = screen.getByLabelText("Default Model");
    await user.type(input, "x");

    const saveButton = screen.getByText("💾 Save");
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockSaveConfig).toHaveBeenCalledTimes(1);
    });

    const savedConfig = mockSaveConfig.mock.calls[0][0];
    expect(savedConfig.project_name).toBe("TestProject");
    expect(savedConfig.models).toBeDefined();
    expect(savedConfig.mcp_server?.name).toBe("ICM MCP");
    expect(savedConfig.maintenance).toBeDefined();
  });

  it("should display and update max parallel agents setting", async () => {
    const user = userEvent.setup();
    const configWithParallelAgents: ConfigResponse = {
      ...defaultConfigResponse,
      config: { ...defaultConfig, max_parallel_agents: 2 },
    };
    mockGetConfig.mockResolvedValueOnce(configWithParallelAgents);

    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const input = screen.getByLabelText("Max Parallel Agents");
    expect(input).toHaveValue(2);
    // Warning should appear when > 1
    expect(screen.getByText(/Parallel mode is experimental/)).toBeInTheDocument();

    await user.clear(input);
    await user.type(input, "3");

    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("should not show parallel warning when max_parallel_agents is 1", async () => {
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    expect(screen.queryByText(/Parallel mode is experimental/)).not.toBeInTheDocument();
  });

  it("should save max_parallel_agents in config", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const input = screen.getByLabelText("Max Parallel Agents");
    await user.tripleClick(input);
    await user.type(input, "4");

    await user.click(screen.getByText("💾 Save"));

    await waitFor(() => {
      expect(mockSaveConfig).toHaveBeenCalledTimes(1);
    });

    const savedConfig = mockSaveConfig.mock.calls[0][0];
    expect(savedConfig.max_parallel_agents).toBeGreaterThanOrEqual(1);
    expect(savedConfig.max_parallel_agents).toBeLessThanOrEqual(8);
  });

  it("should display unsaved changes red banner", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    // Initially banner should not be present
    await waitFor(() => {
      expect(document.querySelector(".settings-unsaved-banner")).not.toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Enable A/B testing mode"));

    // Banner should appear after change
    await waitFor(() => {
      const banner = document.querySelector(".settings-unsaved-banner");
      expect(banner).toBeTruthy();
      expect(banner?.textContent).toContain("unsaved changes");
    });
  });

  it("should hide banner after save", async () => {
    const user = userEvent.setup();
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Enable A/B testing mode"));

    // Banner should appear
    let banner = document.querySelector(".settings-unsaved-banner");
    expect(banner).toBeInTheDocument();

    await user.click(screen.getByText("💾 Save"));

    await waitFor(() => {
      banner = document.querySelector(".settings-unsaved-banner");
      expect(banner).not.toBeInTheDocument();
    });
  });

  it("should show confirmation dialog when closing with unsaved changes", async () => {
    const user = userEvent.setup();
    window.confirm = vi.fn().mockReturnValue(false);

    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Enable A/B testing mode"));

    const closeButton = screen.getByText("⚙️ Settings").parentElement?.querySelector(".prompt-close-btn");
    await user.click(closeButton!);

    expect(window.confirm).toHaveBeenCalledWith("Close without saving?");
    expect(mockOnClose).not.toHaveBeenCalled();
  });

  it("should close when confirming unsaved changes", async () => {
    const user = userEvent.setup();
    window.confirm = vi.fn().mockReturnValue(true);

    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    await user.click(screen.getByLabelText("Enable A/B testing mode"));

    const closeButton = screen.getByText("⚙️ Settings").parentElement?.querySelector(".prompt-close-btn");
    await user.click(closeButton!);

    expect(window.confirm).toHaveBeenCalledWith("Close without saving?");
    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it("should close without dialog when no unsaved changes", async () => {
    const user = userEvent.setup();
    window.confirm = vi.fn();

    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const closeButton = screen.getByText("⚙️ Settings").parentElement?.querySelector(".prompt-close-btn");
    await user.click(closeButton!);

    expect(window.confirm).not.toHaveBeenCalled();
    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it("should display special-effect tags section", async () => {
    render(<SettingsPage getConfig={mockGetConfig} saveConfig={mockSaveConfig} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    expect(screen.getByText("🏷️ Special-Effect Tags")).toBeInTheDocument();
    expect(screen.getByText("Human required")).toBeInTheDocument();
    expect(screen.getByText("High conflict risk")).toBeInTheDocument();
    expect(screen.getByText("Skip this item until a human can handle it.")).toBeInTheDocument();
    expect(screen.getByText("Runs serially to avoid merge conflicts.")).toBeInTheDocument();
  });

  it("should call onOpenPromptEditor when prompt file link clicked", async () => {
    const user = userEvent.setup();
    const mockOpenPromptEditor = vi.fn();

    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
        onOpenPromptEditor={mockOpenPromptEditor}
      />,
    );

    await waitFor(() => {
      expect(screen.queryByText("Loading configuration…")).not.toBeInTheDocument();
    });

    const promptFileLink = screen.getByText("📄 janitor.md");
    await user.click(promptFileLink);

    expect(mockOpenPromptEditor).toHaveBeenCalledWith("janitor.md");
  });
});
