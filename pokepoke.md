# PokePoke Architecture

## Presentation Diagram

```mermaid
graph TB
    CLI["🚀 CLI Entry Point"]:::entry

    subgraph Desktop["Desktop App"]
        direction LR
        PyWebView["Python Backend<br/>(pywebview)"]:::ui
        React["React Frontend<br/>Agent Cards · Logs · Stats"]:::ui
        PyWebView <-->|"Bridge API"| React
    end

    Orch["🎯 Orchestrator<br/>Main Loop"]:::core

    subgraph WorkPipeline["Work Item Pipeline"]
        direction LR
        Select["📋 Select<br/>Work Item"]:::step
        Assign["🔖 Assign<br/>& Branch"]:::step
        Invoke["🧠 Invoke<br/>Copilot"]:::step
        Validate["🚪 Gate<br/>Agent"]:::step
        Merge["✅ Merge<br/>& Close"]:::step
        Select --> Assign --> Invoke --> Validate --> Merge
        Validate -->|"❌ Retry"| Invoke
    end

    subgraph Agents["Agent Types"]
        direction LR
        Work["📋 Work"]:::agent
        Gate["🚪 Gate"]:::agent
        Cleanup["🧹 Cleanup"]:::agent
        Maint["🔧 Maintenance"]:::agent
    end

    subgraph External["External Systems"]
        direction LR
        BeadsDB[("📦 Beads DB<br/>Issue Tracker")]:::ext
        Git[("🌳 Git Repo<br/>+ Worktrees")]:::ext
        Copilot["☁️ GitHub<br/>Copilot SDK"]:::ext
    end

    CLI --> Desktop
    CLI --> Orch
    Orch --> WorkPipeline
    Orch -->|"periodic"| Maint
    Work & Gate & Cleanup -.-> Copilot
    Select -.-> BeadsDB
    Assign -.-> BeadsDB
    Assign -.-> Git
    Merge -.-> Git
    Merge -.-> BeadsDB
    Orch -.->|"status"| Desktop

    classDef entry fill:#FFD700,stroke:#B8860B,stroke-width:2px,color:#333,font-weight:bold
    classDef core fill:#FF6B6B,stroke:#C0392B,stroke-width:2px,color:#fff,font-weight:bold
    classDef ui fill:#A78BFA,stroke:#7C3AED,stroke-width:2px,color:#fff
    classDef step fill:#60A5FA,stroke:#2563EB,stroke-width:2px,color:#fff
    classDef agent fill:#34D399,stroke:#059669,stroke-width:2px,color:#fff
    classDef ext fill:#FB923C,stroke:#EA580C,stroke-width:2px,color:#fff
```

**Color Legend:** 🟡 Entry · 🔴 Orchestrator · 🟣 Desktop UI · 🔵 Pipeline Steps · 🟢 Agents · 🟠 External Systems

**Pipeline flow:** Select → Assign → Invoke Copilot → Gate validation → Merge (retry loop on failure)