/**
 * Tests for runtime-validated bridge schemas.
 *
 * These tests verify that:
 * 1. Valid payloads pass validation
 * 2. Invalid payloads fail with actionable error messages
 * 3. Contract mismatches are caught at the boundary
 */

import { describe, expect, it } from "vitest";

import {
  AgentInfoSchema,
  AgentStatsSchema,
  AppStateSchema,
  ConfigResponseSchema,
  LogEntrySchema,
  MaintenanceConfigSchema,
  ModelCompletionRecordSchema,
  ProjectConfigSchema,
  PromptDetailSchema,
  PromptInfoSchema,
  safeValidatePayload,
  SessionStatsSchema,
  SetupStatusSchema,
  validatePayload,
  WorkItemSchema,
} from "./schemas";

describe("LogEntrySchema", () => {
  it("should validate a valid log entry", () => {
    const validLog = {
      message: "Test message",
      target: "orchestrator" as const,
      style: null,
      timestamp: 1234567890,
    };
    expect(() => validatePayload(LogEntrySchema, validLog, "test")).not.toThrow();
  });

  it("should reject invalid target", () => {
    const invalidLog = {
      message: "Test",
      target: "invalid",
      style: null,
      timestamp: 123,
    };
    expect(() => validatePayload(LogEntrySchema, invalidLog, "test")).toThrow(
      /target.*Invalid option/
    );
  });

  it("should reject missing required fields", () => {
    const incomplete = { message: "Test" };
    expect(() => validatePayload(LogEntrySchema, incomplete, "test")).toThrow(/Invalid input/);
  });
});

describe("WorkItemSchema", () => {
  it("should validate a valid work item", () => {
    const validItem = {
      item_id: "test-123",
      title: "Test Item",
      status: "active",
      labels: ["bug", "frontend"],
    };
    expect(() => validatePayload(WorkItemSchema, validItem, "test")).not.toThrow();
  });

  it("should accept work item without optional labels", () => {
    const itemNoLabels = {
      item_id: "test-456",
      title: "Another Item",
      status: "pending",
    };
    expect(() => validatePayload(WorkItemSchema, itemNoLabels, "test")).not.toThrow();
  });

  it("should reject work item with wrong type for item_id", () => {
    const invalidItem = {
      item_id: 123, // Should be string
      title: "Test",
      status: "active",
    };
    expect(() => validatePayload(WorkItemSchema, invalidItem, "test")).toThrow(
      /item_id.*expected string/
    );
  });
});

describe("AgentStatsSchema", () => {
  it("should validate valid agent stats", () => {
    const validStats = {
      wall_duration: 10.5,
      api_duration: 5.2,
      input_tokens: 1000,
      output_tokens: 500,
      lines_added: 50,
      lines_removed: 20,
      premium_requests: 2,
      retries: 1,
      tool_calls: 15,
    };
    expect(() => validatePayload(AgentStatsSchema, validStats, "test")).not.toThrow();
  });

  it("should reject stats with missing fields", () => {
    const incompleteStats = {
      wall_duration: 10.5,
      api_duration: 5.2,
      // Missing required fields
    };
    expect(() => validatePayload(AgentStatsSchema, incompleteStats, "test")).toThrow(/Invalid input/);
  });
});

describe("SessionStatsSchema", () => {
  it("should validate minimal session stats", () => {
    const minimalStats = {
      elapsed_time: 120.5,
    };
    expect(() => validatePayload(SessionStatsSchema, minimalStats, "test")).not.toThrow();
  });

  it("should validate full session stats", () => {
    const fullStats = {
      elapsed_time: 300.0,
      agent_stats: {
        wall_duration: 10.5,
        api_duration: 5.2,
        input_tokens: 1000,
        output_tokens: 500,
        lines_added: 50,
        lines_removed: 20,
        premium_requests: 2,
        retries: 1,
        tool_calls: 15,
      },
      items_completed: 5,
      items_created: 3,
      net_items_delta: 2,
      work_agent_runs: 10,
      model_completions: [
        {
          item_id: "item-1",
          model: "claude-sonnet-4",
          duration_seconds: 60.0,
          gate_passed: true,
          input_tokens: 1000,
          output_tokens: 500,
          agent_turns: 3,
          cost: 0.05,
          retry_attempts: 0,
          api_duration: 30.0,
          lines_added: 50,
          lines_removed: 20,
        },
      ],
    };
    expect(() => validatePayload(SessionStatsSchema, fullStats, "test")).not.toThrow();
  });
});

describe("AgentInfoSchema", () => {
  it("should validate running agent info", () => {
    const validAgent = {
      agent_id: "agent-123",
      name: "Test Agent",
      iteration: 1,
      status: "running" as const,
      recent_logs: ["Log 1", "Log 2"],
    };
    expect(() => validatePayload(AgentInfoSchema, validAgent, "test")).not.toThrow();
  });

  it("should validate agent with all optional fields", () => {
    const fullAgent = {
      agent_id: "agent-456",
      base_agent_id: "base-123",
      card_id: "card-789",
      parent_card_id: null,
      name: "Full Agent",
      iteration: 2,
      status: "success" as const,
      model: "claude-sonnet-4",
      parent_agent_id: "parent-123",
      work_item_id: "item-123",
      work_item_title: "Test Item",
      agent_type: "work",
      modified_files: ["file1.ts", "file2.ts"],
      recent_logs: ["Log entry"],
      log_lines: ["Full log 1", "Full log 2"],
      agent_prompt: "Test prompt",
      started_at: 1234567890,
      last_updated: 1234567900,
      last_log_at: 1234567895,
      paused: false,
      session_id: "session-123",
      input_tokens: 1000,
      output_tokens: 500,
      is_history_entry: false,
    };
    expect(() => validatePayload(AgentInfoSchema, fullAgent, "test")).not.toThrow();
  });

  it("should reject agent with invalid status", () => {
    const invalidAgent = {
      agent_id: "agent-789",
      name: "Test",
      iteration: 1,
      status: "invalid-status",
      recent_logs: [],
    };
    expect(() => validatePayload(AgentInfoSchema, invalidAgent, "test")).toThrow(
      /status.*Invalid option/
    );
  });
});

describe("AppStateSchema", () => {
  it("should validate minimal app state", () => {
    const minimalState = {
      work_item: null,
      agent_name: "",
      repository_name: "test-repo",
      stats: null,
      progress: { active: false, status: "" },
      log_count: 0,
      model_leaderboard: {},
      agents: [],
      stop_after_current: false,
      current_session_id: null,
      logs_dir: null,
    };
    expect(() => validatePayload(AppStateSchema, minimalState, "test")).not.toThrow();
  });

  it("should validate full app state with work item and agents", () => {
    const fullState = {
      work_item: {
        item_id: "item-123",
        title: "Test Item",
        status: "active",
        labels: ["bug"],
      },
      agent_name: "TestAgent",
      repository_name: "test-repo",
      stats: {
        elapsed_time: 120.5,
        items_completed: 5,
      },
      progress: { active: true, status: "Processing item" },
      log_count: 100,
      model_leaderboard: {
        "claude_sonnet_4": {  // Use underscore instead of hyphen for valid record key
          total_items_attempted: 10,
          total_items_succeeded: 8,
          total_items_failed: 2,
          total_duration_seconds: 600.0,
          total_retries: 3,
          average_duration: 60.0,
          success_rate: 0.8,
          last_used: "2024-01-01T12:00:00Z",
        },
      },
      agents: [
        {
          agent_id: "agent-1",
          name: "WorkAgent",
          iteration: 1,
          status: "running" as const,
          recent_logs: ["Processing..."],
        },
      ],
      stop_after_current: false,
      project_name: "TestProject",
      current_session_id: "session-123",
      logs_dir: "/path/to/logs",
      new_logs: [
        {
          message: "New log",
          target: "orchestrator" as const,
          style: null,
          timestamp: 1234567890,
        },
      ],
    };
    expect(() => validatePayload(AppStateSchema, fullState, "test")).not.toThrow();
  });

  it("should reject app state with invalid agent", () => {
    const invalidState = {
      work_item: null,
      agent_name: "",
      repository_name: "test-repo",
      stats: null,
      progress: { active: false, status: "" },
      log_count: 0,
      model_leaderboard: {},
      agents: [
        {
          agent_id: "agent-1",
          // Missing required fields
        },
      ],
      stop_after_current: false,
      current_session_id: null,
      logs_dir: null,
    };
    expect(() => validatePayload(AppStateSchema, invalidState, "test")).toThrow();
  });
});

describe("ConfigResponseSchema", () => {
  it("should validate config response", () => {
    const validConfig = {
      path: "/path/to/config.yaml",
      config: {
        project_name: "TestProject",
        models: {
          default: "claude-sonnet-4",
          fallback: "claude-haiku",
        },
        max_parallel_agents: 3,
      },
      exists: true,
    };
    expect(() => validatePayload(ConfigResponseSchema, validConfig, "test")).not.toThrow();
  });

  it("should accept config with unknown fields (catchall)", () => {
    const configWithExtra = {
      path: "/path/to/config.yaml",
      config: {
        project_name: "TestProject",
        custom_field: "value", // Unknown field should be allowed
        nested: { unknown: "data" },
      },
      exists: true,
    };
    expect(() => validatePayload(ConfigResponseSchema, configWithExtra, "test")).not.toThrow();
  });
});

describe("PromptInfoSchema", () => {
  it("should validate prompt info", () => {
    const validPrompt = {
      name: "test-prompt",
      is_override: true,
      has_builtin: true,
      source: "user" as const,
    };
    expect(() => validatePayload(PromptInfoSchema, validPrompt, "test")).not.toThrow();
  });

  it("should reject invalid source", () => {
    const invalidPrompt = {
      name: "test",
      is_override: false,
      has_builtin: false,
      source: "invalid",
    };
    expect(() => validatePayload(PromptInfoSchema, invalidPrompt, "test")).toThrow(
      /source.*Invalid option/
    );
  });
});

describe("PromptDetailSchema", () => {
  it("should validate prompt detail", () => {
    const validDetail = {
      name: "test-prompt",
      is_override: false,
      has_builtin: true,
      source: "builtin" as const,
      content: "This is the prompt content",
      template_variables: ["var1", "var2"],
    };
    expect(() => validatePayload(PromptDetailSchema, validDetail, "test")).not.toThrow();
  });
});

describe("SetupStatusSchema", () => {
  it("should validate setup status", () => {
    const validStatus = {
      cwd: "/path/to/project",
      project_root: "/path/to/project",
      is_git_repo: true,
      beads_installed: true,
      beads_initialized: true,
      config_exists: true,
      config_path: "/path/to/config.yaml",
      needs_setup: false,
    };
    expect(() => validatePayload(SetupStatusSchema, validStatus, "test")).not.toThrow();
  });
});

describe("Helper functions", () => {
  describe("validatePayload", () => {
    it("should throw with context on validation failure", () => {
      const invalid = { message: "test" };
      expect(() => validatePayload(LogEntrySchema, invalid, "myContext")).toThrow(
        /\[Bridge Contract Error\] myContext failed validation/
      );
    });

    it("should include specific error details", () => {
      const invalid = { message: "test", target: "invalid" };
      expect(() => validatePayload(LogEntrySchema, invalid, "myContext")).toThrow(/target/);
    });
  });

  describe("safeValidatePayload", () => {
    it("should return null on validation failure", () => {
      const invalid = { message: "test" };
      const result = safeValidatePayload(LogEntrySchema, invalid, "test");
      expect(result).toBeNull();
    });

    it("should return validated data on success", () => {
      const valid = {
        message: "test",
        target: "orchestrator" as const,
        style: null,
        timestamp: 123,
      };
      const result = safeValidatePayload(LogEntrySchema, valid, "test");
      expect(result).toEqual(valid);
    });
  });
});

describe("ModelCompletionRecordSchema", () => {
  it("should validate model completion record", () => {
    const valid = {
      item_id: "item-1",
      model: "claude-sonnet-4",
      duration_seconds: 60.0,
      gate_passed: true,
      input_tokens: 1000,
      output_tokens: 500,
      agent_turns: 3,
      cost: 0.05,
      retry_attempts: 0,
      api_duration: 30.0,
      lines_added: 50,
      lines_removed: 20,
    };
    expect(() => validatePayload(ModelCompletionRecordSchema, valid, "test")).not.toThrow();
  });

  it("should accept null for nullable fields", () => {
    const validWithNulls = {
      item_id: "item-1",
      model: "claude-sonnet-4",
      duration_seconds: 60.0,
      gate_passed: null, // Nullable
      input_tokens: 1000,
      output_tokens: 500,
      agent_turns: 3,
      cost: 0.05,
      retry_attempts: 0,
      api_duration: null, // Nullable
      lines_added: null, // Nullable
      lines_removed: null, // Nullable
    };
    expect(() => validatePayload(ModelCompletionRecordSchema, validWithNulls, "test")).not.toThrow();
  });
});

describe("MaintenanceConfigSchema", () => {
  it("should validate maintenance config", () => {
    const valid = {
      agents: [
        {
          name: "test-agent",
          prompt_file: "test.md",
          frequency: 10,
          enabled: true,
          needs_worktree: true,
          merge_changes: true,
          model: "claude-sonnet-4",
          custom: false,
          description: "Test maintenance agent",
        },
      ],
    };
    expect(() => validatePayload(MaintenanceConfigSchema, valid, "test")).not.toThrow();
  });
});

describe("ProjectConfigSchema", () => {
  it("should validate project config with all sections", () => {
    const valid = {
      project_name: "TestProject",
      models: {
        default: "claude-sonnet-4",
        fallback: "claude-haiku",
        ab_testing_enabled: true,
        candidate_models: ["claude-sonnet-4", "gpt-4"],
      },
      git: {
        default_branch: "main",
      },
      mcp_server: {
        enabled: true,
        restart_script: "./restart.sh",
        name: "test-server",
      },
      maintenance: {
        agents: [
          {
            name: "cleanup",
            prompt_file: "cleanup.md",
            frequency: 100,
            enabled: true,
            needs_worktree: false,
          },
        ],
      },
      test_data: {
        key1: "value1",
      },
      max_parallel_agents: 5,
      // Note: catchall allows additional fields but we skip testing that here
      // as the implementation depends on the Python side accepting them
    };
    expect(() => validatePayload(ProjectConfigSchema, valid, "test")).not.toThrow();
  });
});

describe("Edge cases", () => {
  it("should handle deeply nested validation errors", () => {
    const invalidState = {
      work_item: null,
      agent_name: "",
      repository_name: "test",
      stats: {
        elapsed_time: "not a number", // Invalid type deep in stats
      },
      progress: { active: false, status: "" },
      log_count: 0,
      model_leaderboard: {},
      agents: [],
      stop_after_current: false,
      current_session_id: null,
      logs_dir: null,
    };
    expect(() => validatePayload(AppStateSchema, invalidState, "test")).toThrow(
      /stats\.elapsed_time.*expected number/
    );
  });

  it("should handle array validation errors with index", () => {
    const invalidLogs = [
      { message: "valid", target: "orchestrator", style: null, timestamp: 123 },
      { message: "invalid", target: "bad-target", style: null, timestamp: 456 },
    ];
    expect(() => {
      invalidLogs.forEach((log, idx) =>
        validatePayload(LogEntrySchema, log, `logs[${idx}]`)
      );
    }).toThrow(/logs\[1\].*target/);
  });
});
