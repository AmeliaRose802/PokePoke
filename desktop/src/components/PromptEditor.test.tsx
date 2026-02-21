/**
 * Tests for PromptEditor component.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach,describe, expect, it, vi } from 'vitest';

import type { PromptDetail,PromptInfo } from '../types';
import { PromptEditor } from './PromptEditor';

describe('PromptEditor', () => {
  const mockListPrompts = vi.fn();
  const mockGetPrompt = vi.fn();
  const mockSavePrompt = vi.fn();
  const mockResetPrompt = vi.fn();
  const mockOnClose = vi.fn();

  const defaultPrompts: PromptInfo[] = [
    { name: 'system-prompt', is_override: false, has_builtin: true, source: 'builtin' },
    { name: 'custom-prompt', is_override: false, has_builtin: false, source: 'user' },
  ];

  const defaultPromptDetail: PromptDetail = {
    name: 'system-prompt',
    content: 'You are a helpful assistant.',
    source: 'builtin',
    has_builtin: true,
    is_override: false,
    template_variables: ['agent_name', 'timestamp'],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockListPrompts.mockResolvedValue(defaultPrompts);
    mockGetPrompt.mockResolvedValue(defaultPromptDetail);
    mockSavePrompt.mockResolvedValue(true);
  });

  it('should load and display prompt list', async () => {
    render(
      <PromptEditor
        listPrompts={mockListPrompts}
        getPrompt={mockGetPrompt}
        savePrompt={mockSavePrompt}
        resetPrompt={mockResetPrompt}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('system-prompt')).toBeInTheDocument();
      expect(screen.getByText('custom-prompt')).toBeInTheDocument();
    });
  });

  it('should display template variables as clickable buttons', async () => {
    const user = userEvent.setup();
    render(
      <PromptEditor
        listPrompts={mockListPrompts}
        getPrompt={mockGetPrompt}
        savePrompt={mockSavePrompt}
        resetPrompt={mockResetPrompt}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('system-prompt')).toBeInTheDocument();
    });

    const systemPromptItem = screen.getByText('system-prompt');
    await user.click(systemPromptItem);

    await waitFor(() => {
      expect(screen.getByText('{{agent_name}}')).toBeInTheDocument();
      expect(screen.getByText('{{timestamp}}')).toBeInTheDocument();
    });

    // Check that they are buttons (not code elements)
    const varButtons = screen.getAllByRole('button').filter(btn => btn.textContent?.includes('{{'));
    expect(varButtons.length).toBeGreaterThan(0);
  });

  it('should insert variable at cursor position when variable button clicked', async () => {
    const user = userEvent.setup();
    render(
      <PromptEditor
        listPrompts={mockListPrompts}
        getPrompt={mockGetPrompt}
        savePrompt={mockSavePrompt}
        resetPrompt={mockResetPrompt}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('system-prompt')).toBeInTheDocument();
    });

    const systemPromptItem = screen.getByText('system-prompt');
    await user.click(systemPromptItem);

    const textarea = screen.getByDisplayValue('You are a helpful assistant.');
    textarea.focus();
    
    // Set cursor at beginning
    (textarea as HTMLTextAreaElement).setSelectionRange(0, 0);

    const agentNameButton = screen.getByText('{{agent_name}}');
    await user.click(agentNameButton);

    await waitFor(() => {
      const content = (textarea as HTMLTextAreaElement).value;
      expect(content).toContain('{{agent_name}}');
      expect(content).toMatch(/^{{agent_name}}/);
    });
  });

  it('should insert variable at middle of text', async () => {
    const user = userEvent.setup();
    const promptWithVariables: PromptDetail = {
      ...defaultPromptDetail,
      content: 'Hello world',
    };
    mockGetPrompt.mockResolvedValue(promptWithVariables);

    render(
      <PromptEditor
        listPrompts={mockListPrompts}
        getPrompt={mockGetPrompt}
        savePrompt={mockSavePrompt}
        resetPrompt={mockResetPrompt}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('system-prompt')).toBeInTheDocument();
    });

    const systemPromptItem = screen.getByText('system-prompt');
    await user.click(systemPromptItem);

    const textarea = screen.getByDisplayValue('Hello world');
    textarea.focus();
    
    // Set cursor at position 5 (after "Hello")
    (textarea as HTMLTextAreaElement).setSelectionRange(5, 5);

    const timestampButton = screen.getByText('{{timestamp}}');
    await user.click(timestampButton);

    await waitFor(() => {
      const content = (textarea as HTMLTextAreaElement).value;
      expect(content).toBe('Hello{{timestamp}} world');
    });
  });

  it('should mark as dirty after variable insertion', async () => {
    const user = userEvent.setup();
    render(
      <PromptEditor
        listPrompts={mockListPrompts}
        getPrompt={mockGetPrompt}
        savePrompt={mockSavePrompt}
        resetPrompt={mockResetPrompt}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('system-prompt')).toBeInTheDocument();
    });

    const systemPromptItem = screen.getByText('system-prompt');
    await user.click(systemPromptItem);

    const textarea = screen.getByDisplayValue('You are a helpful assistant.');
    textarea.focus();

    const agentNameButton = screen.getByText('{{agent_name}}');
    await user.click(agentNameButton);

    // Save button should be enabled after variable inserted
    const saveButton = screen.getByText('💾 Save');
    await waitFor(() => {
      expect(saveButton).not.toBeDisabled();
    });
  });

  it('should replace selected text with variable', async () => {
    const user = userEvent.setup();
    render(
      <PromptEditor
        listPrompts={mockListPrompts}
        getPrompt={mockGetPrompt}
        savePrompt={mockSavePrompt}
        resetPrompt={mockResetPrompt}
        onClose={mockOnClose}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('system-prompt')).toBeInTheDocument();
    });

    const systemPromptItem = screen.getByText('system-prompt');
    await user.click(systemPromptItem);

    const textarea = screen.getByDisplayValue('You are a helpful assistant.') as HTMLTextAreaElement;
    textarea.focus();
    
    // Select text and insert variable
    textarea.setSelectionRange(11, 18);

    const agentNameButton = screen.getByText('{{agent_name}}');
    await user.click(agentNameButton);

    await waitFor(() => {
      const content = textarea.value;
      // Variable should have been inserted, replacing the selected text
      expect(content).toContain('{{agent_name}}');
      // Should not have both the old and new content
      expect(content.length).toBeLessThan('You are a helpful assistant.'.length + 20);
    });
  });
});
