---
description: Pre-commit quality gates and validation engine enforcing tests, coverage, linting, and build checks before work completion.
references:
  - .githooks/check-build.ps1
  - .githooks/check-code-quality.ps1
  - .githooks/check-compile-warnings.ps1
  - .githooks/check-coverage.py
  - .githooks/check-file-length.ps1
  - .githooks/pre-commit.ps1
  - .githooks/verify-integrity.ps1
confidence: medium
lastUpdated: 2026-03-31
---

# Spec: Validation Gates

## Purpose
- Enforce code quality standards through automated pre-commit hooks.
- Prevent bypass of quality gates via multi-layered defense-in-depth protection.
- In scope: coverage enforcement, linting, build verification, integrity checks.
- Out of scope: test implementation, CI/CD pipeline configuration.

## Component Interaction
- `pre-commit.ps1`: Main hook orchestrating all quality checks with integrity verification.
- `verify-integrity.ps1`: Detects tampering attempts on quality gate scripts.
- `check-coverage.py`: Enforces 80% minimum code coverage on modified files.
- `check-code-quality.ps1`: Runs linting and static analysis checks.
- `check-compile-warnings.ps1`: Enforces zero-warning policy.
- `check-build.ps1`: Verifies project builds successfully.
- `check-file-length.ps1`: Enforces file length limits.

## Design Decisions
- Quality gates protected by CODEOWNERS requiring admin approval for modifications.
- Integrity check runs FIRST to detect any tampering before other checks.
- No bypass mechanisms allowed (no skip parameters, no environment variable overrides).
- Coverage threshold fixed at 80%; lowering is explicitly forbidden.
- All checks must pass; partial success is still failure.
