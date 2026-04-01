#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Check test files for unsafe subprocess/git/filesystem operations
    
.DESCRIPTION
    Scans test files for patterns that could cause hangs:
    - Real subprocess calls (subprocess.run, subprocess.Popen) without proper mocks
    - Direct git command execution (subprocess.run(['git', ...]))
    - Filesystem operations (os.system, shutil operations) without mocks
    - Missing @pytest.mark.allow_real_bd or @pytest.mark.allow_git_repair markers
    
    This prevents agents from creating integration tests that hang due to
    unmocked external operations. All tests MUST use mocks unless explicitly
    marked with the appropriate pytest marker.
    
    Exemptions:
    - Tests in tests/fakes.py (test helper factories)
    - Tests marked with @pytest.mark.allow_real_bd
    - Tests marked with @pytest.mark.allow_git_repair
    - Tests in conftest.py (fixture definitions may need real operations)
    
.EXAMPLE
    .\.githooks\check-test-safety.ps1
    Checks all staged test files for unsafe patterns
#>

$ErrorActionPreference = "Stop"

# Source the staged-files utility
. "$PSScriptRoot\staged-files-utils.ps1"

try {
    # Get repository root
    $repoRoot = git rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0) {
        $repoRoot = (Get-Location).Path
    }
    
    # Get all staged files to check for test infrastructure changes
    $allStagedFiles = git diff --cached --name-only --diff-filter=ACM 2>$null
    if ($LASTEXITCODE -ne 0) {
        $allStagedFiles = @()
    } else {
        $allStagedFiles = $allStagedFiles -split "`n" | Where-Object { $_ -ne '' } | ForEach-Object { $_.Trim() }
    }
    
    # Check if test infrastructure files are staged (requires full scan)
    $infrastructureChanged = $false
    foreach ($file in $allStagedFiles) {
        $basename = [System.IO.Path]::GetFileName($file)
        if ($basename -eq "conftest.py" -or $basename -eq "__init__.py") {
            Write-Host "[scope] $basename changed — scanning all test files" -ForegroundColor Yellow
            $infrastructureChanged = $true
            break
        }
    }
    
    # Determine which test files to scan
    $testFiles = @()
    
    if ($infrastructureChanged) {
        # Full scan: Get all test files recursively
        $testFiles += Get-ChildItem -Path "." -Filter "test_*.py" -Recurse -ErrorAction SilentlyContinue
        $testFiles += Get-ChildItem -Path "." -Filter "*_test.py" -Recurse -ErrorAction SilentlyContinue
        $testFiles = $testFiles | Where-Object { $_.FullName -notmatch '\\(venv|.venv|__pycache__|dist|build)\\' }
    } else {
        # Scoped scan: Get only staged test files
        $stagedTestFiles = Get-StagedFiles -Pattern '(test_.*\.py|_test\.py)$' -DenyPatterns @('venv', '.venv', '__pycache__', 'dist', 'build')
        
        if ($stagedTestFiles.Count -eq 0) {
            Write-Host "✅ No test files staged for commit" -ForegroundColor Green
            exit 0
        }
        
        Write-Host "[scope] Scanning $($stagedTestFiles.Count) staged test file(s)" -ForegroundColor Yellow
        
        # Convert relative paths to FileInfo objects for consistency with full scan
        foreach ($file in $stagedTestFiles) {
            $fullPath = Join-Path $repoRoot $file
            if (Test-Path $fullPath) {
                $testFiles += Get-Item $fullPath
            }
        }
    }
    
    $unsafeTests = @()
    
    foreach ($file in $testFiles) {
        # Skip exempted files
        $relativePath = $file.FullName.Replace("$repoRoot\", "").Replace("\", "/")
        
        # Exempt fakes.py (test helper factories)
        if ($relativePath -match 'tests/fakes\.py$') {
            continue
        }
        
        # Exempt conftest.py (fixture definitions may need real operations)
        if ($relativePath -match 'conftest\.py$') {
            continue
        }
        
        $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
        if (-not $content) {
            continue
        }
        
        # Check if file has allow_real_bd or allow_git_repair markers
        $hasAllowRealBd = $content -match '@pytest\.mark\.allow_real_bd'
        $hasAllowGitRepair = $content -match '@pytest\.mark\.allow_git_repair'
        
        $lines = Get-Content $file.FullName -ErrorAction SilentlyContinue
        
        for ($i = 0; $i -lt $lines.Count; $i++) {
            $line = $lines[$i]
            
            # Skip comments and docstrings
            if ($line -match '^\s*(#|"""|'''''')') {
                continue
            }
            
            # Pattern 1: subprocess.run without mock
            if ($line -match 'subprocess\.(run|Popen|call|check_output|check_call)\s*\(') {
                # Check if this is inside a mock or patch context
                $isMocked = $false
                
                # Look backward for mock/patch context
                for ($j = [Math]::Max(0, $i - 10); $j -lt $i; $j++) {
                    $prevLine = $lines[$j]
                    if ($prevLine -match '(with\s+(patch|mock)|@patch|@mock\.patch|Mock\(|MagicMock\()') {
                        $isMocked = $true
                        break
                    }
                }
                
                # Look forward for assertion that this is a mock
                if (-not $isMocked) {
                    for ($j = $i; $j -lt [Math]::Min($i + 5, $lines.Count); $j++) {
                        $nextLine = $lines[$j]
                        if ($nextLine -match '\.assert_|mock_|Mock|fake_|FakeGitClient|FakeBeadsClient') {
                            $isMocked = $true
                            break
                        }
                    }
                }
                
                # Check if inside fakes.py helper function (returns CompletedProcess)
                if ($line -match 'CompletedProcess') {
                    $isMocked = $true
                }
                
                # Check if this is a Windows mklink command (look forward for cmd and mklink args)
                if (-not $isMocked) {
                    for ($j = $i; $j -lt [Math]::Min($i + 10, $lines.Count); $j++) {
                        if ($lines[$j] -match 'mklink') {
                            $isMocked = $true
                            break
                        }
                    }
                }
                
                # Check if inside try/except with pytest.skip for admin-required operations
                if (-not $isMocked) {
                    for ($j = [Math]::Max(0, $i - 5); $j -lt [Math]::Min($i + 10, $lines.Count); $j++) {
                        if ($lines[$j] -match 'pytest\.skip.*[Cc]annot create') {
                            $isMocked = $true
                            break
                        }
                    }
                }
                
                if (-not $isMocked) {
                    # Check if this is a git command
                    $isGitCommand = $line -match "subprocess\.\w+\(\s*\[['`"]git['`"]"
                    
                    # If it's a git command, only allow if has allow_git_repair marker
                    if ($isGitCommand -and -not $hasAllowGitRepair) {
                        $unsafeTests += @{
                            File = $relativePath
                            Line = $i + 1
                            Issue = "Real subprocess call to git command without @pytest.mark.allow_git_repair"
                            Code = $line.Trim()
                        }
                    }
                    # If it's not a git command, flag it anyway (requires mocking)
                    elseif (-not $isGitCommand) {
                        $unsafeTests += @{
                            File = $relativePath
                            Line = $i + 1
                            Issue = "Real subprocess call without proper mocking"
                            Code = $line.Trim()
                        }
                    }
                }
            }
            
            # Pattern 2: os.system calls
            if ($line -match 'os\.system\s*\(' -and $line -notmatch '#') {
                $unsafeTests += @{
                    File = $relativePath
                    Line = $i + 1
                    Issue = "os.system() call can hang - use subprocess with mocks instead"
                    Code = $line.Trim()
                }
            }
            
            # Pattern 3: Direct git worktree/add/commit/push commands in string literals
            if ($line -match "['`"](git\s+(worktree|add|commit|push|checkout|branch|stash|pull|fetch))['`"]" `
                -and $line -notmatch '#' `
                -and $line -notmatch 'merge' `
                -and -not $hasAllowGitRepair) {
                
                # Skip if this is in a mock configuration
                $skipLine = $false
                for ($j = [Math]::Max(0, $i - 5); $j -lt $i; $j++) {
                    if ($lines[$j] -match '(run_git_results|FakeGitClient|mock|patch)') {
                        $skipLine = $true
                        break
                    }
                }
                
                if (-not $skipLine) {
                    $unsafeTests += @{
                        File = $relativePath
                        Line = $i + 1
                        Issue = "Git command string without @pytest.mark.allow_git_repair - use FakeGitClient instead"
                        Code = $line.Trim()
                    }
                }
            }
            
            # Pattern 4: Real beads CLI calls without marker
            if ($line -match "subprocess\.\w+\(\s*\[['`"](bd|br)['`"]" -and -not $hasAllowRealBd) {
                # Check if this is mocked
                $isMocked = $false
                for ($j = [Math]::Max(0, $i - 10); $j -lt $i; $j++) {
                    if ($lines[$j] -match '(with\s+(patch|mock)|@patch|FakeBeadsClient|_blocked)') {
                        $isMocked = $true
                        break
                    }
                }
                
                if (-not $isMocked) {
                    $unsafeTests += @{
                        File = $relativePath
                        Line = $i + 1
                        Issue = "Real beads CLI call without @pytest.mark.allow_real_bd"
                        Code = $line.Trim()
                    }
                }
            }
        }
    }
    
    if ($unsafeTests.Count -gt 0) {
        Write-Host "❌ $($unsafeTests.Count) unsafe test pattern(s) found" -ForegroundColor Red
        Write-Host ""
        Write-Host "Tests MUST use mocks for subprocess, git, and filesystem operations." -ForegroundColor Yellow
        Write-Host "This prevents test hangs in worktrees and CI environments." -ForegroundColor Yellow
        Write-Host ""
        
        foreach ($test in $unsafeTests) {
            Write-Host "  $($test.File):$($test.Line)" -ForegroundColor Red
            Write-Host "    Issue: $($test.Issue)" -ForegroundColor Yellow
            Write-Host "    Code: $($test.Code)" -ForegroundColor Gray
            Write-Host ""
        }
        
        Write-Host "Fix options:" -ForegroundColor Cyan
        Write-Host "  1. Use FakeGitClient or FakeBeadsClient from tests/fakes.py" -ForegroundColor White
        Write-Host "  2. Use @patch('subprocess.run') or @patch('pokepoke.module._run_bd')" -ForegroundColor White
        Write-Host "  3. Add @pytest.mark.allow_real_bd for beads integration tests" -ForegroundColor White
        Write-Host "  4. Add @pytest.mark.allow_git_repair for git integration tests" -ForegroundColor White
        Write-Host ""
        Write-Host "See tests/conftest.py for fixture implementations and tests/fakes.py for fake helpers." -ForegroundColor Cyan
        exit 1
    }
    else {
        Write-Host "✅ No unsafe test patterns detected" -ForegroundColor Green
        exit 0
    }
}
catch {
    Write-Host "❌ Error: $_" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Gray
    exit 1
}
