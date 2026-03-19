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

    subgraph Pool["Thread Pool"]
        direction LR
        A1["🐍 Agent 1<br/>Fix login bug"]:::a1
        A2["🐍 Agent 2<br/>Add caching"]:::a2
        A3["🐍 Agent 3<br/>Update tests"]:::a3
        A4["🐍 Agent 4<br/>Refactor API"]:::a4
    end

    subgraph Gates["Gate Agents"]
        direction LR
        G1["🚪 Gate 1"]:::gate
        G2["🚪 Gate 2"]:::gate
        G3["🚪 Gate 3"]:::gate
        G4["🚪 Gate 4"]:::gate
    end

    subgraph Worktrees["Isolated Worktrees"]
        direction LR
        W1["🌳 worktree-1"]:::wt
        W2["🌳 worktree-2"]:::wt
        W3["🌳 worktree-3"]:::wt
        W4["🌳 worktree-4"]:::wt
    end

    Main[("🌳 Main Branch")]:::done

    Beads -->|"ready items"| Orch
    Orch --> A1 & A2 & A3 & A4
    A1 --> W1
    A2 --> W2
    A3 --> W3
    A4 --> W4
    W1 --> G1
    W2 --> G2
    W3 --> G3
    W4 --> G4
    G1 -->|"❌"| A1
    G2 -->|"❌"| A2
    G3 -->|"❌"| A3
    G4 -->|"❌"| A4
    G1 & G2 & G3 & G4 -->|"✅"| Main

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

**Parallel execution:** The orchestrator fans out to N agents, each in its own worktree. Gate agents validate each agent's work — pass merges to main, fail retries the work agent.