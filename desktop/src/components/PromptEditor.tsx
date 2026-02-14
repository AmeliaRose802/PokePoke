/**
 * Prompt editor panel for viewing, editing, and resetting prompt templates.
 *
 * Shows a list of all prompts with override status, a textarea editor with
 * template variable reference, and reset-to-default per prompt.
 */

import { useCallback, useEffect, useState } from "react";
import type { PromptInfo, PromptDetail } from "../types";

interface Props {
  listPrompts: () => Promise<PromptInfo[]>;
  getPrompt: (name: string) => Promise<PromptDetail | null>;
  savePrompt: (name: string, content: string) => Promise<boolean>;
  resetPrompt: (name: string) => Promise<boolean>;
  onClose: () => void;
}

export function PromptEditor({
  listPrompts,
  getPrompt,
  savePrompt,
  resetPrompt,
  onClose,
}: Props) {
  const [prompts, setPrompts] = useState<PromptInfo[]>([]);
  const [selected, setSelected] = useState<PromptDetail | null>(null);
  const [editorContent, setEditorContent] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  // Load prompt list on mount
  useEffect(() => {
    let active = true;
    listPrompts().then((list) => {
      if (active) setPrompts(list);
    });
    return () => { active = false; };
  }, [listPrompts]);

  const reloadList = useCallback(async () => {
    const list = await listPrompts();
    setPrompts(list);
  }, [listPrompts]);

  const selectPrompt = useCallback(
    async (name: string) => {
      const detail = await getPrompt(name);
      if (detail) {
        setSelected(detail);
        setEditorContent(detail.content);
        setDirty(false);
        setMessage("");
      }
    },
    [getPrompt]
  );

  const handleSave = useCallback(async () => {
    if (!selected) return;
    setSaving(true);
    const ok = await savePrompt(selected.name, editorContent);
    setSaving(false);
    if (ok) {
      setDirty(false);
      setMessage("Saved");
      await reloadList();
      const detail = await getPrompt(selected.name);
      if (detail) setSelected(detail);
    } else {
      setMessage("Save failed");
    }
  }, [selected, editorContent, savePrompt, reloadList, getPrompt]);

  const handleReset = useCallback(async () => {
    if (!selected || !selected.has_builtin) return;
    const ok = await resetPrompt(selected.name);
    if (ok) {
      setMessage("Reset to default");
      await reloadList();
      await selectPrompt(selected.name);
    } else {
      setMessage("Reset failed");
    }
  }, [selected, resetPrompt, reloadList, selectPrompt]);

  return (
    <div className="prompt-editor-overlay">
      <div className="prompt-editor">
        {/* Header */}
        <div className="prompt-editor-header">
          <span>📝 Prompt Editor</span>
          <button className="prompt-close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="prompt-editor-body">
          {/* Sidebar: prompt list */}
          <div className="prompt-list">
            <div className="prompt-list-title">Templates</div>
            {prompts.map((p) => (
              <div
                key={p.name}
                className={`prompt-list-item ${
                  selected?.name === p.name ? "selected" : ""
                }`}
                onClick={() => selectPrompt(p.name)}
              >
                <span className="prompt-name">{p.name}</span>
                {p.is_override && (
                  <span className="prompt-badge override">override</span>
                )}
                {!p.has_builtin && (
                  <span className="prompt-badge custom">custom</span>
                )}
              </div>
            ))}
          </div>

          {/* Editor area */}
          <div className="prompt-content">
            {selected ? (
              <>
                {/* Toolbar */}
                <div className="prompt-toolbar">
                  <span className="prompt-toolbar-name">{selected.name}</span>
                  <span className="prompt-toolbar-source">
                    {selected.source === "user" ? "📁 User" : "📦 Built-in"}
                  </span>
                  {message && (
                    <span className="prompt-toolbar-msg">{message}</span>
                  )}
                  <div className="prompt-toolbar-actions">
                    {selected.has_builtin && selected.is_override && (
                      <button
                        className="prompt-btn reset"
                        onClick={handleReset}
                      >
                        ↩ Reset
                      </button>
                    )}
                    <button
                      className="prompt-btn save"
                      onClick={handleSave}
                      disabled={!dirty || saving}
                    >
                      {saving ? "…" : "💾 Save"}
                    </button>
                  </div>
                </div>

                {/* Template variable reference */}
                {selected.template_variables.length > 0 && (
                  <div className="prompt-vars">
                    <span className="prompt-vars-label">Variables:</span>
                    {selected.template_variables.map((v) => (
                      <code key={v} className="prompt-var-tag">
                        {`{{${v}}}`}
                      </code>
                    ))}
                  </div>
                )}

                {/* Editor */}
                <textarea
                  className="prompt-textarea"
                  value={editorContent}
                  onChange={(e) => {
                    setEditorContent(e.target.value);
                    setDirty(true);
                    setMessage("");
                  }}
                  spellCheck={false}
                />
              </>
            ) : (
              <div className="prompt-empty">
                Select a prompt template to edit
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
