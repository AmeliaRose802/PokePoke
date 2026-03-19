# PokePoke Architecture

```mermaid
graph LR
    Beads[("📦 Beads<br/>Issue Queue")]:::ext
    Select["📋 Pick<br/>Task"]:::step
    Branch["🌳 Create<br/>Worktree"]:::step
    Code["🧠 Copilot<br/>Codes"]:::ai
    Gate["🚪 Gate<br/>Validates"]:::gate
    Merge["✅ Merge<br/>& Close"]:::done

    Beads --> Select --> Branch --> Code --> Gate
    Gate -->|"✅ Pass"| Merge
    Gate -->|"❌ Fail"| Code
    Merge -->|"🔁 Next item"| Beads

    classDef ext fill:#FB923C,stroke:#EA580C,stroke-width:2px,color:#fff,font-weight:bold
    classDef step fill:#60A5FA,stroke:#2563EB,stroke-width:2px,color:#fff,font-weight:bold
    classDef ai fill:#A78BFA,stroke:#7C3AED,stroke-width:2px,color:#fff,font-weight:bold
    classDef gate fill:#FBBF24,stroke:#D97706,stroke-width:2px,color:#333,font-weight:bold
    classDef done fill:#34D399,stroke:#059669,stroke-width:2px,color:#fff,font-weight:bold
```

**The core loop:** Pick a task from Beads → isolate in a worktree → Copilot writes the code → Gate agent validates → retry or merge → repeat

---

## Parallel Agents

```mermaid
graph TB
    Beads[("📦 Beads<br/>Issue Queue")]:::ext
    Orch["🎯 Orchestrator"]:::core
    Main[("🌳 Main Branch")]:::done

    Beads -->|"ready items"| Orch

    Orch --> A1 & A2 & A3 & A4

    subgraph L1["Lane 1"]
        A1["🐍 Agent 1<br/>Fix login bug"]:::a1
        W1["🌳 worktree-1"]:::wt
        G1["🚪 Gate 1"]:::gate
        A1 --> W1 --> G1
        G1 -.->|"❌ retry"| A1
    end

    subgraph L2["Lane 2"]
        A2["🐍 Agent 2<br/>Add caching"]:::a2
        W2["🌳 worktree-2"]:::wt
        G2["🚪 Gate 2"]:::gate
        A2 --> W2 --> G2
        G2 -.->|"❌ retry"| A2
    end

    subgraph L3["Lane 3"]
        A3["🐍 Agent 3<br/>Update tests"]:::a3
        W3["🌳 worktree-3"]:::wt
        G3["🚪 Gate 3"]:::gate
        A3 --> W3 --> G3
        G3 -.->|"❌ retry"| A3
    end

    subgraph L4["Lane 4"]
        A4["🐍 Agent 4<br/>Refactor API"]:::a4
        W4["🌳 worktree-4"]:::wt
        G4["🚪 Gate 4"]:::gate
        A4 --> W4 --> G4
        G4 -.->|"❌ retry"| A4
    end

    G1 -->|"✅"| Main
    G2 -->|"✅"| Main
    G3 -->|"✅"| Main
    G4 -->|"✅"| Main

    classDef ext fill:#FB923C,stroke:#EA580C,stroke-width:2px,color:#fff,font-weight:bold
    classDef core fill:#FF6B6B,stroke:#C0392B,stroke-width:2px,color:#fff,font-weight:bold
    classDef a1 fill:#60A5FA,stroke:#2563EB,stroke-width:2px,color:#fff,font-weight:bold
    classDef a2 fill:#A78BFA,stroke:#7C3AED,stroke-width:2px,color:#fff,font-weight:bold
    classDef a3 fill:#F472B6,stroke:#DB2777,stroke-width:2px,color:#fff,font-weight:bold
    classDef a4 fill:#FBBF24,stroke:#D97706,stroke-width:2px,color:#333,font-weight:bold
    classDef wt fill:#6EE7B7,stroke:#059669,stroke-width:2px,color:#333,font-weight:bold
    classDef gate fill:#F87171,stroke:#B91C1C,stroke-width:2px,color:#fff,font-weight:bold
    classDef done fill:#34D399,stroke:#059669,stroke-width:2px,color:#fff,font-weight:bold
```

**Parallel execution:** The orchestrator fans out to N agents, each in its own lane: worktree → gate. Pass (✅) merges to main, fail (❌) retries within the lane.

---

## Gate Agent Detail

```mermaid
graph LR
    Work["🧠 Work Agent<br/>writes code"]:::ai
    Tests["🧪 Run Tests"]:::check
    Lint["📏 Lint &<br/>Type Check"]:::check
    Build["🔨 Build"]:::check
    Gate{"🚪 Gate<br/>Pass?"}:::gate
    Pass["✅ Pass"]:::done
    Feedback["📝 Corrective<br/>Feedback"]:::fail
    Retry["🔁 Retry with<br/>feedback"]:::ai

    Work --> Tests --> Lint --> Build --> Gate
    Gate -->|"all green"| Pass
    Gate -->|"failures"| Feedback --> Retry --> Work

    classDef ai fill:#A78BFA,stroke:#7C3AED,stroke-width:2px,color:#fff,font-weight:bold
    classDef check fill:#60A5FA,stroke:#2563EB,stroke-width:2px,color:#fff,font-weight:bold
    classDef gate fill:#FBBF24,stroke:#D97706,stroke-width:3px,color:#333,font-weight:bold
    classDef done fill:#34D399,stroke:#059669,stroke-width:2px,color:#fff,font-weight:bold
    classDef fail fill:#F87171,stroke:#B91C1C,stroke-width:2px,color:#fff,font-weight:bold
```

**Gate validation:** After the work agent finishes, the gate runs tests, linting, and build checks. If anything fails, it generates corrective feedback and the work agent retries. This loops until all checks pass.