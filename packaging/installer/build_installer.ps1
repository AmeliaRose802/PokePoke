<#
.SYNOPSIS
    Build the PokePoke Windows installer using NSIS with code signing.

.DESCRIPTION
    This script builds the Windows installer for PokePoke. It requires:
    1. PyInstaller build completed (dist/PokePoke/ exists)
    2. NSIS installed and in PATH (makensis command available)
    3. WebView2 bootstrapper downloaded to this directory
    
    The script automatically detects available code signing certificates and signs the installer.

.PARAMETER SkipWebView2Check
    Skip verification that WebView2 bootstrapper exists (for CI builds that download it separately).

.PARAMETER SkipSigning
    Skip code signing (useful for development builds or when no certificate is available).

.PARAMETER CertificateSource
    Specify certificate source: Auto (default), Store, File, Azure, or SelfSigned.

.PARAMETER CertificatePath
    Path to certificate file (.pfx) when using File source.

.PARAMETER CertificateThumbprint
    Thumbprint of certificate in store when using Store source.

.PARAMETER Verbose
    Enable verbose output.

.EXAMPLE
    .\build_installer.ps1
    
    Build with automatic certificate detection and signing.
    
.EXAMPLE
    .\build_installer.ps1 -SkipWebView2Check -SkipSigning
    
    Build without WebView2 check and without code signing.

.EXAMPLE
    .\build_installer.ps1 -CertificateSource File -CertificatePath ".\mycert.pfx"
    
    Build using a specific certificate file.
#>

param(
    [switch]$SkipWebView2Check,
    
    [switch]$SkipSigning,
    
    [ValidateSet('Auto', 'Store', 'File', 'Azure', 'SelfSigned')]
    [string]$CertificateSource = 'Auto',
    
    [string]$CertificatePath,
    
    [string]$CertificateThumbprint,
    
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

# Set verbose preference
if ($Verbose) {
    $VerbosePreference = 'Continue'
}

Write-Host "=== PokePoke Installer Build with Code Signing ===" -ForegroundColor Cyan

# Import code signing module
$signingModule = Join-Path $ScriptDir "..\signing\CodeSigning.psm1"
if (Test-Path $signingModule) {
    Import-Module $signingModule -Force
    Write-Host "✓ Code signing module loaded" -ForegroundColor Green
} else {
    if (-not $SkipSigning) {
        Write-Warning "Code signing module not found: $signingModule"
        Write-Warning "Continuing without code signing capability"
        $SkipSigning = $true
    }
}

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
    Write-Host "`n=== Installer Build Complete ===" -ForegroundColor Green
    Write-Host "Installer: $installerPath"
    Write-Host "Size: $([math]::Round($fileInfo.Length / 1MB, 2)) MB"
} else {
    Write-Error "Installer was not created at expected location: $installerPath"
    exit 1
}

# Find code signing certificate if not skipping signing
$certificateInfo = $null
if (-not $SkipSigning -and (Get-Command Find-CodeSigningCertificate -ErrorAction SilentlyContinue)) {
    Write-Host "`nSearching for code signing certificate..." -ForegroundColor Yellow
    
    $findParams = @{
        CertificateSource = $CertificateSource
    }
    
    if ($CertificatePath) {
        $findParams.CertificatePath = $CertificatePath
    }
    
    if ($CertificateThumbprint) {
        $findParams.CertificateThumbprint = $CertificateThumbprint
    }
    
    $certificateInfo = Find-CodeSigningCertificate @findParams
    
    if ($certificateInfo) {
        Write-Host "✓ Found certificate:" -ForegroundColor Green
        Write-Host "  Source: $($certificateInfo.Source)" -ForegroundColor White
        Write-Host "  Subject: $($certificateInfo.Subject)" -ForegroundColor White
        if ($certificateInfo.NotAfter) {
            Write-Host "  Expires: $($certificateInfo.NotAfter)" -ForegroundColor White
        }
        if ($certificateInfo.IsSelfSigned) {
            Write-Host "  ⚠️  Self-signed certificate (development only)" -ForegroundColor Yellow
        }
    } else {
        Write-Warning "No suitable code signing certificate found"
        Write-Host "To create a self-signed certificate for development:" -ForegroundColor Yellow
        Write-Host "  .\signing\Create-SelfSignedCert.ps1" -ForegroundColor Yellow
        $SkipSigning = $true
    }
}

# Sign the installer
if (-not $SkipSigning -and $certificateInfo -and (Get-Command Invoke-CodeSigning -ErrorAction SilentlyContinue)) {
    Write-Host "`nSigning installer..." -ForegroundColor Yellow
    
    $signingResult = Invoke-CodeSigning -FilePath $installerPath -CertificateInfo $certificateInfo -Description "PokePoke Installer"
    
    if ($signingResult) {
        Write-Host "✓ Installer signed successfully" -ForegroundColor Green
        
        # Verify the signature
        if (Get-Command Test-CodeSignature -ErrorAction SilentlyContinue) {
            Write-Host "Verifying signature..." -ForegroundColor Yellow
            $verification = Test-CodeSignature -FilePath $installerPath
            
            if ($verification -and $verification.IsSigned) {
                Write-Host "✓ Signature verification passed" -ForegroundColor Green
                Write-Host "  Status: $($verification.Status)" -ForegroundColor White
                Write-Host "  Signer: $($verification.SignerCertificate.Subject)" -ForegroundColor White
            } else {
                Write-Warning "Signature verification failed or installer is not signed"
            }
        }
    } else {
        Write-Warning "Code signing failed, but build will continue"
        Write-Warning "The installer is unsigned and may show security warnings"
    }
} else {
    Write-Host "`nSkipping code signing" -ForegroundColor Yellow
    if ($SkipSigning) {
        Write-Host "  Reason: -SkipSigning parameter specified" -ForegroundColor Gray
    } elseif (-not $certificateInfo) {
        Write-Host "  Reason: No certificate available" -ForegroundColor Gray
    } else {
        Write-Host "  Reason: Code signing module not loaded" -ForegroundColor Gray
    }
}

Write-Host "`n=== Installer Build Complete ===" -ForegroundColor Green
Write-Host "Installer: $installerPath" -ForegroundColor White

# Check final signature status
try {
    $signature = Get-AuthenticodeSignature -FilePath $installerPath
    if ($signature.Status -eq 'Valid') {
        Write-Host "Status: ✓ Signed and valid" -ForegroundColor Green
    } elseif ($signature.Status -eq 'UnknownError') {
        Write-Host "Status: ⚠️  Signed but with unknown error (may still work)" -ForegroundColor Yellow
    } elseif ($signature.SignerCertificate) {
        Write-Host "Status: ⚠️  Signed but not trusted ($($signature.Status))" -ForegroundColor Yellow
    } else {
        Write-Host "Status: ❌ Not signed" -ForegroundColor Red
    }
} catch {
    Write-Host "Status: ❓ Could not check signature" -ForegroundColor Gray
}

Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "1. Test the installer on a clean machine" -ForegroundColor White
Write-Host "2. Check for SmartScreen warnings during installation" -ForegroundColor White
if (-not $certificateInfo -and -not $SkipSigning) {
    Write-Host "3. Create signing certificate: .\signing\Create-SelfSignedCert.ps1" -ForegroundColor White
}
