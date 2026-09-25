# Machine provisioning only. No deployments, fault activation, or policy changes.
[CmdletBinding()]
param(
    [string]$Python,
    [switch]$InstallRunner,
    [string]$RunnerDirectory = (Join-Path $env:USERPROFILE 'actions-runner-memos-current')
)
$ErrorActionPreference = 'Stop'
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { throw 'FullLanguage PowerShell required' }
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$config = Get-Content (Join-Path $PSScriptRoot 'config.json') -Raw | ConvertFrom-Json
foreach ($program in @('git', 'docker', 'gh', 'tar')) { Get-Command $program -ErrorAction Stop | Out-Null }
if (!$Python) {
    $Python = (& py -3 -c 'import sys; print(sys.executable)').Trim()
    if ($LASTEXITCODE) { throw 'Install Python 3.11+ or pass -Python with its executable path' }
}
& $Python -c 'import sys; assert sys.version_info >= (3, 11)'
if ($LASTEXITCODE) { throw 'Python 3.11+ required' }
$venvPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE) { throw 'Could not create repository-owned Python environment' }
}
$state = Join-Path $env:LOCALAPPDATA $config.owner
New-Item -ItemType Directory -Path $state -Force | Out-Null
# Secrets and SQLite backups stay private to this Windows account and SYSTEM.
$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $state /inheritance:r /grant:r "${account}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE) { throw 'Could not restrict private state permissions' }
if ($InstallRunner) {
    $runnerConfig = Join-Path $RunnerDirectory '.runner'
    if (!(Test-Path -LiteralPath (Join-Path $RunnerDirectory 'config.cmd'))) {
        if (Test-Path -LiteralPath $RunnerDirectory) { throw 'Existing incomplete runner directory; inspect before retrying' }
        $release = gh api repos/actions/runner/releases/latest | ConvertFrom-Json
        if ($LASTEXITCODE) { throw 'Runner release query failed' }
        $asset = $release.assets | Where-Object { $_.name -match '^actions-runner-win-x64-.*\.zip$' }
        if (!$asset.digest -or !$asset.digest.StartsWith('sha256:')) { throw 'Official runner checksum missing' }
        New-Item -ItemType Directory -Path $RunnerDirectory | Out-Null
        $archive = Join-Path $env:TEMP $asset.name
        Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -OutFile $archive
        if ((Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $asset.digest.Substring(7)) { throw 'Runner checksum mismatch' }
        Expand-Archive -LiteralPath $archive -DestinationPath $RunnerDirectory
    }
    if (Test-Path -LiteralPath $runnerConfig) {
        $existing = Get-Content -LiteralPath $runnerConfig -Raw | ConvertFrom-Json
        if ($existing.gitHubUrl.TrimEnd('/') -ne "https://github.com/$($config.repository)" -or $existing.agentName -ne $config.runner_name) {
            throw 'Refusing to repurpose a runner registered elsewhere'
        }
    } else {
        $registration = gh api --method POST "repos/$($config.repository)/actions/runners/registration-token" | ConvertFrom-Json
        if ($LASTEXITCODE -or !$registration.token) { throw 'Runner registration token unavailable' }
        Push-Location $RunnerDirectory
        try {
            & ./config.cmd --unattended --url "https://github.com/$($config.repository)" --token $registration.token --name $config.runner_name --labels $config.runner_label --work _work
            if ($LASTEXITCODE) { throw 'Runner configuration failed' }
        } finally { $registration = $null; Pop-Location }
    }
    $runners = gh api "repos/$($config.repository)/actions/runners" | ConvertFrom-Json
    if ($LASTEXITCODE) { throw 'Could not check runner activity' }
    if (@($runners.runners | Where-Object { $_.name -eq $config.runner_name -and $_.busy }).Count) { throw 'Runner is busy; rerun setup after its job ends' }
    $taskName = 'MemosCurrentActionsRunner'
    $old = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($old) {
        if ($old.Actions.Arguments -notlike "*$RunnerDirectory*") { throw 'Scheduled task belongs to a different installation' }
        Stop-ScheduledTask -TaskName $taskName
        Start-Sleep -Seconds 3
    }
    $launcher = Join-Path $RunnerDirectory 'Start-MemosRunner.ps1'
    $pythonDir = Split-Path $venvPython
    # Escape literal single quotes in Windows paths before writing PowerShell source.
    $pathLiteral = ($pythonDir + ';' + $env:PATH).Replace("'", "''")
    @"
`$ErrorActionPreference = 'Stop'
Set-Location `$PSScriptRoot
`$env:PATH = '$pathLiteral'
& ./run.cmd *> (Join-Path `$PSScriptRoot 'runner-console.log')
exit `$LASTEXITCODE
"@ | Set-Content -LiteralPath $launcher -Encoding UTF8
    $action = New-ScheduledTaskAction -Execute (Join-Path $PSHOME 'powershell.exe') -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $launcher + '"') -WorkingDirectory $RunnerDirectory
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
    $principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
}
& $venvPython (Join-Path $PSScriptRoot 'manage.py') check
if ($LASTEXITCODE) { throw 'Prerequisites incomplete. Import the frozen image bundle if images are missing.' }
Write-Host 'Conventional environment configured. Private state:' $state
