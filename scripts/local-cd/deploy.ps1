# Windows PowerShell 5.1 and PowerShell 7. No automatic rollback.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$Commit,
    [string]$StateDirectory = $env:LOCAL_CD_STATE_DIRECTORY,
    [int]$StagingPort = $(if ($env:LOCAL_CD_STAGING_PORT) { [int]$env:LOCAL_CD_STAGING_PORT } else { 5231 }),
    [int]$ProductionPort = $(if ($env:LOCAL_CD_PRODUCTION_PORT) { [int]$env:LOCAL_CD_PRODUCTION_PORT } else { 5232 }),
    [ValidateSet('', 'v1', 'v2')][string]$FrozenRelease = '',
    [ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$TrialId = 'local',
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    throw 'Local CD requires FullLanguage PowerShell on the runner account'
}
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$composeFile = Join-Path $PSScriptRoot 'compose.yaml'
$projects = if ($FrozenRelease) { @('memos-aligned-current-staging', 'memos-aligned-current-production') } else { @('memos-local-staging', 'memos-local-production') }
if ($FrozenRelease -and !$PSBoundParameters.ContainsKey('StagingPort') -and !$env:LOCAL_CD_STAGING_PORT) { $StagingPort = 5441 }
if ($FrozenRelease -and !$PSBoundParameters.ContainsKey('ProductionPort') -and !$env:LOCAL_CD_PRODUCTION_PORT) { $ProductionPort = 5442 }
$ports = @($StagingPort, $ProductionPort)
$dataSuffix = 'data'
$nativeEvents = $null

function Write-Event {
    param([string]$Name, [hashtable]$Fields = @{})
    if (!$script:nativeEvents) { return }
    $entry = @{ timestamp = [DateTime]::UtcNow.ToString('o'); event = $Name; trial_id = $TrialId }
    foreach ($key in $Fields.Keys) { $entry[$key] = $Fields[$key] }
    $entry | ConvertTo-Json -Compress | Add-Content -LiteralPath $script:nativeEvents -Encoding UTF8
}

function Invoke-Native {
    param([string]$Program, [string[]]$Arguments)
    $result = & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit $LASTEXITCODE): $($Arguments -join ' ')" }
    return $result
}

function Invoke-Compose {
    param([int]$Environment, [string[]]$Arguments)
    $env:MEMOS_HOST_PORT = [string]$ports[$Environment]
    $env:MEMOS_DATA_VOLUME = "$($projects[$Environment])_$dataSuffix"
    Invoke-Native docker (@('compose', '--file', $composeFile, '--project-name', $projects[$Environment]) + $Arguments)
}

function Get-Container {
    param([int]$Environment)
    $ids = @(Invoke-Compose $Environment @('ps', '--all', '--quiet', 'memos'))
    if ($ids.Count -gt 1) { throw "Expected at most one container for $($projects[$Environment])" }
    if ($ids.Count -eq 0) { return $null }
    $items = (Invoke-Native docker @('inspect', $ids[0])) -join "`n" | ConvertFrom-Json
    return @($items)[0]
}

function Write-Json {
    param([string]$Path, $Value)
    # A same-directory rename keeps accepted.json from becoming a partial JSON file.
    $temporary = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Assert-Deployment {
    param([int]$Environment, [string]$Image, [string]$Version)
    $baseUrl = "http://127.0.0.1:$($ports[$Environment])"
    $deadline = [DateTime]::UtcNow.AddSeconds(180)
    $lastFailure = 'not ready'
    $round = 0
    do {
        $round++
        Write-Event 'health_observation' @{ environment = @('staging', 'production')[$Environment]; round = $round }
        try {
            $container = Get-Container $Environment
            if (!$container -or !$container.State.Running) { throw 'Container is not running' }
            if ($container.Image -ne $Image) { throw 'Container image ID does not match candidate' }
            $health = Invoke-WebRequest "$baseUrl/healthz" -UseBasicParsing -TimeoutSec 5
            if ($health.StatusCode -ne 200 -or $health.Content.Trim() -ne 'Service ready.') { throw 'Unexpected health response' }
            $profile = Invoke-RestMethod "$baseUrl/api/v1/instance/profile" -TimeoutSec 5
            if ($profile.commit -ne $Commit -or $profile.version -ne $Version -or $profile.instanceUrl -ne $baseUrl) { throw 'API release identity does not match candidate' }
            if ($FrozenRelease) {
                $targetName = @('staging', 'production')[$Environment]
                $credential = Get-Content (Join-Path $StateDirectory "credentials/$targetName/credential.json") -Raw | ConvertFrom-Json
                $sentinel = Invoke-RestMethod "$baseUrl/api/v1/$($credential.sentinel_name)" -Headers @{ Authorization = "Bearer $($credential.token)" } -TimeoutSec 5
                if ($sentinel.content -ne $credential.sentinel_content) { throw 'Seed sentinel persistence check failed' }
            }
            $page = Invoke-WebRequest "$baseUrl/" -UseBasicParsing -TimeoutSec 5
            if ($page.Content -notmatch 'id="root"') { throw 'Frontend root is missing' }
            $asset = [regex]::Match($page.Content, 'src="([^"\s]+\.js)"')
            if (!$asset.Success) { throw 'Frontend JavaScript asset is missing' }
            $assetUrl = [Uri]::new([Uri]"$baseUrl/", $asset.Groups[1].Value)
            if ($assetUrl.Authority -ne ([Uri]$baseUrl).Authority -or $assetUrl.Scheme -ne 'http') { throw 'Unexpected frontend asset origin' }
            $javascript = Invoke-WebRequest $assetUrl.AbsoluteUri -UseBasicParsing -TimeoutSec 5
            if ($javascript.StatusCode -ne 200 -or $javascript.Content.Length -eq 0 -or $javascript.Headers['Content-Type'] -notmatch 'javascript') {
                throw 'Frontend JavaScript was not served'
            }
            $after = Get-Container $Environment
            if (!$after.State.Running -or $after.Id -ne $container.Id -or $after.RestartCount -ne $container.RestartCount) {
                throw 'Container restarted during verification'
            }
            Write-Host "$($projects[$Environment]) verified at $baseUrl ($Commit, $Image)"
            return
        } catch {
            $lastFailure = $_.Exception.Message
            if ([DateTime]::UtcNow -ge $deadline) { break }
            Start-Sleep -Seconds 3
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Verification failed for $($projects[$Environment]): $lastFailure"
}

function Save-Diagnostics {
    foreach ($project in $projects) {
        # Diagnostics are best effort; never replace the original deployment error.
        try {
            $ids = @(Invoke-Native docker @('ps', '--all', '--quiet', '--filter', "label=com.docker.compose.project=$project"))
            if ($ids.Count -eq 0) { continue }
            foreach ($id in $ids) {
                $item = @(((Invoke-Native docker @('inspect', $id)) -join "`n" | ConvertFrom-Json))[0]
                Write-Json (Join-Path $reportDirectory "$project-status.json") @{
                    id = $item.Id; image = $item.Image; state = $item.State; restarts = $item.RestartCount
                }
                # Docker emits application logs on both streams.
                $savedPreference = $ErrorActionPreference
                try {
                    $ErrorActionPreference = 'Continue'
                    & docker logs --tail 200 $id 2>&1 | Out-File (Join-Path $reportDirectory "$project.log") -Encoding UTF8
                } finally { $ErrorActionPreference = $savedPreference }
            }
        } catch { Write-Warning "Could not collect all diagnostics for ${project}: $_" }
    }
}

if ($StagingPort -eq $ProductionPort -or $StagingPort -lt 1024 -or $ProductionPort -lt 1024 -or $StagingPort -gt 65535 -or $ProductionPort -gt 65535) {
    throw 'Choose distinct staging/production ports between 1024 and 65535'
}
if (!$StateDirectory) { $StateDirectory = Join-Path $env:USERPROFILE $(if ($FrozenRelease) { '.memos-aligned-current' } else { '.memos-local-cd' }) }
$StateDirectory = [IO.Path]::GetFullPath($StateDirectory)
if ($StateDirectory.TrimEnd('\', '/') -eq $repo.TrimEnd('\', '/') -or $StateDirectory.StartsWith($repo.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'StateDirectory must be outside the checkout (it holds production backups)'
}

Push-Location $repo
$deploymentLock = $null
try {
    $head = (Invoke-Native git @('rev-parse', 'HEAD')).Trim()
    $frozen = $null
    if ($FrozenRelease) {
        $manifest = Get-Content (Join-Path $PSScriptRoot 'frozen-releases.json') -Raw | ConvertFrom-Json
        $frozen = $manifest.releases.$FrozenRelease
        if ($frozen.application_sha -ne $Commit) { throw 'Release SHA differs from frozen contract' }
        $tree = (Invoke-Native git @('rev-parse', "$Commit`^{tree}")).Trim()
        if ($tree -ne $frozen.tree) { throw 'Frozen source tree mismatch' }
    } elseif ($head -ne $Commit) { throw "Checkout $head does not match requested commit $Commit" }
    # pnpm release replaces the tracked placeholder HTML as part of the build.
    if (@(Invoke-Native git @('diff', '--name-only', 'HEAD', '--', '.', ':(exclude)server/frontend/dist')).Count -gt 0) {
        throw 'Tracked source files have uncommitted changes'
    }
    $engine = (Invoke-Native docker @('version', '--format', '{{.Server.Os}}')).Trim()
    if ($engine -ne 'linux') { throw 'Docker must use the Linux-container engine' }
    Invoke-Native docker @('compose', 'version') | Write-Host
    Invoke-Native docker @('buildx', 'version') | Write-Host
    Get-Command tar -ErrorAction Stop | Out-Null
    # A syntactically valid placeholder is enough for preflight Compose inspection.
    $env:MEMOS_IMAGE = 'sha256:' + ('0' * 64)
    for ($i = 0; $i -lt 2; $i++) {
        Invoke-Compose $i @('config', '--quiet')
        $existing = Get-Container $i
        $volumeName = "$($projects[$i])_$dataSuffix"
        $volumes = @(Invoke-Native docker @('volume', 'ls', '--quiet', '--filter', "name=^${volumeName}$"))
        if ($volumes.Count -gt 0) {
            $volume = @(((Invoke-Native docker @('volume', 'inspect', $volumeName)) -join "`n" | ConvertFrom-Json))[0]
            if (!$volume.Labels -or $volume.Labels.'com.docker.compose.project' -ne $projects[$i]) { throw "Volume $volumeName is not owned by this Compose project" }
        }
        if ($existing) {
            $mounts = @($existing.Mounts | Where-Object { $_.Destination -eq '/var/opt/memos' -and $_.Type -eq 'volume' -and $_.Name -eq $volumeName })
            if ($mounts.Count -ne 1) { throw "Unexpected data mount for $($projects[$i]); refusing deployment" }
        }
        # If this project's running container owns the desired port, replacement is safe.
        $ownsPort = $false
        if ($existing -and ($existing.State.Running -or $existing.State.Restarting)) {
            # NetworkSettings.Ports can be empty during a restart loop; the
            # configured reservation still belongs to this managed container.
            $bindingProperty = $existing.HostConfig.PortBindings.PSObject.Properties['5230/tcp']
            if ($bindingProperty) {
                $ownsPort = @($bindingProperty.Value | Where-Object { $_.HostIp -eq '127.0.0.1' -and $_.HostPort -eq [string]$ports[$i] }).Count -eq 1
            }
        }
        if (!$ownsPort) {
            $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $ports[$i])
            try { $listener.Start() } finally { $listener.Stop() }
        }
    }
    if ($CheckOnly) { Write-Host 'Preflight passed'; return }

    New-Item -ItemType Directory -Path $StateDirectory -Force | Out-Null
    $deploymentLock = [IO.File]::Open((Join-Path $StateDirectory 'deployment.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $runKey = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
    $releaseDirectory = Join-Path $StateDirectory "releases/$runKey"
    New-Item -ItemType Directory -Path $releaseDirectory -Force | Out-Null
    $reportDirectory = $releaseDirectory
    if ($env:RUNNER_TEMP) {
        $reportKey = $runKey
        if ($env:GITHUB_RUN_ID -and $env:GITHUB_RUN_ATTEMPT) { $reportKey = "$($env:GITHUB_RUN_ID)-$($env:GITHUB_RUN_ATTEMPT)" }
        $reportDirectory = Join-Path $env:RUNNER_TEMP "memos-local-cd-report/$reportKey"
        New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
    }
    $acceptedPath = Join-Path $StateDirectory 'accepted.json'
    $previous = $null
    if (Test-Path -LiteralPath $acceptedPath) { $previous = Get-Content -LiteralPath $acceptedPath -Raw | ConvertFrom-Json }
    $version = "local-$Commit"
    $tag = "memos-local:$Commit-$runKey"
    $record = [ordered]@{
        status = 'started'; commit = $Commit; version = $version; image = $null; tag = $tag
        startedAt = [DateTime]::UtcNow.ToString('o'); acceptedAt = $null
        workflowRun = $env:GITHUB_RUN_ID; workflowAttempt = $env:GITHUB_RUN_ATTEMPT
        stagingPort = $StagingPort; productionPort = $ProductionPort
        previous = $previous; productionBackup = $null; previousImage = $null; error = $null
        control_sha = $head; trial_id = $TrialId; frozen_release = $FrozenRelease
    }
    $nativeEvents = Join-Path $releaseDirectory 'native-events.jsonl'
    if ($FrozenRelease -eq 'v2' -and (!$previous -or $previous.commit -ne $manifest.releases.v1.application_sha)) { throw 'Frozen v2 requires an accepted v1 baseline in this isolated state directory' }
    Write-Event 'pipeline_start'
    if ($env:LOCAL_CD_EVIDENCE_POINTER) { $releaseDirectory | Set-Content -LiteralPath $env:LOCAL_CD_EVIDENCE_POINTER -Encoding UTF8 }
    try {
        if ($frozen) {
            $image = $frozen.image_id
            $meta = @(((Invoke-Native docker @('image', 'inspect', $image)) -join "`n" | ConvertFrom-Json))[0]
            if ($meta.Id -ne $image -or $meta.Config.Labels.'experiment.release_sha' -ne $Commit) { throw 'Frozen image identity mismatch' }
            if ($frozen.version -ne $version) { throw 'Frozen VERSION mismatch' }
            $record.tag = $frozen.tag
        } else {
        if (!(Test-Path -LiteralPath (Join-Path $repo 'server/frontend/dist/index.html'))) { throw 'Run pnpm release in web before deployment' }
        Write-Host 'Building immutable candidate image'
        $imageFile = Join-Path $releaseDirectory 'image-id.txt'
        # Archive preserves Git's LF shell scripts even on core.autocrlf Windows
        # checkouts and excludes untracked files. Add only generated SPA assets.
        $contextDirectory = Join-Path $releaseDirectory 'build-context'
        $contextArchive = Join-Path $releaseDirectory 'source.tar'
        New-Item -ItemType Directory -Path $contextDirectory | Out-Null
        try {
            Invoke-Native git @('-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'archive', '--format=tar', "--output=$contextArchive", $Commit)
            Invoke-Native tar @('-xf', $contextArchive, '-C', $contextDirectory)
            if ([IO.File]::ReadAllText((Join-Path $contextDirectory 'scripts/entrypoint.sh')).Contains("`r")) {
                throw 'Archived Linux entrypoint must have LF line endings'
            }
            Copy-Item -Path (Join-Path $repo 'server/frontend/dist/*') -Destination (Join-Path $contextDirectory 'server/frontend/dist') -Recurse -Force
            Invoke-Native docker @('build', '--file', (Join-Path $contextDirectory 'scripts/Dockerfile'), '--build-arg', "VERSION=$version", '--build-arg', "COMMIT=$Commit", '--label', "org.opencontainers.image.revision=$Commit", '--tag', $tag, '--iidfile', $imageFile, $contextDirectory) | Write-Host
        } finally {
            $resolvedContext = [IO.Path]::GetFullPath($contextDirectory)
            $expectedContext = [IO.Path]::GetFullPath((Join-Path $releaseDirectory 'build-context'))
            if ($resolvedContext -ne $expectedContext -or !(Test-Path -LiteralPath (Join-Path $resolvedContext 'scripts/Dockerfile'))) {
                Write-Warning 'Build context retained for inspection'
            } else {
                Remove-Item -LiteralPath $resolvedContext -Recurse -Force
            }
            if (Test-Path -LiteralPath $contextArchive) { Remove-Item -LiteralPath $contextArchive -Force }
        }
        $image = (Get-Content -LiteralPath $imageFile -Raw).Trim()
        if ($image -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Build did not produce a valid immutable image ID' }
        }
        $record.image = $image
        $env:MEMOS_IMAGE = $image
        Write-Json (Join-Path $releaseDirectory 'release.json') $record

        Write-Host 'Deploying staging'
        Write-Event 'deployment_start' @{ environment = 'staging'; application_sha = $Commit; image_id = $image }
        Invoke-Compose 0 @('up', '--detach', '--no-build', '--pull', 'never', 'memos') | Write-Host
        Write-Event 'deployment_end' @{ environment = 'staging'; application_sha = $Commit; image_id = $image }
        Assert-Deployment 0 $image $version
        $record.status = 'staging-verified'

        $production = Get-Container 1
        if ($production) {
            $record.previousImage = $production.Image
            # Preserve the actual previous image even if no accepted record exists.
            Invoke-Native docker @('image', 'tag', $production.Image, "memos-local:previous-$runKey")
        }
        $productionVolume = "$($projects[1])_$dataSuffix"
        $hasData = @(Invoke-Native docker @('volume', 'ls', '--quiet', '--filter', "name=^${productionVolume}$")).Count -gt 0
        $record.status = 'production-backup'
        Write-Json (Join-Path $releaseDirectory 'release.json') $record
        if ($production) {
            Write-Host 'Stopping production for a consistent data backup'
            Invoke-Compose 1 @('stop', '--timeout', '30', 'memos') | Write-Host
        }
        if ($hasData) {
            $backupDirectory = Join-Path $releaseDirectory 'backup'
            New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
            Write-Host 'Backing up complete production data volume'
            Invoke-Native docker @('run', '--rm', '--network', 'none', '--user', '0', '--entrypoint', '/bin/sh', '--mount', "type=volume,source=$productionVolume,target=/source,readonly", '--mount', "type=bind,source=$backupDirectory,target=/backup", $image, '-ec', 'tar -czf /backup/data.tar.gz -C /source .; tar -tzf /backup/data.tar.gz > /dev/null') | Write-Host
            $backupPath = Join-Path $backupDirectory 'data.tar.gz'
            $record.productionBackup = @{ path = $backupPath; sha256 = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash }
        }
        # Persist the recovery information before starting a potentially migrating binary.
        $record.status = 'production-deploying'
        Write-Json (Join-Path $releaseDirectory 'release.json') $record
        Write-Host 'Deploying the same image to production'
        Write-Event 'deployment_start' @{ environment = 'production'; application_sha = $Commit; image_id = $image }
        Invoke-Compose 1 @('up', '--detach', '--no-build', '--pull', 'never', 'memos') | Write-Host
        Write-Event 'deployment_end' @{ environment = 'production'; application_sha = $Commit; image_id = $image }
        Assert-Deployment 1 $image $version
        $record.status = 'accepted'
        $record.acceptedAt = [DateTime]::UtcNow.ToString('o')
        Write-Json (Join-Path $releaseDirectory 'release.json') $record
        # Keep only the previous release identity, not a recursively growing history.
        Write-Json $acceptedPath @{
            commit = $Commit; image = $image; version = $version; releaseDirectory = $releaseDirectory
            acceptedAt = $record.acceptedAt; workflowRun = $env:GITHUB_RUN_ID
        }
        Write-Host "Accepted release: $Commit ($image)"
        if ($env:GITHUB_STEP_SUMMARY) {
            "Accepted local release: ``$Commit`` / ``$image``. Staging: http://127.0.0.1:$StagingPort ; production: http://127.0.0.1:$ProductionPort" | Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY
        }
    } catch {
        $record.status = 'failed'
        $record.error = $_.Exception.Message
        Write-Json (Join-Path $releaseDirectory 'release.json') $record
        throw
    } finally {
        Write-Event 'pipeline_end' @{ status = $record.status }
        Save-Diagnostics
        if ($reportDirectory -ne $releaseDirectory) {
            Copy-Item -LiteralPath $nativeEvents -Destination (Join-Path $reportDirectory 'native-events.jsonl') -Force
            Copy-Item -LiteralPath (Join-Path $releaseDirectory 'release.json') -Destination (Join-Path $reportDirectory 'release.json') -Force
            Get-ChildItem -LiteralPath $reportDirectory -File | Copy-Item -Destination $releaseDirectory -Force
        }
        Write-Host "Release record and diagnostics: $releaseDirectory"
    }
} finally {
    if ($deploymentLock) { $deploymentLock.Dispose() }
    Pop-Location
}
