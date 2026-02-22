<#
.SYNOPSIS
    Build the PokePoke Windows installer using NSIS.

.DESCRIPTION
    This script builds the Windows installer for PokePoke. It requires:
    1. PyInstaller build completed (dist/PokePoke/ exists)
    2. NSIS installed and in PATH (makensis command available)
    3. WebView2 bootstrapper downloaded to this directory

.PARAMETER SkipWebView2Check
    Skip verification that WebView2 bootstrapper exists (for CI builds that download it separately).

.EXAMPLE
    .\build_installer.ps1
    
.EXAMPLE
    .\build_installer.ps1 -SkipWebView2Check
#>

param(
    [switch]$SkipWebView2Check
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

Write-Host "=== PokePoke Installer Build ===" -ForegroundColor Cyan

# Check for NSIS
Write-Host "`nChecking for NSIS..." -ForegroundColor Yellow
$nsisPath = Get-Command makensis -ErrorAction SilentlyContinue
if (-not $nsisPath) {
    # Try common installation paths
    $commonPaths = @(
        "C:\Program Files (x86)\NSIS\makensis.exe",
        "C:\Program Files\NSIS\makensis.exe"
    )
    foreach ($path in $commonPaths) {
        if (Test-Path $path) {
            $nsisPath = $path
            break
        }
    }
}

if (-not $nsisPath) {
    Write-Error @"
NSIS not found. Please install NSIS from https://nsis.sourceforge.io/
After installation, either:
  1. Add NSIS to your PATH, or
  2. Install to default location (C:\Program Files (x86)\NSIS\)
"@
    exit 1
}
Write-Host "Found NSIS: $nsisPath" -ForegroundColor Green

# Check for PyInstaller dist
$distDir = Join-Path $ProjectRoot "dist\PokePoke"
Write-Host "`nChecking for PyInstaller output..." -ForegroundColor Yellow
if (-not (Test-Path $distDir)) {
    Write-Error @"
PyInstaller output not found at: $distDir
Please run the PyInstaller build first:
  cd $ProjectRoot
  pyinstaller packaging/pyinstaller/pokepoke.spec
"@
    exit 1
}
Write-Host "Found PyInstaller output: $distDir" -ForegroundColor Green

# Check for WebView2 bootstrapper
$webview2Path = Join-Path $ScriptDir "MicrosoftEdgeWebview2Setup.exe"
Write-Host "`nChecking for WebView2 bootstrapper..." -ForegroundColor Yellow
if (-not $SkipWebView2Check -and -not (Test-Path $webview2Path)) {
    Write-Warning @"
WebView2 bootstrapper not found at: $webview2Path

To download the WebView2 Evergreen Bootstrapper:
  1. Visit: https://developer.microsoft.com/en-us/microsoft-edge/webview2/
  2. Download 'Evergreen Bootstrapper'
  3. Save as: $webview2Path

Or run this PowerShell command:
  Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile '$webview2Path'

The installer will still build but WebView2 installation will fail for users who don't have it.
"@
    
    $continue = Read-Host "Continue without WebView2 bootstrapper? (y/N)"
    if ($continue -ne 'y' -and $continue -ne 'Y') {
        exit 1
    }
} elseif (Test-Path $webview2Path) {
    Write-Host "Found WebView2 bootstrapper: $webview2Path" -ForegroundColor Green
}

# Build the installer
Write-Host "`nBuilding installer..." -ForegroundColor Yellow
$nsiFile = Join-Path $ScriptDir "pokepoke.nsi"

Push-Location $ScriptDir
try {
    if ($nsisPath -is [System.Management.Automation.ApplicationInfo]) {
        & $nsisPath.Source $nsiFile
    } else {
        & $nsisPath $nsiFile
    }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "NSIS build failed with exit code: $LASTEXITCODE"
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

# Verify output
$installerPath = Join-Path $ProjectRoot "dist\PokePokeInstaller-0.1.0.exe"
if (Test-Path $installerPath) {
    $fileInfo = Get-Item $installerPath
    Write-Host "`n=== Build Complete ===" -ForegroundColor Green
    Write-Host "Installer: $installerPath"
    Write-Host "Size: $([math]::Round($fileInfo.Length / 1MB, 2)) MB"
} else {
    Write-Error "Installer was not created at expected location: $installerPath"
    exit 1
}
