param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [string]$ModelId = 'kimi-k2.5-thinking',

    [string]$ApiBaseUrl = 'http://127.0.0.1:9766/v1',

    [string]$HealthUrl = 'http://127.0.0.1:9766/health',

    [string]$Title = 'kimi-runtime-task',

    [string]$TaskText,

    [string]$TaskFile,

    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Message) {
    Write-Error $Message
    exit 1
}

if (-not (Test-Path -LiteralPath $RepoPath)) {
    Fail "RepoPath does not exist: $RepoPath"
}

$resolvedRepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
$resolvedScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$opencodeCommand = Get-Command opencode.cmd -ErrorAction SilentlyContinue
if (-not $opencodeCommand) {
    $candidate = 'C:\Users\andre\AppData\Roaming\npm\opencode.cmd'
    if (Test-Path -LiteralPath $candidate) {
        $opencodeCommand = Get-Item -LiteralPath $candidate
    }
}
if (-not $opencodeCommand) {
    Fail 'opencode.cmd not found'
}

try {
    $health = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 15
} catch {
    Fail "FreeGLMKimiAPI health failed: $($_.Exception.Message)"
}

if (-not $health.ok) {
    Fail 'FreeGLMKimiAPI health responded but ok != true'
}

try {
    $models = Invoke-RestMethod -Uri "$ApiBaseUrl/models" -Method Get -TimeoutSec 15
} catch {
    Fail "FreeGLMKimiAPI models failed: $($_.Exception.Message)"
}

$availableModelIds = @($models.data | ForEach-Object { $_.id })
if (-not $availableModelIds -or $availableModelIds.Count -eq 0) {
    Fail 'No models returned by FreeGLMKimiAPI'
}

if ($availableModelIds -notcontains $ModelId) {
    Fail "Requested model '$ModelId' not found in /v1/models. Available: $($availableModelIds -join ', ')"
}

$config = @{
    '$schema'  = 'https://opencode.ai/config.json'
    permission = @{
        '*' = 'allow'
    }
    provider   = @{
        freeglmkimi = @{
            npm     = '@ai-sdk/openai-compatible'
            name    = 'FreeGLMKimiAPI'
            options = @{
                baseURL = $ApiBaseUrl
                apiKey  = 'dummy-key'
            }
            models  = @{
                $ModelId = @{
                    name = $ModelId
                }
            }
        }
    }
} | ConvertTo-Json -Depth 10 -Compress

Write-Host "health_ok=true"
Write-Host "models_ok=true"
Write-Host "model_found=$ModelId"
Write-Host "runtime_config_only=true"
Write-Host "permanent_opencode_config_touched=false"

if ($CheckOnly) {
    Write-Host "check_only=true"
    exit 0
}

$hasTaskText = -not [string]::IsNullOrWhiteSpace($TaskText)
$hasTaskFile = -not [string]::IsNullOrWhiteSpace($TaskFile)

if (($hasTaskText -and $hasTaskFile) -or (-not $hasTaskText -and -not $hasTaskFile)) {
    Fail 'Provide exactly one of -TaskText or -TaskFile unless -CheckOnly is used'
}

$cleanupTaskFile = $false
if ($hasTaskFile) {
    if (-not (Test-Path -LiteralPath $TaskFile)) {
        Fail "TaskFile does not exist: $TaskFile"
    }
    $resolvedTaskFile = (Resolve-Path -LiteralPath $TaskFile).Path
} else {
    $tempName = 'kimi-runtime-task-' + [guid]::NewGuid().ToString() + '.md'
    $resolvedTaskFile = Join-Path $env:TEMP $tempName
    [System.IO.File]::WriteAllText($resolvedTaskFile, $TaskText, [System.Text.UTF8Encoding]::new($false))
    $cleanupTaskFile = $true
}

try {
    $env:OPENCODE_CONFIG_CONTENT = $config
    & $opencodeCommand.Source run --model "freeglmkimi/$ModelId" --dir $resolvedRepoPath --file $resolvedTaskFile --title $Title 'Read the attached task file and follow its instructions exactly.'
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        exit $exitCode
    }
} finally {
    Remove-Item Env:OPENCODE_CONFIG_CONTENT -ErrorAction SilentlyContinue
    if ($cleanupTaskFile -and (Test-Path -LiteralPath $resolvedTaskFile)) {
        Remove-Item -LiteralPath $resolvedTaskFile -Force -ErrorAction SilentlyContinue
    }
}
