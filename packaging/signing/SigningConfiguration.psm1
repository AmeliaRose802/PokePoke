#Requires -Version 5.1

<#
.SYNOPSIS
    Configuration management for PokePoke code signing.

.DESCRIPTION
    Handles loading and merging code signing configuration from multiple sources:
    - Default configuration
    - YAML configuration file
    - Environment variables
    - Command line parameters

.AUTHOR
    Amelia Payne

.VERSION
    1.0.0
#>

# Check for PowerShell-Yaml module
$yamlModuleAvailable = $false
try {
    Import-Module powershell-yaml -ErrorAction Stop
    $yamlModuleAvailable = $true
} catch {
    Write-Warning "PowerShell-Yaml module not available. Configuration will use defaults and environment variables only."
    Write-Warning "To install: Install-Module powershell-yaml -Scope CurrentUser"
}

#region Configuration Loading

<#
.SYNOPSIS
    Loads code signing configuration from multiple sources.

.DESCRIPTION
    Merges configuration from:
    1. Built-in defaults
    2. YAML configuration file (if available)
    3. Environment variables
    4. Command line parameters (highest priority)

.PARAMETER ConfigFile
    Path to YAML configuration file. Defaults to 'signing-config.yml' in project root.

.PARAMETER Environment
    Environment name (development, ci, production). Used to select environment-specific settings.

.PARAMETER Parameters
    Hashtable of command line parameters to override configuration.

.OUTPUTS
    PSCustomObject with merged configuration.
#>
function Get-SigningConfiguration {
    [CmdletBinding()]
    param(
        [string]$ConfigFile,
        
        [string]$Environment = 'development',
        
        [hashtable]$Parameters = @{}
    )
    
    # Start with default configuration
    $config = Get-DefaultSigningConfiguration
    
    # Try to find and load YAML configuration file
    if (-not $ConfigFile) {
        # Look for config file in common locations
        $projectRoot = Get-ProjectRoot
        $possiblePaths = @(
            (Join-Path $projectRoot "signing-config.yml"),
            (Join-Path $projectRoot "packaging\signing\signing-config.yml"),
            (Join-Path $projectRoot ".pokepoke\signing-config.yml")
        )
        
        foreach ($path in $possiblePaths) {
            if (Test-Path $path) {
                $ConfigFile = $path
                break
            }
        }
    }
    
    # Load YAML configuration if available
    if ($ConfigFile -and (Test-Path $ConfigFile) -and $yamlModuleAvailable) {
        Write-Verbose "Loading configuration from: $ConfigFile"
        try {
            $yamlConfig = Get-Content $ConfigFile -Raw | ConvertFrom-Yaml
            $config = Merge-Configuration $config $yamlConfig
            Write-Verbose "✓ YAML configuration loaded"
        } catch {
            Write-Warning "Failed to load YAML configuration from $ConfigFile`: $($_.Exception.Message)"
        }
    }
    
    # Apply environment-specific settings
    if ($config.environments -and $config.environments.$Environment) {
        Write-Verbose "Applying environment settings for: $Environment"
        $envConfig = @{ signing = $config.environments.$Environment }
        $config = Merge-Configuration $config $envConfig
    }
    
    # Apply environment variables
    $config = Apply-EnvironmentVariables $config
    
    # Apply command line parameters (highest priority)
    if ($Parameters.Count -gt 0) {
        Write-Verbose "Applying command line parameter overrides"
        $config = Apply-ParameterOverrides $config $Parameters
    }
    
    # Validate and normalize configuration
    $config = Resolve-ConfigurationPaths $config
    
    return [PSCustomObject]$config
}

function Get-DefaultSigningConfiguration {
    return @{
        signing = @{
            enabled = $true
            certificate_source = 'Auto'
            description = 'PokePoke - Autonomous Beads + Copilot CLI Orchestrator'
            url = 'https://github.com/AmeliaRose802/PokePoke'
            timestamp_server = 'http://timestamp.sectigo.com'
            timestamp_servers_fallback = @(
                'http://timestamp.globalsign.com/scripts/timstamp.dll',
                'http://timestamp.comodoca.com',
                'http://time.certum.pl'
            )
        }
        certificates = @{
            file = @{
                path = 'certificates/code-signing.pfx'
            }
            store = @{
                thumbprint = ''
                subject_pattern = 'PokePoke'
                store_location = 'CurrentUser'
            }
            azure = @{
                endpoint = ''
                account_name = ''
                profile_name = ''
            }
            self_signed = @{
                subject_name = 'PokePoke Development'
                validity_years = 5
                install_as_trusted = $true
            }
        }
        build = @{
            sign_executable = $true
            sign_installer = $true
            fail_on_signing_error = $false
            verify_signatures = $true
        }
        environment_variables = @{
            cert_password = 'CERT_PASSWORD'
            azure_endpoint = 'AZURE_TRUSTED_SIGNING_ENDPOINT'
            azure_account = 'AZURE_TRUSTED_SIGNING_ACCOUNT_NAME'
            azure_profile = 'AZURE_TRUSTED_SIGNING_PROFILE_NAME'
            cert_source_override = 'POKEPOKE_CERT_SOURCE'
            skip_signing = 'POKEPOKE_SKIP_SIGNING'
        }
        logging = @{
            level = 'Normal'
            log_file = 'build-logs/signing.log'
            include_sensitive = $false
        }
    }
}

function Merge-Configuration {
    param($base, $override)
    
    $result = $base.Clone()
    
    foreach ($key in $override.Keys) {
        if ($result.ContainsKey($key) -and $result[$key] -is [hashtable] -and $override[$key] -is [hashtable]) {
            # Recursively merge hashtables
            $result[$key] = Merge-Configuration $result[$key] $override[$key]
        } else {
            # Override value
            $result[$key] = $override[$key]
        }
    }
    
    return $result
}

function Apply-EnvironmentVariables {
    param($config)
    
    $envVars = $config.environment_variables
    
    # Skip signing if environment variable is set
    if ($envVars.skip_signing -and $env:($envVars.skip_signing)) {
        $config.signing.enabled = $false
    }
    
    # Certificate source override
    if ($envVars.cert_source_override -and $env:($envVars.cert_source_override)) {
        $config.signing.certificate_source = $env:($envVars.cert_source_override)
    }
    
    # Azure Trusted Signing settings
    if ($envVars.azure_endpoint -and $env:($envVars.azure_endpoint)) {
        $config.certificates.azure.endpoint = $env:($envVars.azure_endpoint)
    }
    
    if ($envVars.azure_account -and $env:($envVars.azure_account)) {
        $config.certificates.azure.account_name = $env:($envVars.azure_account)
    }
    
    if ($envVars.azure_profile -and $env:($envVars.azure_profile)) {
        $config.certificates.azure.profile_name = $env:($envVars.azure_profile)
    }
    
    return $config
}

function Apply-ParameterOverrides {
    param($config, $parameters)
    
    if ($parameters.ContainsKey('SkipSigning') -and $parameters.SkipSigning) {
        $config.signing.enabled = $false
    }
    
    if ($parameters.ContainsKey('CertificateSource')) {
        $config.signing.certificate_source = $parameters.CertificateSource
    }
    
    if ($parameters.ContainsKey('CertificatePath')) {
        $config.certificates.file.path = $parameters.CertificatePath
    }
    
    if ($parameters.ContainsKey('CertificateThumbprint')) {
        $config.certificates.store.thumbprint = $parameters.CertificateThumbprint
    }
    
    if ($parameters.ContainsKey('Verbose') -and $parameters.Verbose) {
        $config.logging.level = 'Verbose'
    }
    
    return $config
}

function Resolve-ConfigurationPaths {
    param($config)
    
    # Resolve relative paths to absolute paths
    $projectRoot = Get-ProjectRoot
    
    # Certificate file path
    if ($config.certificates.file.path -and -not [System.IO.Path]::IsPathRooted($config.certificates.file.path)) {
        $config.certificates.file.path = Join-Path $projectRoot $config.certificates.file.path
    }
    
    # Log file path
    if ($config.logging.log_file -and -not [System.IO.Path]::IsPathRooted($config.logging.log_file)) {
        $config.logging.log_file = Join-Path $projectRoot $config.logging.log_file
        
        # Ensure log directory exists
        $logDir = Split-Path $config.logging.log_file -Parent
        if (-not (Test-Path $logDir)) {
            New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        }
    }
    
    return $config
}

function Get-ProjectRoot {
    # Try to find project root by looking for common files
    $currentDir = Get-Location
    $searchPaths = @($currentDir.Path)
    
    # Add parent directories to search
    $parent = $currentDir.Parent
    while ($parent) {
        $searchPaths += $parent.FullName
        $parent = $parent.Parent
    }
    
    # Look for project indicators
    $indicators = @('pyproject.toml', 'pokepoke.spec', '.git', 'src')
    
    foreach ($path in $searchPaths) {
        foreach ($indicator in $indicators) {
            if (Test-Path (Join-Path $path $indicator)) {
                return $path
            }
        }
    }
    
    # Fallback to current directory
    return $currentDir.Path
}

#endregion

#region Azure Trusted Signing

<#
.SYNOPSIS
    Installs or updates Azure SignTool for Azure Trusted Signing.

.DESCRIPTION
    Ensures AzureSignTool is available for Azure Trusted Signing operations.
    Installs as a .NET global tool if not already present.

.OUTPUTS
    Boolean indicating success or failure.
#>
function Install-AzureSignTool {
    [CmdletBinding()]
    param()
    
    Write-Verbose "Checking for AzureSignTool installation..."
    
    # Check if already installed
    try {
        $result = & dotnet tool list --global 2>$null | Select-String "azuresigntool"
        if ($result) {
            Write-Verbose "AzureSignTool is already installed as a global tool"
            return $true
        }
    } catch {
        Write-Verbose "Error checking dotnet global tools: $($_.Exception.Message)"
    }
    
    # Try to install
    Write-Host "Installing AzureSignTool as .NET global tool..." -ForegroundColor Yellow
    
    try {
        $output = & dotnet tool install --global AzureSignTool 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ AzureSignTool installed successfully" -ForegroundColor Green
            return $true
        } else {
            Write-Warning "Failed to install AzureSignTool: $output"
            return $false
        }
    } catch {
        Write-Warning "Error installing AzureSignTool: $($_.Exception.Message)"
        return $false
    }
}

<#
.SYNOPSIS
    Tests Azure Trusted Signing authentication and configuration.

.DESCRIPTION
    Verifies that Azure Trusted Signing is properly configured and authenticated.

.PARAMETER Config
    Signing configuration object.

.OUTPUTS
    Boolean indicating whether Azure Trusted Signing is ready to use.
#>
function Test-AzureTrustedSigning {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [PSCustomObject]$Config
    )
    
    $azureConfig = $Config.certificates.azure
    
    # Check required configuration
    if (-not $azureConfig.endpoint) {
        Write-Verbose "Azure endpoint not configured"
        return $false
    }
    
    if (-not $azureConfig.account_name) {
        Write-Verbose "Azure account name not configured"
        return $false
    }
    
    if (-not $azureConfig.profile_name) {
        Write-Verbose "Azure profile name not configured"
        return $false
    }
    
    # Check if AzureSignTool is available
    if (-not (Get-Command AzureSignTool -ErrorAction SilentlyContinue)) {
        Write-Verbose "AzureSignTool not found in PATH"
        return $false
    }
    
    Write-Verbose "Azure Trusted Signing configuration appears valid"
    return $true
}

<#
.SYNOPSIS
    Gets Azure Trusted Signing certificate information for use with the signing module.

.DESCRIPTION
    Creates a certificate info object compatible with the CodeSigning module for Azure Trusted Signing.

.PARAMETER Config
    Signing configuration object.

.OUTPUTS
    Hashtable with Azure Trusted Signing certificate information.
#>
function Get-AzureTrustedSigningCertificate {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [PSCustomObject]$Config
    )
    
    if (-not (Test-AzureTrustedSigning $Config)) {
        return $null
    }
    
    $azureConfig = $Config.certificates.azure
    
    return @{
        Source = 'Azure'
        Endpoint = $azureConfig.endpoint
        AccountName = $azureConfig.account_name
        ProfileName = $azureConfig.profile_name
        SigningMethod = 'AzureSignTool'
        IsValid = $true
    }
}

#endregion

#region Logging

<#
.SYNOPSIS
    Writes a log message to the configured log file.

.DESCRIPTION
    Appends log messages to the signing log file if logging is enabled.

.PARAMETER Message
    The message to log.

.PARAMETER Level
    Log level: Info, Warning, Error.

.PARAMETER Config
    Signing configuration object.
#>
function Write-SigningLog {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Message,
        
        [ValidateSet('Info', 'Warning', 'Error')]
        [string]$Level = 'Info',
        
        [PSCustomObject]$Config
    )
    
    if (-not $Config -or -not $Config.logging.log_file) {
        return
    }
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] [$Level] $Message"
    
    try {
        Add-Content -Path $Config.logging.log_file -Value $logEntry -Encoding UTF8
    } catch {
        Write-Verbose "Failed to write to log file: $($_.Exception.Message)"
    }
}

#endregion

# Export public functions
Export-ModuleMember -Function @(
    'Get-SigningConfiguration',
    'Install-AzureSignTool',
    'Test-AzureTrustedSigning',
    'Get-AzureTrustedSigningCertificate',
    'Write-SigningLog'
)