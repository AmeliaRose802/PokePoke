<#
.SYNOPSIS
    Creates a self-signed code signing certificate for PokePoke development.

.DESCRIPTION
    Generates a self-signed certificate suitable for code signing during development.
    The certificate will be installed in the CurrentUser\My certificate store and
    the root certificate will be added to the Trusted Root Certification Authorities
    to avoid trust warnings.
    
    This is intended for development and testing only. For production releases,
    use a proper code signing certificate or Azure Trusted Signing.

.PARAMETER SubjectName
    The subject name for the certificate. Defaults to "PokePoke Development".

.PARAMETER ValidityYears
    Number of years the certificate should be valid. Defaults to 5.

.PARAMETER Force
    Overwrite existing certificate if one exists with the same subject.

.PARAMETER ExportPath
    Optional path to export the certificate (.pfx file) with private key.

.EXAMPLE
    .\Create-SelfSignedCert.ps1
    
    Creates a certificate with default settings.

.EXAMPLE
    .\Create-SelfSignedCert.ps1 -SubjectName "My Company Development" -ValidityYears 3 -ExportPath ".\mycert.pfx"
    
    Creates a certificate with custom subject name, 3-year validity, and exports to file.

.NOTES
    - Requires PowerShell running as Administrator to install to Trusted Root
    - The certificate will appear in Windows certificate store
    - Self-signed certificates will still show security warnings to end users
    - For CI/CD, consider using Azure Trusted Signing instead
#>

[CmdletBinding()]
param(
    [string]$SubjectName = "PokePoke Development",
    
    [ValidateRange(1, 10)]
    [int]$ValidityYears = 5,
    
    [switch]$Force,
    
    [string]$ExportPath
)

$ErrorActionPreference = "Stop"

Write-Host "=== PokePoke Self-Signed Certificate Generator ===" -ForegroundColor Cyan
Write-Host "Subject: $SubjectName" -ForegroundColor Yellow
Write-Host "Validity: $ValidityYears years" -ForegroundColor Yellow

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
if (-not $isAdmin) {
    Write-Warning "Not running as Administrator. The certificate will be created but may not be trusted."
    Write-Warning "To avoid trust warnings, run this script as Administrator."
}

# Check for existing certificate
Write-Host "`nChecking for existing certificate..." -ForegroundColor Yellow
$existingCert = Get-ChildItem 'Cert:\CurrentUser\My' | 
                Where-Object { 
                    $_.Subject -like "*$SubjectName*" -and 
                    $_.Issuer -eq $_.Subject -and  # Self-signed
                    $_.NotAfter -gt (Get-Date)
                }

if ($existingCert -and -not $Force) {
    Write-Host "✓ Valid certificate already exists:" -ForegroundColor Green
    Write-Host "  Subject: $($existingCert.Subject)"
    Write-Host "  Thumbprint: $($existingCert.Thumbprint)"
    Write-Host "  Expires: $($existingCert.NotAfter)"
    Write-Host "`nUse -Force to replace the existing certificate."
    exit 0
} elseif ($existingCert -and $Force) {
    Write-Host "Removing existing certificate (Force specified)..." -ForegroundColor Yellow
    $existingCert | Remove-Item -Force
}

# Create the certificate
Write-Host "`nCreating self-signed certificate..." -ForegroundColor Yellow

try {
    # Create the certificate with code signing usage
    $cert = New-SelfSignedCertificate `
        -Subject "CN=$SubjectName" `
        -Type CodeSigningCert `
        -KeyUsage DigitalSignature `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -HashAlgorithm SHA256 `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -NotAfter (Get-Date).AddYears($ValidityYears) `
        -TextExtension @(
            "2.5.29.37={text}1.3.6.1.5.5.7.3.3",  # Code Signing EKU
            "2.5.29.19={text}false"               # Not a CA
        )
    
    Write-Host "✓ Certificate created successfully!" -ForegroundColor Green
    Write-Host "  Thumbprint: $($cert.Thumbprint)"
    Write-Host "  Subject: $($cert.Subject)"
    Write-Host "  Expires: $($cert.NotAfter)"
    
} catch {
    Write-Error "Failed to create certificate: $($_.Exception.Message)"
    exit 1
}

# Install to Trusted Root (requires Admin)
if ($isAdmin) {
    Write-Host "`nInstalling certificate to Trusted Root Certification Authorities..." -ForegroundColor Yellow
    
    try {
        # Get the certificate from My store
        $certToTrust = Get-Item -Path "Cert:\CurrentUser\My\$($cert.Thumbprint)"
        
        # Export public key only
        $publicCert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($certToTrust.RawData)
        
        # Import to Trusted Root
        $store = New-Object System.Security.Cryptography.X509Certificates.X509Store(
            [System.Security.Cryptography.X509Certificates.StoreName]::Root,
            [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
        )
        $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
        $store.Add($publicCert)
        $store.Close()
        
        Write-Host "✓ Certificate installed to Trusted Root" -ForegroundColor Green
        Write-Host "  Files signed with this certificate will be trusted on this machine" -ForegroundColor Green
        
    } catch {
        Write-Warning "Failed to install to Trusted Root: $($_.Exception.Message)"
        Write-Warning "The certificate will work for signing but may show trust warnings."
    }
} else {
    Write-Host "`nSkipping Trusted Root installation (not running as Administrator)" -ForegroundColor Yellow
    Write-Host "To install as trusted root:" -ForegroundColor Yellow
    Write-Host "  1. Run PowerShell as Administrator" -ForegroundColor Yellow
    Write-Host "  2. Run: Get-ChildItem 'Cert:\CurrentUser\My\$($cert.Thumbprint)' | Export-Certificate -FilePath temp.cer" -ForegroundColor Yellow
    Write-Host "  3. Run: Import-Certificate -FilePath temp.cer -CertStoreLocation 'Cert:\CurrentUser\Root'" -ForegroundColor Yellow
}

# Export to file if requested
if ($ExportPath) {
    Write-Host "`nExporting certificate to file..." -ForegroundColor Yellow
    
    try {
        # Prompt for password
        $password = Read-Host "Enter password for exported certificate (or press Enter for no password)" -AsSecureString
        
        if ($password.Length -eq 0) {
            # Export without password
            Export-Certificate -Cert $cert -FilePath $ExportPath -Force | Out-Null
            Write-Host "✓ Certificate (public key only) exported to: $ExportPath" -ForegroundColor Green
        } else {
            # Export with password (includes private key)
            Export-PfxCertificate -Cert $cert -FilePath $ExportPath -Password $password -Force | Out-Null
            Write-Host "✓ Certificate with private key exported to: $ExportPath" -ForegroundColor Green
        }
        
    } catch {
        Write-Warning "Failed to export certificate: $($_.Exception.Message)"
    }
}

Write-Host "`n=== Certificate Creation Complete ===" -ForegroundColor Green
Write-Host "`nUsage Instructions:" -ForegroundColor Cyan
Write-Host "1. Build scripts will automatically detect and use this certificate" -ForegroundColor White
Write-Host "2. To use manually:" -ForegroundColor White
Write-Host "   - Thumbprint: $($cert.Thumbprint)" -ForegroundColor White
Write-Host "   - Location: Cert:\CurrentUser\My" -ForegroundColor White
Write-Host "3. To test signing:" -ForegroundColor White
Write-Host "   signtool sign /sha1 $($cert.Thumbprint) /fd SHA256 /tr http://timestamp.sectigo.com /td SHA256 yourfile.exe" -ForegroundColor White

Write-Host "`n⚠️  Security Notice:" -ForegroundColor Yellow
Write-Host "- This is a self-signed certificate for development only" -ForegroundColor Yellow
Write-Host "- End users will still see security warnings" -ForegroundColor Yellow
Write-Host "- Use a proper code signing certificate for production releases" -ForegroundColor Yellow
Write-Host "- Consider Azure Trusted Signing for CI/CD pipelines" -ForegroundColor Yellow