/**
 * Tests for SettingsPage component.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsPage } from './SettingsPage';
import type { ConfigResponse, ProjectConfig } from '../types';

describe('SettingsPage', () => {
  const mockGetConfig = vi.fn();
  const mockSaveConfig = vi.fn();
  const mockOnClose = vi.fn();

  const defaultConfig: ProjectConfig = {
    project_name: 'TestProject',
    models: {
      default: 'claude-sonnet-4.5',
      fallback: 'claude-sonnet-4',
      candidate_models: ['gpt-5', 'gpt-5-codex'],
    },
    maintenance: {
      agents: [
        {
          name: 'Janitor',
          enabled: true,
          frequency: 5,
          prompt_file: 'janitor.md',
          needs_worktree: false,
          merge_changes: false,
        },
      ],
    },
  };

  const defaultConfigResponse: ConfigResponse = {
    path: '/test/.pokepoke/config.yaml',
    config: defaultConfig,
    exists: true,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetConfig.mockResolvedValue(defaultConfigResponse);
    mockSaveConfig.mockResolvedValue(true);
  });

  it('should display loading state initially', () => {
    mockGetConfig.mockImplementation(() => new Promise(() => {})); // never resolves
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    expect(screen.getByText('Loading configuration…')).toBeInTheDocument();
  });

  it('should load and display configuration', async () => {
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    expect(mockGetConfig).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('Default Model')).toHaveValue('claude-sonnet-4.5');
    expect(screen.getByLabelText('Fallback Model')).toHaveValue('claude-sonnet-4');
  });

  it('should display error when config fails to load', async () => {
    mockGetConfig.mockResolvedValue(null);

    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Could not load configuration.')).toBeInTheDocument();
    });
  });

  it('should call onClose when close button clicked', async () => {
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const closeButton = screen.getByText('⚙ Settings').parentElement?.querySelector('.prompt-close-btn');
    expect(closeButton).toBeInTheDocument();
    await userEvent.click(closeButton!);

    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it('should mark dirty when default model changed', async () => {
    const user = userEvent.setup();
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const input = screen.getByLabelText('Default Model');
    await user.clear(input);
    await user.type(input, 'gpt-5.2');

    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
  });

  it('should mark dirty when fallback model changed', async () => {
    const user = userEvent.setup();
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const input = screen.getByLabelText('Fallback Model');
    await user.clear(input);
    await user.type(input, 'gpt-5.1');

    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
  });

  it('should add candidate model chip on Enter', async () => {
    const user = userEvent.setup();
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const chipInput = screen.getByPlaceholderText('Add model…');
    await user.type(chipInput, 'claude-opus-4.5{Enter}');

    expect(screen.getByText('claude-opus-4.5')).toBeInTheDocument();
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
  });

  it('should remove candidate model chip when x clicked', async () => {
    const user = userEvent.setup();
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const gpt5Chip = screen.getByText('gpt-5').closest('.chip');
    expect(gpt5Chip).toBeInTheDocument();

    const removeButton = gpt5Chip!.querySelector('.chip-remove');
    await user.click(removeButton!);

    expect(screen.queryByText('gpt-5')).not.toBeInTheDocument();
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
  });

  it('should not add duplicate candidate models', async () => {
    const user = userEvent.setup();
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const chipInput = screen.getByPlaceholderText('Add model…');
    await user.type(chipInput, 'gpt-5{Enter}');

    // Should still only have one gpt-5 chip
    const chips = screen.getAllByText('gpt-5');
    expect(chips.length).toBe(1);
  });

  it('should display maintenance agents', async () => {
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    expect(screen.getByText('Janitor')).toBeInTheDocument();
    expect(screen.getByText('📄 janitor.md')).toBeInTheDocument();
  });

  it('should toggle maintenance agent enabled state', async () => {
    const user = userEvent.setup();
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const toggle = screen.getByRole('checkbox');
    expect(toggle).toBeChecked();

    await user.click(toggle);

    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
  });

  it('should update maintenance agent frequency', async () => {
    const user = userEvent.setup();
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const frequencyInput = screen.getByDisplayValue('5');
    await user.clear(frequencyInput);
    await user.type(frequencyInput, '10');

    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
  });

  it('should save configuration successfully', async () => {
    const user = userEvent.setup();
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const input = screen.getByLabelText('Default Model');
    await user.clear(input);
    await user.type(input, 'gpt-5.2');

    const saveButton = screen.getByText('💾 Save');
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockSaveConfig).toHaveBeenCalledTimes(1);
    });

    const savedConfig = mockSaveConfig.mock.calls[0][0];
    expect(savedConfig.models.default).toBe('gpt-5.2');

    expect(screen.getByText('Saved')).toBeInTheDocument();
    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
  });

  it('should display error message on save failure', async () => {
    const user = userEvent.setup();
    mockSaveConfig.mockResolvedValue(false);

    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const input = screen.getByLabelText('Default Model');
    await user.type(input, 'x');

    const saveButton = screen.getByText('💾 Save');
    await user.click(saveButton);

    await waitFor(() => {
      expect(screen.getByText('Save failed')).toBeInTheDocument();
    });
  });

  it('should reset changes when reset clicked', async () => {
    const user = userEvent.setup();
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const input = screen.getByLabelText('Default Model');
    await user.clear(input);
    await user.type(input, 'changed-model');

    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();

    const resetButton = screen.getByText('↩ Reset');
    await user.click(resetButton);

    expect(screen.getByText('Reset to saved values')).toBeInTheDocument();
    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Default Model')).toHaveValue('claude-sonnet-4.5');
  });

  it('should disable save button when not dirty', async () => {
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const saveButton = screen.getByText('💾 Save');
    expect(saveButton).toBeDisabled();
  });

  it('should disable reset button when not dirty', async () => {
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const resetButton = screen.getByText('↩ Reset');
    expect(resetButton).toBeDisabled();
  });

  it('should show loading state on save button during save', async () => {
    const user = userEvent.setup();
    mockSaveConfig.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve(true), 100)));

    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const input = screen.getByLabelText('Default Model');
    await user.type(input, 'x');

    const saveButton = screen.getByText('💾 Save');
    await user.click(saveButton);

    expect(screen.getByText('…')).toBeInTheDocument();
  });

  it('should handle empty maintenance agents array', async () => {
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

    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    expect(screen.getByText('No maintenance agents configured')).toBeInTheDocument();
  });

  it('should add chip on blur if input has value', async () => {
    const user = userEvent.setup();
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const chipInput = screen.getByPlaceholderText('Add model…');
    await user.type(chipInput, 'new-model');
    await user.tab(); // triggers blur

    expect(screen.getByText('new-model')).toBeInTheDocument();
  });

  it('should remove last chip on backspace with empty input', async () => {
    const user = userEvent.setup();
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const chipInput = screen.getByPlaceholderText('Add model…');
    
    // Should have gpt-5-codex as last chip
    expect(screen.getByText('gpt-5-codex')).toBeInTheDocument();
    
    await user.click(chipInput);
    await user.keyboard('{Backspace}');

    expect(screen.queryByText('gpt-5-codex')).not.toBeInTheDocument();
  });

  it('should include all configuration sections in save', async () => {
    const user = userEvent.setup();
    render(
      <SettingsPage
        getConfig={mockGetConfig}
        saveConfig={mockSaveConfig}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading configuration…')).not.toBeInTheDocument();
    });

    const input = screen.getByLabelText('Default Model');
    await user.type(input, 'x');

    const saveButton = screen.getByText('💾 Save');
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockSaveConfig).toHaveBeenCalledTimes(1);
    });

    const savedConfig = mockSaveConfig.mock.calls[0][0];
    expect(savedConfig.project_name).toBe('TestProject');
    expect(savedConfig.models).toBeDefined();
    expect(savedConfig.maintenance).toBeDefined();
  });
});
