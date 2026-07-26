$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $scriptDir "Invoke-ProjectWorkflow.ps1") validate --root (Resolve-Path (Join-Path $scriptDir "..\..")) --strict @args
exit $LASTEXITCODE
