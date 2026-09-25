# Operator helper only; never invoked by the frozen deployment controller.
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Run experiment/setup.ps1 first' }
& $python (Join-Path $PSScriptRoot 'trial.py') @args
exit $LASTEXITCODE
