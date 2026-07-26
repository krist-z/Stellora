$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Cli = Join-Path $ScriptDir "_runtime/workflow_cli.py"
python $Cli @args
