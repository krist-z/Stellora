$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$cli = Join-Path $scriptDir "_runtime\workflow_cli.py"
& python $cli @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
