<#
.SYNOPSIS
    Build PokePoke with PyInstaller including code signing.

.DESCRIPTION
    Enhanced PyInstaller build script that includes code signing capability.
    Automatically detects available signing certificates and signs the executable after building.

.PARAMETER SkipSigning
    Skip code signing (useful for development builds or when no certificate is available).

.PARAMETER CertificateSource
    Specify certificate source: Auto (default), Store, File, Azure, or SelfSigned.

.PARAMETER CertificatePath
    Path to certificate file (.pfx) when using File source.

.PARAMETER CertificateThumbprint
    Thumbprint of certificate in store when using Store source.

.PARAMETER Clean
    Clean build directories before building.

.PARAMETER Verbose
    Enable verbose output.

.EXAMPLE
    .\build_with_signing.ps1
    
    Build with automatic certificate detection and signing.

.EXAMPLE
    .\build_with_signing.ps1 -SkipSigning
    
    Build without code signing.

.EXAMPLE
    .\build_with_signing.ps1 -CertificateSource File -CertificatePath ".\mycert.pfx"
    
    Build using a specific certificate file.
#>

[CmdletBinding()]
param(
    [switch]$SkipSigning,
    
    [ValidateSet('Auto', 'Store', 'File', 'Azure', 'SelfSigned')]
    [string]$CertificateSource = 'Auto',
    
    [string]$CertificatePath,
    
    [string]$CertificateThumbprint,
    
    [switch]$Clean,
    
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

# Set verbose preference
if ($Verbose) {
    $VerbosePreference = 'Continue'
}

Write-Host "=== PokePoke PyInstaller Build with Code Signing ===" -ForegroundColor Cyan

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

# Clean build directories if requested
if ($Clean) {
    Write-Host "`nCleaning build directories..." -ForegroundColor Yellow
    $buildDir = Join-Path $ProjectRoot "build"
    $distDir = Join-Path $ProjectRoot "dist"
    
    if (Test-Path $buildDir) {
        Remove-Item $buildDir -Recurse -Force
        Write-Host "✓ Cleaned build directory" -ForegroundColor Green
    }
    
    if (Test-Path $distDir) {
        Remove-Item $distDir -Recurse -Force
        Write-Host "✓ Cleaned dist directory" -ForegroundColor Green
    }
}

# Check for PyInstaller
Write-Host "`nChecking for PyInstaller..." -ForegroundColor Yellow
$pyinstaller = Get-Command pyinstaller -ErrorAction SilentlyContinue
if (-not $pyinstaller) {
    Write-Error @"
PyInstaller not found. Please install PyInstaller:
  pip install pyinstaller

Or activate the appropriate Python environment.
"@
    exit 1
}
Write-Host "Found PyInstaller: $($pyinstaller.Source)" -ForegroundColor Green

# Check for spec file
$specFile = Join-Path $ScriptDir "pokepoke.spec"
if (-not (Test-Path $specFile)) {
    Write-Error "PyInstaller spec file not found: $specFile"
    exit 1
}
Write-Host "Found spec file: $specFile" -ForegroundColor Green

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

# Run PyInstaller build
Write-Host "`nRunning PyInstaller build..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    & pyinstaller $specFile --noconfirm
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "PyInstaller build failed with exit code: $LASTEXITCODE"
        exit $LASTEXITCODE
    }
    
    Write-Host "✓ PyInstaller build completed successfully" -ForegroundColor Green
    
} finally {
    Pop-Location
}

# Verify build output
$exePath = Join-Path $ProjectRoot "dist\PokePoke\PokePoke.exe"
if (-not (Test-Path $exePath)) {
    Write-Error "Build output not found: $exePath"
    exit 1
}

$fileInfo = Get-Item $exePath
Write-Host "✓ Executable created: $exePath" -ForegroundColor Green
Write-Host "  Size: $([math]::Round($fileInfo.Length / 1MB, 2)) MB" -ForegroundColor White

# Sign the executable
if (-not $SkipSigning -and $certificateInfo -and (Get-Command Invoke-CodeSigning -ErrorAction SilentlyContinue)) {
    Write-Host "`nSigning executable..." -ForegroundColor Yellow
    
    $signingResult = Invoke-CodeSigning -FilePath $exePath -CertificateInfo $certificateInfo
    
    if ($signingResult) {
        Write-Host "✓ Executable signed successfully" -ForegroundColor Green
        
        # Verify the signature
        if (Get-Command Test-CodeSignature -ErrorAction SilentlyContinue) {
            Write-Host "Verifying signature..." -ForegroundColor Yellow
            $verification = Test-CodeSignature -FilePath $exePath
            
            if ($verification -and $verification.IsSigned) {
                Write-Host "✓ Signature verification passed" -ForegroundColor Green
                Write-Host "  Status: $($verification.Status)" -ForegroundColor White
                Write-Host "  Signer: $($verification.SignerCertificate.Subject)" -ForegroundColor White
            } else {
                Write-Warning "Signature verification failed or file is not signed"
            }
        }
    } else {
        Write-Warning "Code signing failed, but build will continue"
        Write-Warning "The executable is unsigned and may show security warnings"
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

Write-Host "`n=== Build Complete ===" -ForegroundColor Green
Write-Host "Executable: $exePath" -ForegroundColor White

# Check if it's signed
try {
    $signature = Get-AuthenticodeSignature -FilePath $exePath
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
Write-Host "1. Test the executable: .\dist\PokePoke\PokePoke.exe --help" -ForegroundColor White
Write-Host "2. Create installer: .\packaging\installer\build_installer.ps1" -ForegroundColor White
if (-not $certificateInfo -and -not $SkipSigning) {
    Write-Host "3. Create signing certificate: .\packaging\signing\Create-SelfSignedCert.ps1" -ForegroundColor White
}