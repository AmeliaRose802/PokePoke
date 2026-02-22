# Azure Trusted Signing Setup Guide

This guide covers setting up Azure Trusted Signing for PokePoke code signing in CI/CD pipelines.

## Prerequisites

- Azure subscription with appropriate permissions
- .NET 6.0+ SDK for AzureSignTool
- GitHub repository with Actions enabled

## Step 1: Azure Trusted Signing Account Setup

### Create Trusted Signing Account

1. **Navigate to Azure Portal:**
   - Go to https://portal.azure.com
   - Search for "Trusted Signing" or navigate to Create a resource > Security > Trusted Signing

2. **Create Account:**
   - Click "Create"
   - Select subscription and resource group
   - Enter account name (e.g., "pokepoke-code-signing")
   - Select region (recommend same as your build agents)
   - Review and create

3. **Wait for Deployment:**
   - Deployment can take 10-15 minutes
   - You'll receive a notification when complete

### Create Certificate Profile

1. **Navigate to Your Trusted Signing Account:**
   - Go to the newly created Trusted Signing account in Azure Portal

2. **Create Certificate Profile:**
   - Click on "Certificate profiles" in the left menu
   - Click "+ Create"
   - Profile name: "PokePoke-Production" (or similar)
   - Certificate type: "Public trust" (for public distribution)
   - Subject: CN=Your Organization Name
   - Certificate validity: Select desired duration (1-3 years typical)
   - Key type: RSA 2048 (recommended for compatibility)

3. **Identity Validation:**
   - For public trust certificates, you'll need to complete identity validation
   - This process can take 1-5 business days depending on the CA
   - You'll need to provide business documentation

4. **Wait for Approval:**
   - The certificate profile will show "Pending" status during validation
   - You'll receive email notifications about the validation progress

## Step 2: Service Principal Setup

Create a service principal for automated access from CI/CD:

### Using Azure CLI

```bash
# Login to Azure
az login

# Create service principal
az ad sp create-for-rbac --name "pokepoke-code-signing-sp" --role "Trusted Signing Certificate Profile Signer" --scopes "/subscriptions/YOUR_SUBSCRIPTION_ID/resourceGroups/YOUR_RESOURCE_GROUP/providers/Microsoft.CodeSigning/codeSigningAccounts/YOUR_ACCOUNT_NAME"

# Note down the output:
# - appId (Client ID)
# - password (Client Secret)  
# - tenant (Tenant ID)
```

### Using Azure Portal

1. **Navigate to Azure Active Directory:**
   - Go to Azure Portal > Azure Active Directory > App registrations

2. **Create New Registration:**
   - Click "New registration"
   - Name: "PokePoke Code Signing Service Principal"
   - Account types: "Accounts in this organizational directory only"
   - Click "Register"

3. **Create Client Secret:**
   - In the app registration, go to "Certificates & secrets"
   - Click "New client secret"
   - Description: "Code signing secret"
   - Expires: Select appropriate duration (24 months recommended)
   - Copy the secret value immediately (it won't be shown again)

4. **Grant Permissions:**
   - Navigate to your Trusted Signing account
   - Go to "Access control (IAM)"
   - Click "Add role assignment"
   - Role: "Trusted Signing Certificate Profile Signer"
   - Assign access to: "User, group, or service principal"
   - Select your service principal
   - Click "Review + assign"

## Step 3: Install and Configure Tools

### Install AzureSignTool

```bash
# Install globally
dotnet tool install --global AzureSignTool

# Verify installation
AzureSignTool --version
```

### Test Configuration Locally

```powershell
# Set environment variables for testing
$env:AZURE_CLIENT_ID = "your-client-id"
$env:AZURE_CLIENT_SECRET = "your-client-secret"
$env:AZURE_TENANT_ID = "your-tenant-id"
$env:AZURE_TRUSTED_SIGNING_ENDPOINT = "https://eus.codesigning.azure.net/"
$env:AZURE_TRUSTED_SIGNING_ACCOUNT_NAME = "your-account-name"
$env:AZURE_TRUSTED_SIGNING_PROFILE_NAME = "your-profile-name"

# Test signing with a dummy file
echo "test" > test.txt
AzureSignTool sign --azure-key-vault-url $env:AZURE_TRUSTED_SIGNING_ENDPOINT --azure-key-vault-certificate $env:AZURE_TRUSTED_SIGNING_PROFILE_NAME --file-digest sha256 --timestamp-rfc3161 http://timestamp.sectigo.com --timestamp-digest sha256 test.txt
```

## Step 4: GitHub Actions Integration

### Configure Repository Secrets

In your GitHub repository, go to Settings > Secrets and variables > Actions, and add:

- `AZURE_CLIENT_ID` - Service principal client ID
- `AZURE_CLIENT_SECRET` - Service principal secret  
- `AZURE_TENANT_ID` - Azure tenant ID
- `AZURE_SIGNING_ENDPOINT` - Azure Trusted Signing endpoint (e.g., https://eus.codesigning.azure.net/)
- `AZURE_SIGNING_ACCOUNT` - Account name
- `AZURE_SIGNING_PROFILE` - Certificate profile name

### Update GitHub Workflow

Create or update `.github/workflows/build-and-sign.yml`:

```yaml
name: Build and Sign Release

on:
  push:
    tags:
      - 'v*'
  workflow_dispatch:

jobs:
  build-windows:
    runs-on: windows-latest
    
    steps:
    - name: Checkout code
      uses: actions/checkout@v4
      with:
        fetch-depth: 0

    - name: Setup Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.12'

    - name: Setup .NET
      uses: actions/setup-dotnet@v4
      with:
        dotnet-version: '8.0.x'

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install pyinstaller

    - name: Install AzureSignTool
      run: dotnet tool install --global AzureSignTool

    - name: Download WebView2 Bootstrapper
      run: |
        Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile 'packaging/installer/MicrosoftEdgeWebview2Setup.exe'

    - name: Build and Sign Executable
      env:
        AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
        AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
        AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
        AZURE_TRUSTED_SIGNING_ENDPOINT: ${{ secrets.AZURE_SIGNING_ENDPOINT }}
        AZURE_TRUSTED_SIGNING_ACCOUNT_NAME: ${{ secrets.AZURE_SIGNING_ACCOUNT }}
        AZURE_TRUSTED_SIGNING_PROFILE_NAME: ${{ secrets.AZURE_SIGNING_PROFILE }}
      run: |
        .\packaging\pyinstaller\build_with_signing.ps1 -CertificateSource Azure

    - name: Build and Sign Installer
      env:
        AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
        AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
        AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
        AZURE_TRUSTED_SIGNING_ENDPOINT: ${{ secrets.AZURE_SIGNING_ENDPOINT }}
        AZURE_TRUSTED_SIGNING_ACCOUNT_NAME: ${{ secrets.AZURE_SIGNING_ACCOUNT }}
        AZURE_TRUSTED_SIGNING_PROFILE_NAME: ${{ secrets.AZURE_SIGNING_PROFILE }}
      run: |
        .\packaging\installer\build_installer.ps1 -CertificateSource Azure

    - name: Verify Signatures
      run: |
        Write-Host "=== Executable Signature ==="
        Get-AuthenticodeSignature -FilePath "dist\PokePoke\PokePoke.exe" | Format-List
        
        Write-Host "=== Installer Signature ==="
        Get-AuthenticodeSignature -FilePath "dist\PokePokeInstaller-0.1.0.exe" | Format-List

    - name: Upload Release Assets
      uses: actions/upload-artifact@v4
      with:
        name: signed-windows-release
        path: |
          dist/PokePoke/
          dist/PokePokeInstaller-*.exe
        retention-days: 90

    - name: Create Release (if tag)
      if: startsWith(github.ref, 'refs/tags/')
      uses: softprops/action-gh-release@v1
      with:
        files: |
          dist/PokePokeInstaller-*.exe
        draft: false
        prerelease: false
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Step 5: Testing and Validation

### Test the CI/CD Pipeline

1. **Create a test tag:**
   ```bash
   git tag v0.1.0-test
   git push origin v0.1.0-test
   ```

2. **Monitor the build:**
   - Go to GitHub Actions tab
   - Watch the build process
   - Check for any signing errors

3. **Verify the signed artifacts:**
   - Download the artifacts from the GitHub Actions run
   - Check signatures locally:
     ```powershell
     Get-AuthenticodeSignature -FilePath "PokePoke.exe"
     Get-AuthenticodeSignature -FilePath "PokePokeInstaller-0.1.0.exe"
     ```

### SmartScreen Testing

1. **Download signed installer on a clean machine**
2. **Run the installer**
3. **Verify no SmartScreen warnings appear**
4. **Check that installation proceeds without security blocks**

## Step 6: Production Considerations

### Certificate Profile Management

- **Monitor certificate expiration** - Set up alerts in Azure
- **Rotate service principals** - Regularly rotate client secrets
- **Audit signing operations** - Review Azure activity logs

### Cost Management

- **Per-signature pricing** - Monitor usage in Azure Cost Management
- **Optimize build frequency** - Only sign releases, not all builds
- **Use caching** - Cache unsigned builds and only sign when needed

### Security Best Practices

- **Least privilege** - Service principal should only have signing permissions
- **Environment separation** - Use different profiles for dev/staging/prod
- **Secret rotation** - Rotate client secrets regularly (every 12-24 months)
- **Audit logging** - Enable and monitor Azure audit logs

### Troubleshooting

**Common Issues:**

1. **"Certificate profile not found"**
   - Verify profile name matches exactly (case-sensitive)
   - Ensure profile is in "Active" state
   - Check service principal has correct permissions

2. **"Authentication failed"**
   - Verify client ID, secret, and tenant ID are correct
   - Check service principal hasn't expired
   - Ensure correct Azure endpoints

3. **"Profile validation pending"**
   - Wait for identity validation to complete
   - Can take 1-5 business days for public trust certificates
   - Monitor email for validation requests

4. **"Signing operation failed"**
   - Check network connectivity from build agent
   - Verify AzureSignTool is installed and updated
   - Check Azure service health status

### Monitoring and Alerts

Set up monitoring for:
- **Certificate profile expiration**
- **Service principal secret expiration**  
- **Failed signing operations**
- **Azure Trusted Signing service health**

## Alternative: GitHub Actions Marketplace Action

Consider using community-maintained GitHub Actions for Azure Trusted Signing:

```yaml
- name: Sign with Azure Trusted Signing
  uses: azure/trusted-signing-action@v0.3.16
  with:
    endpoint: ${{ secrets.AZURE_SIGNING_ENDPOINT }}
    account-name: ${{ secrets.AZURE_SIGNING_ACCOUNT }}
    certificate-profile-name: ${{ secrets.AZURE_SIGNING_PROFILE }}
    files-folder: 'dist'
    files-folder-filter: 'exe'
    file-digest: sha256
    timestamp-rfc3161: http://timestamp.sectigo.com
    timestamp-digest: sha256
  env:
    AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
    AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
    AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
```

---

This completes the Azure Trusted Signing setup. The next step would be to integrate these configurations into your existing CI/CD pipeline and test the complete flow from code commit to signed release artifacts.