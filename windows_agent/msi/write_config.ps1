# write_config.ps1 — Called by MSI installer to write config.json
# Usage: powershell.exe -ExecutionPolicy Bypass -File write_config.ps1 -OrgToken "ODT-XKCD-9F3A"

param(
    [Parameter(Mandatory=$true)]
    [string]$OrgToken,

    [string]$ApiBase = "https://timetracker-api-k375.onrender.com/api"
)

$configDir = Join-Path $env:APPDATA "TimeTracker"
if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

# If config already exists (e.g., reinstall), merge rather than overwrite
$configPath = Join-Path $configDir "config.json"
$config = @{}

if (Test-Path $configPath) {
    try {
        $existing = Get-Content $configPath -Raw | ConvertFrom-Json
        # Preserve existing api_key if present (device already paired)
        foreach ($prop in $existing.PSObject.Properties) {
            $config[$prop.Name] = $prop.Value
        }
    } catch {
        # Corrupted config, start fresh
    }
}

# Set/overwrite org token and api base
$config["org_token"] = $OrgToken
$config["api_base"] = $ApiBase

# Write config
$config | ConvertTo-Json -Depth 3 | Set-Content -Path $configPath -Encoding UTF8

Write-Host "[INSTALLER] Config written to $configPath"
Write-Host "[INSTALLER]   org_token = $OrgToken"
Write-Host "[INSTALLER]   api_base  = $ApiBase"