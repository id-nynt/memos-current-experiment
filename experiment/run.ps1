[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Run experiment/setup.ps1 first' }
& $python (Join-Path $PSScriptRoot 'manage.py') @Arguments
exit $LASTEXITCODE
