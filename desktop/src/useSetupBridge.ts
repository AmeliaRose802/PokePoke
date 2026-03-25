/**
 * Setup wizard bridge hooks for the PokePoke desktop app.
 *
 * Extracted from useBridge.ts to keep file length under the limit.
 */

import { useCallback } from "react";

import { SetupStatusSchema, validatePayload } from "./schemas";
import type { SetupConfigPayload, SetupStatus } from "./types";

export interface SetupBridgeMethods {
  checkSetupStatus: () => Promise<SetupStatus>;
  gitInit: (defaultBranch?: string) => Promise<{
    success: boolean;
    error?: string;
    stdout?: string | null;
    stderr?: string | null;
  } | null>;
  bdInit: () => Promise<{ success: boolean } | null>;
  createDefaultConfig: (config: SetupConfigPayload) => Promise<{ path: string; saved: boolean } | null>;
  scaffoldPromptOverrides: (
    templates?: string[],
    force?: boolean,
  ) => Promise<{ success: boolean; written: string[] } | null>;
  completeSetup: () => Promise<{ success: boolean; error?: string } | null>;
}

export function useSetupBridge(): SetupBridgeMethods {
  const checkSetupStatus = useCallback(async (): Promise<SetupStatus> => {
    if (!window.pywebview?.api) {
      throw new Error("pywebview API not available");
    }
    const raw = await window.pywebview.api.check_setup_status();
    return validatePayload(SetupStatusSchema, raw, "checkSetupStatus");
  }, []);

  const gitInit = useCallback(async (defaultBranch?: string) => {
    if (!window.pywebview?.api) return null;
    return window.pywebview.api.git_init(defaultBranch);
  }, []);

  const bdInit = useCallback(async () => {
    if (!window.pywebview?.api) return null;
    return window.pywebview.api.bd_init();
  }, []);

  const createDefaultConfig = useCallback(async (config: SetupConfigPayload) => {
    if (!window.pywebview?.api) return null;
    return window.pywebview.api.create_default_config(config);
  }, []);

  const scaffoldPromptOverrides = useCallback(async (templates?: string[], force?: boolean) => {
    if (!window.pywebview?.api) return null;
    return window.pywebview.api.scaffold_prompt_overrides(templates, force);
  }, []);

  const completeSetup = useCallback(async () => {
    if (!window.pywebview?.api) return null;
    return window.pywebview.api.complete_setup();
  }, []);

  return {
    checkSetupStatus,
    gitInit,
    bdInit,
    createDefaultConfig,
    scaffoldPromptOverrides,
    completeSetup,
  };
}
