#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Ensures the pokepoke package can be imported from outside the repository root.

.DESCRIPTION
    Simulates invoking Python from a temporary directory to verify that:
      1. The pokepoke module can be imported without relying on the current working directory
      2. The resolved module path points to the main repository rather than a git worktree

    If the import fails or resolves to the wrong location, the script exits with a non-zero code.

.EXAMPLE
    .\.githooks\check-pokepoke-import.ps1
#>

param()

$ErrorActionPreference = "Stop"

function Normalize-Path {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    try {
        $fullPath = [System.IO.Path]::GetFullPath($Path)
    }
    catch {
        throw "Unable to normalize path '$Path': $_"
    }

    return $fullPath.TrimEnd('\', '/')
}

function Get-MainRepoRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRootPath
    )

    $repoItem = Get-Item -LiteralPath $RepoRootPath
    $parent = $repoItem.Parent

    if ($parent -and $parent.Name.Equals("worktrees", [System.StringComparison]::OrdinalIgnoreCase)) {
        if ($parent.Parent) {
            return $parent.Parent.FullName
        }
    }

    return $repoItem.FullName
}

function Remove-TempDirectory {
    param([string]$Path)
    if (-not $Path) { return }
    try {
        Remove-Item -Path $Path -Recurse -Force -ErrorAction SilentlyContinue
    }
    catch {
        # Non-fatal cleanup failure
    }
}

$repoRoot = git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    $repoRoot = (Get-Location).Path
}

$repoRoot = Normalize-Path $repoRoot
$mainRepoRoot = Normalize-Path (Get-MainRepoRoot $repoRoot)
$isWorktree = $repoRoot -ne $mainRepoRoot

$comparison = if ($IsWindows) {
    [System.StringComparison]::OrdinalIgnoreCase
}
else {
    [System.StringComparison]::Ordinal
}

Write-Host "🏁 Running pokepoke boot check (import from external directory)..." -ForegroundColor Cyan

$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("pokepoke-import-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDir | Out-Null

$pythonScript = @'
import importlib
import json
import pathlib
import sys

result = {}

try:
    module = importlib.import_module("pokepoke")
except Exception as exc:
    result["ok"] = False
    result["error"] = f"{exc.__class__.__name__}: {exc}"
else:
    module_path = pathlib.Path(module.__file__).resolve()
    result["ok"] = True
    result["module_file"] = str(module_path)
    parents = module_path.parents
    if len(parents) >= 3:
        result["project_root"] = str(parents[2])
    else:
        result["project_root"] = str(parents[len(parents) - 1])

json.dump(result, sys.stdout)
'@

$pythonOutput = $null
$pythonExitCode = 0
$pythonError = $null

Push-Location $tempDir
try {
    $pythonOutput = & python -c $pythonScript
    $pythonExitCode = $LASTEXITCODE
}
catch {
    $pythonError = $_
}
finally {
    Pop-Location
    Remove-TempDirectory -Path $tempDir
}

if ($pythonError) {
    Write-Host "❌ Failed to execute python while checking pokepoke import." -ForegroundColor Red
    Write-Host "   $pythonError" -ForegroundColor Yellow
    exit 1
}

if ($pythonExitCode -ne 0) {
    Write-Host "❌ Python exited with code $pythonExitCode while running boot check." -ForegroundColor Red
    if ($pythonOutput) {
        Write-Host $pythonOutput
    }
    Write-Host "Ensure Python is installed and accessible." -ForegroundColor Yellow
    exit 1
}

try {
    $result = $pythonOutput | ConvertFrom-Json
}
catch {
    Write-Host "❌ Unexpected python output while parsing pokepoke import result." -ForegroundColor Red
    if ($pythonOutput) {
        Write-Host $pythonOutput
    }
    exit 1
}

if (-not $result.ok) {
    Write-Host "❌ Unable to import pokepoke from a temporary directory." -ForegroundColor Red
    Write-Host "   $($result.error)" -ForegroundColor Yellow
    Write-Host "Fix: reinstall pokepoke using 'pip install -e $mainRepoRoot' (from the main repo)." -ForegroundColor Yellow
    exit 1
}

if (-not $result.module_file -or -not $result.project_root) {
    Write-Host "❌ Python result missing expected metadata (module_file/project_root)." -ForegroundColor Red
    Write-Host "   $pythonOutput" -ForegroundColor Yellow
    exit 1
}

$moduleFile = Normalize-Path $result.module_file
$moduleProjectRoot = Normalize-Path $result.project_root

# In a worktree, the shared venv's editable install can only point to one location
# at a time — skip the location check and just verify importability.
if ($isWorktree) {
    Write-Host "✅ pokepoke import succeeded in worktree (module: $moduleFile)" -ForegroundColor Green
    exit 0
}

if (-not $moduleFile.StartsWith($mainRepoRoot, $comparison)) {
    Write-Host "❌ pokepoke import resolved to $moduleFile" -ForegroundColor Red
    Write-Host "   Expected module under main repo: $mainRepoRoot" -ForegroundColor Yellow
    Write-Host "Fix: run 'pip install -e $mainRepoRoot' so the editable install points to the main repository." -ForegroundColor Yellow
    exit 1
}

if (-not $moduleProjectRoot.StartsWith($mainRepoRoot, $comparison)) {
    Write-Host "❌ pokepoke project root resolved to $moduleProjectRoot" -ForegroundColor Red
    Write-Host "   Expected root under $mainRepoRoot" -ForegroundColor Yellow
    Write-Host "Fix: reinstall pokepoke from the canonical repository root." -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ pokepoke import succeeded from external directory (module: $moduleFile)" -ForegroundColor Green
exit 0
