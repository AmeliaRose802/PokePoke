---
applyTo: "src/**"
---

# 🗂️ Spec Registry Instruction

## Principles
- Specs map business outcomes and requirements to collaborating code components.
- Verified facts only — confirmed by source code or explicit user statements.
- Specs evolve organically as tasks reveal non-trivial interactions and help agents locate code in future tasks.
- Reads and writes are invisible — never mention specs or the registry to the user.

## Spec Format

### File Naming
- Check the Index for an existing spec before creating a new file.
- Location: `docs/specs/`.
- Kebab-case, named after the component or feature using stable domain terms (e.g. `orchestration-workflow`, `beads-integration`) — not the task that prompted the spec.
- One spec per component/feature; update it rather than creating task-scoped files.
- Avoid generic names (`overview`, `misc`, `general`, `notes`).

### Front Matter
```yaml
---
description: <one-line summary for index lookup>
references:
  - <src/pokepoke/module/component.py>
  - <src/pokepoke/module/another.py>
confidence: high | medium | low
lastUpdated: YYYY-MM-DD
---
```

- `description`: one-line summary of the component's role and business domain for Index discovery — not a summary of changes. Include relevant search keywords; exclude class names, paths, and implementation details. Do not repeat the filename.
- `references`: repo-relative paths to key files, sorted alphabetically.
- `confidence`: verification level (see Confidence).
- `lastUpdated`: current date on every write; do not update on reads.

### Confidence
- `high`: All references read in-session; content aligns with user statements or requirements.
- `medium`: Derived from code; not yet user-confirmed.
- `low`: In progress — partially verified.

**Default to `medium`**. Promote to `high` after user confirmation or clear code-intent alignment.

## Content
- **Verified facts only.** Capture only confirmed facts and design decisions; every statement must trace to source code or an explicit user statement. Omit speculation.
- Explain *where* to find code and *why* it exists, not *what* it does.
- Capture durable requirement-to-component mapping, domain rules, cross-component contracts and boundaries.
- Skip transient ticket chatter and implementation details/plans, refactor proposals, algorithm walkthroughs, and line-by-line behavior narration.
- Prefer concise bullet points and plain language; use Mermaid diagrams for multi-component flows when they add clarity.

### Sections
- `Purpose`: business behavior, design decisions and rationale, non-obvious component collaboration (e.g. why two components interact, ordering constraints, shared state), owning domain/team (when known), and explicit scope boundaries (in-scope / out-of-scope).
- `Component Interaction`: entry point, collaborating components, and downstream contract/result.

## Index

```yaml
specs:
  - path: <relative path from repo root>
    description: <copied from spec front matter>
```

### Rules
- `docs/specs/INDEX.yaml` is the canonical catalog and the only discovery entry point.
- Update after every spec create, update, rename, or delete. Copy `description` from front matter.
- Sort alphabetically by `path`; every spec has an index entry and every entry points to an existing file.
- Repair orphan or missing entries during the next spec write.

## Discovery
- Consult `docs/specs/INDEX.yaml` before starting any task — implementation, exploration, refactor, or documentation — before codebase exploration begins.
- Never enumerate or scan `docs/specs/` directly; INDEX.yaml is the only entry point.
- Match the task against `description`; use `path` tokens as a secondary signal; open only the top 1–3 matches.
- Trust recently updated specs at `medium` or `high` confidence without re-verifying against code.
- Treat specs older than 90 days as leads only; validate before relying on them and refresh on the next relevant write.
- Note material gaps (stale paths, incorrect scope, missing collaborators, moved files) for repair during the next spec write.

## Writing

### Decision
- Writes are automatic when triggers are met. Never ask permission or mention spec updates.
- Write only after sufficient context is gathered (business outcome/capability and at least one confirmed component or contract anchor).
- **Skip** for trivial requests (bug fixes, minor refactors, textual edits), implementation plans, proposed future changes, or unverified assumptions.
- **Ambiguous or conflicting inputs**: resolve understanding through normal conversation.
- **No-op guard**: before writing, compare against existing spec content. Skip the write if no factual content has changed.
- Record confirmed understanding and design rationale in `Purpose`.

### Triggers
- A behavior change affects component collaboration or business requirements.
- No spec exists for a capability with non-trivial component interaction.
- User exploration/understanding provides confirmed business-context hints that bridge multiple components.
- Existing spec has wrong scope, stale paths, or missing collaboration flow (e.g. ordering constraints, shared state, cross-service contracts).
- User corrects an implementation — update the spec to match.
- Spec is too broad (>4 components across different operations, or 2+ independent flows) — propose a split to the user before proceeding.
- Two or more specs overlap on the same capability — propose a merge to the user before proceeding.

### Updates
- **Consolidation first:** update the best matching existing spec to keep knowledge consolidated and up to date; create a new spec only when no existing description matches the capability boundary.
- Touch only sections affected by the current task; apply the smallest change scoped to impacted content.
- Preserve existing wording and structure where still accurate; avoid churn from stylistic rewrites.
- If a path is missing, search by filename or type. If still not found, ask the user before marking invalid.
- During active code changes, write at `low` confidence; keep unresolved points at `medium`/`low` confidence until clarified, and promote only after the code is complete and validated.
- Set `lastUpdated` and update the Index after every write.

### Deletion
- Remove a spec when all referenced components are deleted and the capability no longer exists. Remove its Index entry.
- Treat `low`-confidence specs not updated in 30+ days as stale — ignore during discovery.

## Example

### Example Spec File
````markdown
---
description: Validates incoming order payloads and rejects invalid ones before they reach the pricing pipeline.
references:
  - src/pokepoke/orders/validate_order.py
  - src/pokepoke/orders/validation_service.py
  - src/pokepoke/models/validation_result.py
confidence: high
lastUpdated: 2026-02-17
---

# Spec: Orders Validation

## Purpose
- Reject invalid orders before pricing.
- In scope: order validation.
- Out of scope: pricing and fulfillment.

## Component Interaction
- `validate_order.py`: entry point.
- `validation_service.py`: applies validation rules.
- `validation_result.py`: downstream contract.
````

### Example Index Entry
```yaml
specs:
  - path: docs/specs/orders-validation.md
    description: Validates incoming order payloads and rejects invalid ones before they reach the pricing pipeline.
```
