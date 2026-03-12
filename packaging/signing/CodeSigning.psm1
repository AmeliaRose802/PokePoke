#Requires -Version 5.1

<#
.SYNOPSIS
    PowerShell module for code signing PokePoke executables and installers.

.DESCRIPTION
    Provides functions to sign Windows executables and installers using various certificate sources:
    - Self-signed certificates (development)
    - Azure Trusted Signing (CI/CD)
    - Traditional code signing certificates (EV or standard)

.AUTHOR
    Amelia Payne

.VERSION
    1.0.0
#>

# Module variables
$script:ModuleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:SignToolPath = $null
$script:AzureSignToolPath = $null

#region Certificate Detection and Validation

<#
.SYNOPSIS
    Finds and validates available code signing certificates.

.DESCRIPTION
    Searches for code signing certificates in various locations and validates their suitability for signing.

.PARAMETER CertificateSource
    Specifies the preferred certificate source: Auto, Store, File, Azure, or SelfSigned.

.PARAMETER CertificatePath
    Path to certificate file (.pfx) when using File source.

.PARAMETER CertificateThumbprint
    Thumbprint of certificate in certificate store when using Store source.

.OUTPUTS
    PSCustomObject with certificate information and signing parameters.
#>
function Find-CodeSigningCertificate {
    [CmdletBinding()]
    param(
        [ValidateSet('Auto', 'Store', 'File', 'Azure', 'SelfSigned')]
        [string]$CertificateSource = 'Auto',
        
        [string]$CertificatePath,
        
        [string]$CertificateThumbprint,
        
        [string]$SubjectName = "PokePoke Development"
    )
    
    Write-Verbose "Searching for code signing certificate (Source: $CertificateSource)"
    
    switch ($CertificateSource) {
        'Store' {
            return Find-CertificateInStore -Thumbprint $CertificateThumbprint -SubjectName $SubjectName
        }
        'File' {
            return Find-CertificateInFile -Path $CertificatePath
        }
        'Azure' {
            return Find-AzureTrustedSigningConfig
        }
        'SelfSigned' {
            return Find-SelfSignedCertificate -SubjectName $SubjectName
        }
        'Auto' {
            # Try in order of preference: Azure -> Store -> File -> SelfSigned
            $cert = Find-AzureTrustedSigningConfig
            if ($cert) { return $cert }
            
            $cert = Find-CertificateInStore -SubjectName $SubjectName
            if ($cert) { return $cert }
            
            if ($CertificatePath -and (Test-Path $CertificatePath)) {
                $cert = Find-CertificateInFile -Path $CertificatePath
                if ($cert) { return $cert }
            }
            
            $cert = Find-SelfSignedCertificate -SubjectName $SubjectName
            if ($cert) { return $cert }
            
            Write-Warning "No suitable code signing certificate found"
            return $null
        }
    }
}

function Find-CertificateInStore {
    param(
        [string]$Thumbprint,
        [string]$SubjectName
    )
    
    $stores = @('CurrentUser\My', 'LocalMachine\My')
    
    foreach ($storeLocation in $stores) {
        Write-Verbose "Searching certificate store: $storeLocation"
        
        try {
            $certs = Get-ChildItem "Cert:\$storeLocation" -CodeSigningCert -ErrorAction SilentlyContinue
            
            if ($Thumbprint) {
                $cert = $certs | Where-Object { $_.Thumbprint -eq $Thumbprint }
            } else {
                $cert = $certs | Where-Object { 
                    $_.Subject -like "*$SubjectName*" -and 
                    $_.NotAfter -gt (Get-Date) -and
                    $_.HasPrivateKey
                }
            }
            
            if ($cert) {
                Write-Verbose "Found certificate in $storeLocation`: $($cert.Subject)"
                return @{
                    Source = 'Store'
                    Certificate = $cert
                    Thumbprint = $cert.Thumbprint
                    Subject = $cert.Subject
                    Issuer = $cert.Issuer
                    NotAfter = $cert.NotAfter
                    SigningMethod = 'SignTool'
                    IsValid = $true
                }
            }
        } catch {
            Write-Verbose "Error searching store $storeLocation`: $($_.Exception.Message)"
        }
    }
    
    return $null
}

function Find-CertificateInFile {
    param([string]$Path)
    
    if (-not (Test-Path $Path)) {
        Write-Warning "Certificate file not found: $Path"
        return $null
    }
    
    try {
        # Try to load the certificate (this will prompt for password if encrypted)
        $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($Path)
        
        if (-not $cert.HasPrivateKey) {
            Write-Warning "Certificate file does not contain private key: $Path"
            return $null
        }
        
        if ($cert.NotAfter -lt (Get-Date)) {
            Write-Warning "Certificate has expired: $Path"
            return $null
        }
        
        # Check if it's suitable for code signing
        $keyUsage = $cert.Extensions | Where-Object { $_.Oid.Value -eq "2.5.29.15" }
        if ($keyUsage -and -not ($keyUsage.KeyUsages -band [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature)) {
            Write-Warning "Certificate is not suitable for code signing: $Path"
            return $null
        }
        
        Write-Verbose "Found valid certificate file: $Path"
        return @{
            Source = 'File'
            Certificate = $cert
            CertificatePath = $Path
            Thumbprint = $cert.Thumbprint
            Subject = $cert.Subject
            Issuer = $cert.Issuer
            NotAfter = $cert.NotAfter
            SigningMethod = 'SignTool'
            IsValid = $true
        }
    } catch {
        Write-Warning "Error loading certificate from file $Path`: $($_.Exception.Message)"
        return $null
    }
}

function Find-AzureTrustedSigningConfig {
    # Check for Azure Trusted Signing configuration
    $azSignTool = Get-AzureSignToolPath
    if (-not $azSignTool) {
        Write-Verbose "Azure SignTool not found"
        return $null
    }
    
    # Check for required environment variables or config
    $endpoint = $env:AZURE_TRUSTED_SIGNING_ENDPOINT
    $accountName = $env:AZURE_TRUSTED_SIGNING_ACCOUNT_NAME
    $profileName = $env:AZURE_TRUSTED_SIGNING_PROFILE_NAME
    
    if ($endpoint -and $accountName -and $profileName) {
        Write-Verbose "Found Azure Trusted Signing configuration"
        return @{
            Source = 'Azure'
            Endpoint = $endpoint
            AccountName = $accountName
            ProfileName = $profileName
            SigningMethod = 'AzureSignTool'
            IsValid = $true
        }
    }
    
    Write-Verbose "Azure Trusted Signing configuration not found"
    return $null
}

function Find-SelfSignedCertificate {
    param([string]$SubjectName)
    
    # Look for self-signed certificate with the specified subject name
    $cert = Get-ChildItem 'Cert:\CurrentUser\My' | 
           Where-Object { 
               $_.Subject -like "*$SubjectName*" -and 
               $_.Issuer -eq $_.Subject -and  # Self-signed
               $_.NotAfter -gt (Get-Date) -and
               $_.HasPrivateKey
           } | 
           Select-Object -First 1
    
    if ($cert) {
        Write-Verbose "Found self-signed certificate: $($cert.Subject)"
        return @{
            Source = 'SelfSigned'
            Certificate = $cert
            Thumbprint = $cert.Thumbprint
            Subject = $cert.Subject
            Issuer = $cert.Issuer
            NotAfter = $cert.NotAfter
            SigningMethod = 'SignTool'
            IsValid = $true
            IsSelfSigned = $true
        }
    }
    
    Write-Verbose "No self-signed certificate found with subject: $SubjectName"
    return $null
}

#endregion

#region Tool Path Discovery

function Get-SignToolPath {
    if ($script:SignToolPath) {
        return $script:SignToolPath
    }
    
    # Try common locations for signtool.exe
    $commonPaths = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe",
        "${env:ProgramFiles}\Windows Kits\10\bin\*\x64\signtool.exe",
        "${env:ProgramFiles(x86)}\Microsoft SDKs\Windows\*\bin\x64\signtool.exe",
        "${env:ProgramFiles}\Microsoft SDKs\Windows\*\bin\x64\signtool.exe"
    )
    
    foreach ($pattern in $commonPaths) {
        $paths = Get-ChildItem $pattern -ErrorAction SilentlyContinue | Sort-Object Name -Descending
        if ($paths) {
            $script:SignToolPath = $paths[0].FullName
            Write-Verbose "Found SignTool: $script:SignToolPath"
            return $script:SignToolPath
        }
    }
    
    # Try PATH
    $signTool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($signTool) {
        $script:SignToolPath = $signTool.Source
        Write-Verbose "Found SignTool in PATH: $script:SignToolPath"
        return $script:SignToolPath
    }
    
    Write-Error "SignTool.exe not found. Please install Windows SDK."
    return $null
}

function Get-AzureSignToolPath {
    if ($script:AzureSignToolPath) {
        return $script:AzureSignToolPath
    }
    
    # Try to find Azure SignTool
    $azSignTool = Get-Command AzureSignTool.exe -ErrorAction SilentlyContinue
    if ($azSignTool) {
        $script:AzureSignToolPath = $azSignTool.Source
        Write-Verbose "Found AzureSignTool: $script:AzureSignToolPath"
        return $script:AzureSignToolPath
    }
    
    # Try dotnet tool
    try {
        $result = & dotnet tool list --global 2>$null | Select-String "azuresigntool"
        if ($result) {
            $script:AzureSignToolPath = "AzureSignTool"
            Write-Verbose "Found AzureSignTool as dotnet global tool"
            return $script:AzureSignToolPath
        }
    } catch {
        # Ignore errors
    }
    
    Write-Verbose "AzureSignTool not found"
    return $null
}

#endregion

#region Code Signing Functions

<#
.SYNOPSIS
    Signs a Windows executable or installer.

.DESCRIPTION
    Signs the specified file using the best available certificate and signing method.

.PARAMETER FilePath
    Path to the file to sign (.exe, .msi, .dll, etc.).

.PARAMETER CertificateInfo
    Certificate information object from Find-CodeSigningCertificate.

.PARAMETER Description
    Description for the signature (optional).

.PARAMETER Url
    URL for more information about the signed file (optional).

.PARAMETER TimestampServer
    Timestamp server URL. Defaults to Sectigo timestamp server.

.PARAMETER Force
    Overwrite existing signature if present.

.OUTPUTS
    Boolean indicating success or failure.
#>
function Invoke-CodeSigning {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$FilePath,
        
        [Parameter(Mandatory)]
        [hashtable]$CertificateInfo,
        
        [string]$Description = "PokePoke - Autonomous Beads + Copilot SDK Orchestrator",
        
        [string]$Url = "https://github.com/AmeliaRose802/PokePoke",
        
        [string]$TimestampServer = "http://timestamp.sectigo.com",
        
        [switch]$Force
    )
    
    if (-not (Test-Path $FilePath)) {
        Write-Error "File not found: $FilePath"
        return $false
    }
    
    if (-not $CertificateInfo.IsValid) {
        Write-Error "Invalid certificate information provided"
        return $false
    }
    
    Write-Host "Signing file: $FilePath" -ForegroundColor Cyan
    Write-Host "Certificate Source: $($CertificateInfo.Source)" -ForegroundColor Yellow
    
    try {
        switch ($CertificateInfo.SigningMethod) {
            'SignTool' {
                return Invoke-SignToolSigning -FilePath $FilePath -CertificateInfo $CertificateInfo -Description $Description -Url $Url -TimestampServer $TimestampServer -Force:$Force
            }
            'AzureSignTool' {
                return Invoke-AzureSignToolSigning -FilePath $FilePath -CertificateInfo $CertificateInfo -Description $Description -Url $Url -TimestampServer $TimestampServer -Force:$Force
            }
            default {
                Write-Error "Unknown signing method: $($CertificateInfo.SigningMethod)"
                return $false
            }
        }
    } catch {
        Write-Error "Code signing failed: $($_.Exception.Message)"
        return $false
    }
}

function Invoke-SignToolSigning {
    param(
        [string]$FilePath,
        [hashtable]$CertificateInfo,
        [string]$Description,
        [string]$Url,
        [string]$TimestampServer,
        [switch]$Force
    )
    
    $signTool = Get-SignToolPath
    if (-not $signTool) {
        return $false
    }
    
    # Build signtool arguments
    $arguments = @('sign')
    
    if ($Force) {
        $arguments += '/f'  # Force overwrite
    }
    
    $arguments += '/fd', 'SHA256'  # File digest algorithm
    $arguments += '/td', 'SHA256'  # Timestamp digest algorithm
    
    if ($TimestampServer) {
        $arguments += '/tr', $TimestampServer
    }
    
    if ($Description) {
        $arguments += '/d', "`"$Description`""
    }
    
    if ($Url) {
        $arguments += '/du', "`"$Url`""
    }
    
    # Add certificate source-specific arguments
    if ($CertificateInfo.Source -eq 'Store') {
        $arguments += '/sha1', $CertificateInfo.Thumbprint
    } elseif ($CertificateInfo.Source -in @('File', 'SelfSigned')) {
        if ($CertificateInfo.CertificatePath) {
            $arguments += '/f', "`"$($CertificateInfo.CertificatePath)`""
            
            # Prompt for password if needed
            if (-not $env:CERT_PASSWORD) {
                $password = Read-Host "Enter certificate password (or set CERT_PASSWORD environment variable)" -AsSecureString
                if ($password.Length -gt 0) {
                    $arguments += '/p', [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($password))
                }
            } else {
                $arguments += '/p', $env:CERT_PASSWORD
            }
        } else {
            $arguments += '/sha1', $CertificateInfo.Thumbprint
        }
    }
    
    $arguments += "`"$FilePath`""
    
    Write-Verbose "Executing: $signTool $($arguments -join ' ')"
    
    # Execute signtool
    $process = Start-Process -FilePath $signTool -ArgumentList $arguments -Wait -PassThru -NoNewWindow -RedirectStandardOutput -RedirectStandardError
    
    if ($process.ExitCode -eq 0) {
        Write-Host "✓ Successfully signed: $FilePath" -ForegroundColor Green
        return $true
    } else {
        Write-Error "SignTool failed with exit code: $($process.ExitCode)"
        if ($process.StandardError) {
            Write-Error "Error output: $($process.StandardError)"
        }
        return $false
    }
}

function Invoke-AzureSignToolSigning {
    param(
        [string]$FilePath,
        [hashtable]$CertificateInfo,
        [string]$Description,
        [string]$Url,
        [string]$TimestampServer,
        [switch]$Force
    )
    
    $azSignTool = Get-AzureSignToolPath
    if (-not $azSignTool) {
        Write-Error "AzureSignTool not found"
        return $false
    }
    
    # Build AzureSignTool arguments
    $arguments = @(
        'sign',
        '--azure-key-vault-url', $CertificateInfo.Endpoint,
        '--azure-key-vault-certificate', $CertificateInfo.ProfileName,
        '--file-digest', 'sha256',
        '--timestamp-rfc3161', $TimestampServer,
        '--timestamp-digest', 'sha256'
    )
    
    if ($Description) {
        $arguments += '--description', "`"$Description`""
    }
    
    if ($Url) {
        $arguments += '--description-url', "`"$Url`""
    }
    
    $arguments += "`"$FilePath`""
    
    Write-Verbose "Executing: $azSignTool $($arguments -join ' ')"
    
    # Execute AzureSignTool
    if ($azSignTool -eq "AzureSignTool") {
        # Dotnet global tool
        $process = Start-Process -FilePath 'dotnet' -ArgumentList (@('AzureSignTool') + $arguments) -Wait -PassThru -NoNewWindow
    } else {
        # Standalone executable
        $process = Start-Process -FilePath $azSignTool -ArgumentList $arguments -Wait -PassThru -NoNewWindow
    }
    
    if ($process.ExitCode -eq 0) {
        Write-Host "✓ Successfully signed with Azure Trusted Signing: $FilePath" -ForegroundColor Green
        return $true
    } else {
        Write-Error "AzureSignTool failed with exit code: $($process.ExitCode)"
        return $false
    }
}

#endregion

#region Verification Functions

<#
.SYNOPSIS
    Verifies the digital signature of a file.

.DESCRIPTION
    Checks if a file is properly signed and validates the signature.

.PARAMETER FilePath
    Path to the file to verify.

.OUTPUTS
    PSCustomObject with verification results.
#>
function Test-CodeSignature {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$FilePath
    )
    
    if (-not (Test-Path $FilePath)) {
        Write-Error "File not found: $FilePath"
        return $null
    }
    
    try {
        $signature = Get-AuthenticodeSignature -FilePath $FilePath
        
        $result = @{
            FilePath = $FilePath
            Status = $signature.Status.ToString()
            SignerCertificate = $null
            TimeStamperCertificate = $null
            SignedTime = $null
            IsSigned = $false
            IsValid = $false
            IsTrusted = $false
            HashAlgorithm = $null
        }
        
        if ($signature.SignerCertificate) {
            $result.IsSigned = $true
            $result.SignerCertificate = @{
                Subject = $signature.SignerCertificate.Subject
                Issuer = $signature.SignerCertificate.Issuer
                Thumbprint = $signature.SignerCertificate.Thumbprint
                NotAfter = $signature.SignerCertificate.NotAfter
            }
            $result.HashAlgorithm = $signature.HashAlgorithm
        }
        
        if ($signature.TimeStamperCertificate) {
            $result.TimeStamperCertificate = @{
                Subject = $signature.TimeStamperCertificate.Subject
                Issuer = $signature.TimeStamperCertificate.Issuer
            }
        }
        
        $result.IsValid = $signature.Status -eq 'Valid'
        $result.IsTrusted = $signature.Status -in @('Valid', 'UnknownError')  # UnknownError might still be trusted
        
        # Try to get signing time
        if ($signature.SignerCertificate) {
            try {
                $signedCms = New-Object System.Security.Cryptography.Pkcs.SignedCms
                $signedCms.Decode((Get-Content $FilePath -Encoding Byte))
                $signerInfo = $signedCms.SignerInfos[0]
                
                foreach ($attr in $signerInfo.SignedAttributes) {
                    if ($attr.Oid.Value -eq "1.2.840.113549.1.9.5") { # signingTime
                        $result.SignedTime = [DateTime]$attr.Values[0]
                        break
                    }
                }
            } catch {
                # Ignore errors in getting signing time
            }
        }
        
        return [PSCustomObject]$result
        
    } catch {
        Write-Error "Error verifying signature: $($_.Exception.Message)"
        return $null
    }
}

#endregion

#region Utility Functions

<#
.SYNOPSIS
    Gets a summary of the code signing environment.

.DESCRIPTION
    Displays information about available certificates and signing tools.

.OUTPUTS
    PSCustomObject with environment information.
#>
function Get-CodeSigningEnvironment {
    [CmdletBinding()]
    param()
    
    $env = @{
        SignToolPath = Get-SignToolPath
        AzureSignToolPath = Get-AzureSignToolPath
        Certificates = @()
        AzureConfig = $null
    }
    
    # Find certificates
    Write-Host "Scanning for code signing certificates..." -ForegroundColor Cyan
    
    # Check certificate stores
    $storeCert = Find-CertificateInStore -SubjectName "PokePoke"
    if ($storeCert) {
        $env.Certificates += $storeCert
    }
    
    # Check for Azure configuration
    $azureConfig = Find-AzureTrustedSigningConfig
    if ($azureConfig) {
        $env.AzureConfig = $azureConfig
    }
    
    # Check for self-signed certificates
    $selfSignedCert = Find-SelfSignedCertificate -SubjectName "PokePoke Development"
    if ($selfSignedCert) {
        $env.Certificates += $selfSignedCert
    }
    
    return [PSCustomObject]$env
}

#endregion

# Export public functions
Export-ModuleMember -Function @(
    'Find-CodeSigningCertificate',
    'Invoke-CodeSigning',
    'Test-CodeSignature',
    'Get-CodeSigningEnvironment'
)