# PokePoke Code Signing

This directory contains the complete code signing infrastructure for PokePoke Windows executables and installers.

## Overview

PokePoke implements a flexible code signing system that supports multiple certificate sources and environments:

- **Self-signed certificates** - For development and testing
- **Certificate files (.pfx)** - For traditional code signing certificates
- **Certificate store** - For certificates installed in Windows certificate store
- **Azure Trusted Signing** - For cloud-based code signing in CI/CD

## Quick Start

### 1. Development Setup (Self-Signed Certificate)

For local development, create a self-signed certificate:

```powershell
# Run as Administrator for trusted installation
.\packaging\signing\Create-SelfSignedCert.ps1

# Or without admin (certificate won't be trusted)
.\packaging\signing\Create-SelfSignedCert.ps1
```

### 2. Build with Code Signing

Build the executable with signing:

```powershell
# PyInstaller build with signing
.\packaging\pyinstaller\build_with_signing.ps1

# NSIS installer build with signing
.\packaging\installer\build_installer.ps1
```

### 3. Verify Signatures

Check if files are properly signed:

```powershell
# Import the signing module
Import-Module .\packaging\signing\CodeSigning.psm1

# Test a signature
Test-CodeSignature -FilePath ".\dist\PokePoke\PokePoke.exe"
```

## Architecture

### Core Components

1. **CodeSigning.psm1** - Main code signing module with certificate detection and signing functions
2. **SigningConfiguration.psm1** - Configuration management and Azure Trusted Signing integration
3. **Create-SelfSignedCert.ps1** - Self-signed certificate generation for development
4. **signing-config-template.yml** - Configuration template with all available options

### Certificate Detection Flow

The system automatically detects certificates in this order:

1. **Azure Trusted Signing** - If environment variables are configured
2. **Certificate Store** - Searches CurrentUser\My and LocalMachine\My stores
3. **Certificate File** - If path is provided and file exists
4. **Self-Signed** - Looks for PokePoke development certificates

## Configuration

### Environment Variables

Set these environment variables for different certificate sources:

```bash
# Azure Trusted Signing
export AZURE_TRUSTED_SIGNING_ENDPOINT="https://eus.codesigning.azure.net/"
export AZURE_TRUSTED_SIGNING_ACCOUNT_NAME="MyAccount"
export AZURE_TRUSTED_SIGNING_PROFILE_NAME="MyProfile"

# Certificate file password
export CERT_PASSWORD="your-certificate-password"

# Force specific certificate source
export POKEPOKE_CERT_SOURCE="Azure"  # Auto, Store, File, Azure, SelfSigned

# Disable signing entirely
export POKEPOKE_SKIP_SIGNING="true"
```

### Configuration File

Create `signing-config.yml` in the project root to customize signing behavior:

```yaml
signing:
  certificate_source: Auto
  description: "PokePoke - Autonomous Beads + Copilot CLI Orchestrator"
  
environments:
  development:
    certificate_source: SelfSigned
  ci:
    certificate_source: Azure
    required: true
  production:
    certificate_source: Auto
    required: true

certificates:
  azure:
    endpoint: "https://eus.codesigning.azure.net/"
    account_name: "MyAccount"
    profile_name: "MyProfile"
```

## Certificate Sources

### Self-Signed Certificates (Development)

**Purpose:** Local development and testing  
**Security:** Low - Only trusted on the machine where created  
**Setup:**

```powershell
# Create with default settings
.\packaging\signing\Create-SelfSignedCert.ps1

# Create with custom settings
.\packaging\signing\Create-SelfSignedCert.ps1 -SubjectName "My Company Dev" -ValidityYears 3

# Export to file
.\packaging\signing\Create-SelfSignedCert.ps1 -ExportPath ".\dev-cert.pfx"
```

**Pros:**
- Free and easy to create
- No external dependencies
- Good for development workflows

**Cons:**
- Shows security warnings to end users
- Not suitable for distribution
- Only trusted on local machine (unless installed as trusted root)

### Traditional Code Signing Certificates

**Purpose:** Production releases with trusted certificates  
**Security:** High - Issued by trusted Certificate Authorities  
**Setup:**

1. Purchase certificate from a trusted CA (Sectigo, DigiCert, GlobalSign, etc.)
2. Install certificate in Windows certificate store OR save as .pfx file
3. Configure signing to use the certificate

**Using certificate store:**
```powershell
# Build will auto-detect certificates in store
.\packaging\pyinstaller\build_with_signing.ps1 -CertificateSource Store

# Or specify thumbprint
.\packaging\pyinstaller\build_with_signing.ps1 -CertificateSource Store -CertificateThumbprint "ABC123..."
```

**Using certificate file:**
```powershell
# Specify certificate file path
.\packaging\pyinstaller\build_with_signing.ps1 -CertificateSource File -CertificatePath ".\certificates\code-signing.pfx"

# Will prompt for password, or set CERT_PASSWORD environment variable
```

**Pros:**
- Trusted by Windows SmartScreen
- No security warnings for end users
- Professional appearance

**Cons:**
- Cost (varies by CA and certificate type)
- Annual renewal required
- EV certificates require hardware security module

### Azure Trusted Signing

**Purpose:** Cloud-based code signing for CI/CD pipelines  
**Security:** High - Microsoft-managed certificate authority  
**Setup:**

1. **Azure Setup:**
   - Create Azure Trusted Signing account
   - Create a certificate profile
   - Grant appropriate permissions

2. **Install AzureSignTool:**
   ```bash
   dotnet tool install --global AzureSignTool
   ```

3. **Configure Authentication:**
   ```bash
   # Service principal (recommended for CI/CD)
   export AZURE_CLIENT_ID="your-client-id"
   export AZURE_CLIENT_SECRET="your-client-secret"
   export AZURE_TENANT_ID="your-tenant-id"
   
   # Or use Azure CLI authentication
   az login
   ```

4. **Configure Signing:**
   ```bash
   export AZURE_TRUSTED_SIGNING_ENDPOINT="https://eus.codesigning.azure.net/"
   export AZURE_TRUSTED_SIGNING_ACCOUNT_NAME="MyAccount"
   export AZURE_TRUSTED_SIGNING_PROFILE_NAME="MyProfile"
   ```

**Pros:**
- No certificate management required
- Highly secure (HSM-backed)
- Perfect for CI/CD pipelines
- Trusted by Windows SmartScreen
- Pay-per-signature model

**Cons:**
- Requires Azure subscription
- Internet connectivity required for signing
- Setup complexity higher than traditional certificates

## Build Integration

### PyInstaller Signing

The enhanced PyInstaller build script (`packaging\pyinstaller\build_with_signing.ps1`) automatically signs the executable after building:

```powershell
# Auto-detect certificate and sign
.\packaging\pyinstaller\build_with_signing.ps1

# Skip signing for faster development builds
.\packaging\pyinstaller\build_with_signing.ps1 -SkipSigning

# Use specific certificate source
.\packaging\pyinstaller\build_with_signing.ps1 -CertificateSource Azure
```

### Installer Signing

The NSIS installer build script (`packaging\installer\build_installer.ps1`) signs the final installer:

```powershell
# Build and sign installer
.\packaging\installer\build_installer.ps1

# Skip WebView2 check and code signing
.\packaging\installer\build_installer.ps1 -SkipWebView2Check -SkipSigning
```

### Build Pipeline Integration

For automated builds, signing happens automatically based on available certificates and configuration:

```yaml
# GitHub Actions example
- name: Build with Code Signing
  run: |
    # Set Azure Trusted Signing configuration
    $env:AZURE_TRUSTED_SIGNING_ENDPOINT = "${{ secrets.AZURE_SIGNING_ENDPOINT }}"
    $env:AZURE_TRUSTED_SIGNING_ACCOUNT_NAME = "${{ secrets.AZURE_SIGNING_ACCOUNT }}"
    $env:AZURE_TRUSTED_SIGNING_PROFILE_NAME = "${{ secrets.AZURE_SIGNING_PROFILE }}"
    
    # Build executable and installer with signing
    .\packaging\pyinstaller\build_with_signing.ps1
    .\packaging\installer\build_installer.ps1
  env:
    AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
    AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
    AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
```

## CI/CD Integration

### GitHub Actions Secrets

Configure these secrets in your GitHub repository:

**For Azure Trusted Signing:**
- `AZURE_CLIENT_ID` - Service principal client ID
- `AZURE_CLIENT_SECRET` - Service principal secret
- `AZURE_TENANT_ID` - Azure tenant ID
- `AZURE_SIGNING_ENDPOINT` - Azure Trusted Signing endpoint
- `AZURE_SIGNING_ACCOUNT` - Account name
- `AZURE_SIGNING_PROFILE` - Profile name

**For traditional certificates:**
- `CODE_SIGNING_CERT` - Base64-encoded .pfx certificate
- `CERT_PASSWORD` - Certificate password

### Workflow Examples

**Azure Trusted Signing:**
```yaml
name: Build and Sign
on: [push, pull_request]

jobs:
  build:
    runs-on: windows-latest
    steps:
    - uses: actions/checkout@v4
    
    - name: Setup .NET
      uses: actions/setup-dotnet@v4
      with:
        dotnet-version: '8.0.x'
    
    - name: Install AzureSignTool
      run: dotnet tool install --global AzureSignTool
    
    - name: Build and Sign
      env:
        AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
        AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
        AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
        AZURE_TRUSTED_SIGNING_ENDPOINT: ${{ secrets.AZURE_SIGNING_ENDPOINT }}
        AZURE_TRUSTED_SIGNING_ACCOUNT_NAME: ${{ secrets.AZURE_SIGNING_ACCOUNT }}
        AZURE_TRUSTED_SIGNING_PROFILE_NAME: ${{ secrets.AZURE_SIGNING_PROFILE }}
      run: |
        .\packaging\pyinstaller\build_with_signing.ps1
        .\packaging\installer\build_installer.ps1
```

**Certificate file:**
```yaml
    - name: Decode certificate
      run: |
        echo "${{ secrets.CODE_SIGNING_CERT }}" | base64 --decode > cert.pfx
    
    - name: Build and Sign
      env:
        CERT_PASSWORD: ${{ secrets.CERT_PASSWORD }}
      run: |
        .\packaging\pyinstaller\build_with_signing.ps1 -CertificateSource File -CertificatePath ".\cert.pfx"
        .\packaging\installer\build_installer.ps1 -CertificateSource File -CertificatePath ".\cert.pfx"
```

## API Reference

### CodeSigning Module Functions

**Find-CodeSigningCertificate**
```powershell
$cert = Find-CodeSigningCertificate -CertificateSource Auto
$cert = Find-CodeSigningCertificate -CertificateSource File -CertificatePath "cert.pfx"
$cert = Find-CodeSigningCertificate -CertificateSource Store -CertificateThumbprint "ABC123..."
```

**Invoke-CodeSigning**
```powershell
$success = Invoke-CodeSigning -FilePath "app.exe" -CertificateInfo $cert
```

**Test-CodeSignature**
```powershell
$result = Test-CodeSignature -FilePath "app.exe"
Write-Host "Signed: $($result.IsSigned), Valid: $($result.IsValid)"
```

**Get-CodeSigningEnvironment**
```powershell
$env = Get-CodeSigningEnvironment
Write-Host "SignTool: $($env.SignToolPath)"
Write-Host "Certificates found: $($env.Certificates.Count)"
```

### SigningConfiguration Module Functions

**Get-SigningConfiguration**
```powershell
$config = Get-SigningConfiguration -Environment "production"
$config = Get-SigningConfiguration -ConfigFile "custom-signing.yml"
$config = Get-SigningConfiguration -Parameters @{ SkipSigning = $true }
```

**Install-AzureSignTool**
```powershell
$installed = Install-AzureSignTool
```

**Test-AzureTrustedSigning**
```powershell
$ready = Test-AzureTrustedSigning -Config $config
```

## Troubleshooting

### Common Issues

**"No suitable code signing certificate found"**
- Solution: Create a self-signed certificate with `Create-SelfSignedCert.ps1`
- For production: Purchase and install a proper code signing certificate

**"SignTool not found"**
- Solution: Install Windows SDK or Visual Studio Build Tools
- Alternative: Ensure signtool.exe is in PATH

**"AzureSignTool not found"**
- Solution: `dotnet tool install --global AzureSignTool`
- Check: `dotnet --version` (requires .NET 6.0+)

**"Azure authentication failed"**
- Check: Azure CLI login (`az login`)
- Check: Service principal credentials are correct
- Check: Permissions on Azure Trusted Signing account

**"Certificate has expired"**
- For self-signed: Create new certificate with `Create-SelfSignedCert.ps1 -Force`
- For commercial: Renew certificate with your CA

**"File is signed but not trusted"**
- Self-signed: Install as trusted root (requires admin)
- Commercial: Ensure certificate chain is complete
- Check: Windows time/date is correct (affects certificate validity)

### Debug Signing Issues

Enable verbose logging:

```powershell
# Enable verbose output in PowerShell
$VerbosePreference = 'Continue'

# Or use -Verbose parameter
.\packaging\pyinstaller\build_with_signing.ps1 -Verbose

# Check signature manually
Get-AuthenticodeSignature -FilePath "app.exe" | Format-List
```

### Testing Signatures

Test how Windows treats your signed files:

1. **Check signature status:**
   ```powershell
   Get-AuthenticodeSignature -FilePath "app.exe"
   ```

2. **Test SmartScreen behavior:**
   - Copy signed file to clean machine
   - Download and run the installer
   - Check for SmartScreen warnings

3. **Verify certificate chain:**
   ```powershell
   $cert = (Get-AuthenticodeSignature -FilePath "app.exe").SignerCertificate
   $cert.Verify()  # Should return $true for trusted certificates
   ```

## Security Considerations

### Certificate Storage

- **Self-signed certificates:** Store private keys securely, don't commit to version control
- **Commercial certificates:** Use hardware security modules (HSM) for EV certificates
- **Azure Trusted Signing:** Use service principals with minimal required permissions

### CI/CD Security

- **Secrets management:** Use GitHub Secrets or Azure Key Vault for sensitive data
- **Least privilege:** Grant minimal permissions required for signing
- **Audit logging:** Enable audit logs for signing operations
- **Environment separation:** Use different certificates/profiles for dev/staging/prod

### Code Integrity

- **Verify signatures:** Always verify signatures after signing
- **Timestamp signatures:** Use timestamp servers to extend signature validity
- **Build reproducibility:** Ensure builds are reproducible and verifiable

## Maintenance

### Certificate Renewal

1. **Commercial certificates:** Renew before expiration (CA will notify)
2. **Self-signed certificates:** Recreate with `Create-SelfSignedCert.ps1 -Force`
3. **Azure Trusted Signing:** Certificates are automatically managed by Microsoft

### Updates and Dependencies

- **Windows SDK:** Keep SignTool updated with Windows SDK updates
- **AzureSignTool:** Update with `dotnet tool update --global AzureSignTool`
- **PowerShell modules:** Update powershell-yaml if used for configuration

### Monitoring

- **Build failures:** Monitor CI/CD for signing failures
- **Certificate expiration:** Set up alerts for certificate expiration
- **Signature verification:** Regularly verify signatures on released files

---

## Quick Reference Card

| Task | Command |
|------|---------|
| Create dev certificate | `.\packaging\signing\Create-SelfSignedCert.ps1` |
| Build signed executable | `.\packaging\pyinstaller\build_with_signing.ps1` |
| Build signed installer | `.\packaging\installer\build_installer.ps1` |
| Check signature | `Get-AuthenticodeSignature -FilePath "app.exe"` |
| Test environment | `Import-Module .\packaging\signing\CodeSigning.psm1; Get-CodeSigningEnvironment` |
| Skip signing | `.\build_script.ps1 -SkipSigning` |
| Use Azure signing | Set `AZURE_TRUSTED_SIGNING_*` environment variables |
| Use certificate file | `.\build_script.ps1 -CertificateSource File -CertificatePath "cert.pfx"` |

---

**Last Updated:** 2026-02-22  
**Version:** 1.0.0