# Execute the actual controller functions with fake HTTP/Docker. No deployment.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { throw 'Tests require FullLanguage PowerShell' }
$tokens = $null; $errors = $null
$path = Join-Path $PSScriptRoot '../scripts/local-cd/deploy.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($fn in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    Invoke-Expression $fn.Extent.Text
}
function Check($Value, $Message) { if (!$Value) { throw $Message } }
function Write-Event($Name, $Fields) { $script:events.Add($Name) }
function Start-Sleep { param($Seconds, $Milliseconds) $script:sleeps++ }
function Get-Container { return $script:container }
function Get-Content { return '{"token":"test","sentinel_name":"memos/test","sentinel_content":"persisted"}' }
function Invoke-WebRequest {
    param($Uri, [switch]$UseBasicParsing, $TimeoutSec)
    if ($Uri -like '*/healthz') {
        $script:healthCalls++
        if ($script:healthCalls -le $script:initialFailures) { throw 'Starting' }
        return @{ StatusCode = 200; Content = 'Service ready.' }
    }
    if ($Uri -like '*.js') { return @{ StatusCode = 200; Content = 'js'; Headers = @{ 'Content-Type' = 'application/javascript' } } }
    return @{ Content = '<div id="root"></div><script src="/app.js"></script>' }
}
function Invoke-RestMethod {
    param($Uri, $Headers, $TimeoutSec)
    if ($Uri -like '*/profile') { return @{ commit = $Commit; version = 'version'; instanceUrl = 'http://127.0.0.1:5542' } }
    $script:sentinelCalls++
    Check ($Headers.Authorization -eq 'Bearer test') 'Sentinel lost authentication'
    # Would heal on a second call: the controller must never make that call.
    if ($script:failAcceptance -and $script:sentinelCalls -eq 1) { throw 'Injected memo failure' }
    return @{ content = 'persisted' }
}
function Invoke-Native {
    param($Program, $Arguments)
    if ($Arguments[-1] -eq 'activate') { $script:events.Add('fault_activation'); return }
    $script:restartSeen = $env:MEMOS_RESTART_POLICY
}
function Reset-Mocks {
    $script:events = [Collections.Generic.List[string]]::new()
    $script:sleeps = 0; $script:healthCalls = 0; $script:sentinelCalls = 0
    $script:initialFailures = 0; $script:failAcceptance = $false
    $script:container = @{ State = @{ Running = $true }; Image = 'image'; Id = 'candidate'; RestartCount = 0; HostConfig = @{ RestartPolicy = @{ Name = 'no' } } }
}
$Experiment = $true; $FrozenRelease = 'v2'; $StartupTimeoutSeconds = 180
$Commit = 'candidate-sha'; $StateDirectory = 'unused'; $ports = @(5541, 5542)
$projects = @('staging', 'production'); $dataSuffix = 'data'; $composeFile = 'unused'
$savedFixture = $env:MEMOS_FIXTURE_DIRECTORY
try {
    $env:MEMOS_FIXTURE_DIRECTORY = ''
    Reset-Mocks
    $initialFailures = 1
    Assert-Deployment 1 image version
    Check ($sentinelCalls -eq 1 -and $sleeps -eq 1 -and $healthCalls -eq 3) 'Healthy startup/once-only acceptance failed'
    Check (($events -join ',') -eq 'startup_start,startup_ready,health_observation') 'Wrong gate order'
    Write-Host 'PASS healthy startup then once-only authenticated acceptance'

    Reset-Mocks
    $failAcceptance = $true
    $failed = $false
    try { Assert-Deployment 1 image version } catch { $failed = $_.Exception.Message -eq 'Injected memo failure' }
    Check ($failed -and $sentinelCalls -eq 1 -and $sleeps -eq 0) 'Acceptance failure was retried or hidden'
    Write-Host 'PASS acceptance failure remains terminal even if next request would pass'

    Reset-Mocks
    $env:MEMOS_FIXTURE_DIRECTORY = 'mock-fixture'
    Assert-Deployment 1 image version
    Check (($events -join ',') -eq 'startup_start,startup_ready,fault_activation,health_observation') 'Fault must activate after startup, before acceptance'
    Write-Host 'PASS explicit startup/activation/acceptance ordering'

    foreach ($bad in @('restart', 'exit', 'image', 'policy')) {
        Reset-Mocks
        switch ($bad) {
            restart { $container.RestartCount = 1 }
            exit { $container.State.Running = $false }
            image { $container.Image = 'foreign' }
            policy { $container.HostConfig.RestartPolicy.Name = 'unless-stopped' }
        }
        $failed = $false
        try { Assert-Deployment 1 image version } catch { $failed = $true }
        Check ($failed -and $healthCalls -eq 0 -and $sentinelCalls -eq 0 -and $sleeps -eq 0) "Unsafe candidate retried: $bad"
    }
    Write-Host 'PASS exit/restart/image/restart-policy failures do not wait for recovery'

    Invoke-Compose 1 @('up', '--detach', '--no-build', '--pull', 'never', 'memos')
    Check ($restartSeen -eq 'no') 'Measured deployment selected automatic restart'
    $Experiment = $false
    Invoke-Compose 1 @('config')
    Check ($restartSeen -eq 'unless-stopped') 'Unrelated local policy changed'
    Write-Host 'PASS measured restart disabled, unrelated local default retained'

    # Execute the real post-terminal try/catch, with failing diagnostics.
    $terminalTry = @($ast.FindAll({ param($n)
        $n -is [Management.Automation.Language.TryStatementAst] -and
        $n.Extent.Text -match "^try\s*\{\s*Write-Event 'pipeline_end'"
    }, $true))
    Check ($terminalTry.Count -eq 1) 'Missing guarded terminal diagnostics'
    function Save-Diagnostics { throw 'Simulated diagnostic disk error' }
    $record = @{ status = 'accepted' }
    Invoke-Expression $terminalTry[0].Extent.Text
    Check ($record.status -eq 'accepted') 'Diagnostics rewrote controller outcome'
    Write-Host 'PASS diagnostic failure preserves accepted outcome'
} finally { $env:MEMOS_FIXTURE_DIRECTORY = $savedFixture }
Write-Host '6 deployment policy checks passed (including four fatal startup cases)'

