$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "..\reaper\mcp_bridge.py"
$destination = "C:\Users\Usuario\AppData\Roaming\REAPER\Scripts\mcp_bridge.py"

Write-Host "Validating REAPER bridge syntax..."

uv run python -m py_compile $source

if ($LASTEXITCODE -ne 0) {
    Write-Error "Syntax validation failed. Bridge was NOT deployed."
    exit 1
}

Write-Host "Syntax OK. Deploying REAPER bridge..."

Copy-Item `
    -Path $source `
    -Destination $destination `
    -Force

if ($LASTEXITCODE -ne 0) {
    Write-Error "Deployment failed."
    exit 1
}

Write-Host "REAPER bridge deployed successfully to:"
Write-Host $destination
