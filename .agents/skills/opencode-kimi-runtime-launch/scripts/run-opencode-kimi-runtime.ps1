param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [string]$ModelId = 'kimi-k2.5-thinking',

    [string]$ApiBaseUrl = 'http://127.0.0.1:9766/v1',

    [string]$HealthUrl = 'http://127.0.0.1:9766/health',

    [string]$Title = 'kimi-runtime-task',

    [string]$TaskText,

    [string]$TaskFile,

    [switch]$CheckOnly,

    [string]$ExecutionProfile,

    [string]$FullProfileReason
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Message) {
    Write-Error $Message
    exit 1
}

# Reject obsolete C1/C2/C3 profiles with helpful error
if (-not [string]::IsNullOrWhiteSpace($ExecutionProfile)) {
    $normalizedProfile = $ExecutionProfile.Trim().ToUpperInvariant()
    if ($normalizedProfile -in @('C1', 'C2', 'C3')) {
        Fail "Profile '$ExecutionProfile' is obsolete. Kimi now uses a single manual-only /kimifree path with tools: read, write, edit, glob, grep, bash, webfetch. Remove -ExecutionProfile or omit it to use the default manual-only Kimi behavior."
    }
    if ($normalizedProfile -eq 'C4') {
        Write-Warning "Profile 'C4' is now the default. The -ExecutionProfile parameter is ignored. Using the manual-only Kimi path (/kimifree) with read, write, edit, glob, grep, bash, webfetch."
    }
}

# Single profile: /kimifree manual-only Kimi
$profileAgentName = 'kimi-manual-route'
$profileAllowedTools = 'read, write, edit, glob, grep, bash, webfetch + external reference URL'
$fullToolCatalogSent = $false
$githubToolsSent = $false
$referenceUrl = 'https://github.com/AndrewVerhoturov1/codex-token-monitor/blob/main/docs/kimi-c4-external-tool-reference.md'

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

# Build tools map for the manual-only Kimi route
$allToolIds = @('bash', 'read', 'glob', 'grep', 'edit', 'write', 'task', 'webfetch', 'todowrite', 'websearch', 'skill', 'apply_patch')
$toolsMap = @{}
$permissionMap = @{}
$allowed = @('read', 'write', 'edit', 'glob', 'grep', 'bash', 'webfetch')
foreach ($id in $allToolIds) {
    $isAllowed = $allowed -contains $id
    $toolsMap[$id] = $isAllowed
    $permissionMap[$id] = if ($isAllowed) { 'allow' } else { 'deny' }
}

$profilePrompt = @"
You are a manual-only Kimi runtime agent invoked via /kimifree or explicit Kimi request.

Reference URL (fetch before implementation):
- URL: $referenceUrl
- Description: public compact reference for extended OpenCode/Kimi tool identity catalog, file/GitHub tool families, output formats, guard rules, and the manual-only Kimi contract.
- Action: Before implementing any task, call webfetch with this URL to read the reference content.

Your actual available tools are: read, write, edit, glob, grep, bash, webfetch. Use webfetch to read the reference URL above before implementation. Do not claim any other tool is available.
"@

$agentConfig = @{
    description = "Manual-only Kimi runtime agent"
    mode        = 'primary'
    prompt      = $profilePrompt
    tools       = $toolsMap
    permission  = $permissionMap
}

$config = @{
    '$schema'  = 'https://opencode.ai/config.json'
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
    agent = @{
        $profileAgentName = $agentConfig
    }
    mcp    = @{
        github = @{
            enabled = $false
        }
    }
} | ConvertTo-Json -Depth 10 -Compress

Write-Host "health_ok=true"
Write-Host "models_ok=true"
Write-Host "model_found=$ModelId"
Write-Host "execution_profile=/kimifree"
Write-Host "profile_agent=$profileAgentName"
Write-Host "profile_allowed_tools=$profileAllowedTools"
Write-Host "full_tool_catalog_sent=$fullToolCatalogSent"
Write-Host "github_tools_sent=$githubToolsSent"
Write-Host "reference_url=$referenceUrl"
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
    $stderrFile = [System.IO.Path]::GetTempFileName()
    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $env:OPENCODE_CONFIG_CONTENT = $config
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $opencodeCommand.Source run --model "freeglmkimi/$ModelId" --agent $profileAgentName --dir $resolvedRepoPath --file $resolvedTaskFile --title $Title 'Read the attached task file and follow its instructions exactly.' 1>$stdoutFile 2>$stderrFile
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }

    $stdoutContent = if (Test-Path -LiteralPath $stdoutFile) { [System.IO.File]::ReadAllText($stdoutFile) } else { '' }
    $stderrContent = if (Test-Path -LiteralPath $stderrFile) { [System.IO.File]::ReadAllText($stderrFile) } else { '' }

    if (-not [string]::IsNullOrWhiteSpace($stderrContent)) {
        Write-Warning "stderr: $stderrContent"
    }
    if (-not [string]::IsNullOrWhiteSpace($stdoutContent)) {
        Write-Host $stdoutContent
    }

    if ($exitCode -ne 0) {
        exit $exitCode
    }
    if ([string]::IsNullOrWhiteSpace($stdoutContent)) {
        Fail 'opencode.cmd produced no stdout output'
    }
} finally {
    Remove-Item -LiteralPath $stdoutFile -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stderrFile -ErrorAction SilentlyContinue
    Remove-Item Env:OPENCODE_CONFIG_CONTENT -ErrorAction SilentlyContinue
    if ($cleanupTaskFile -and (Test-Path -LiteralPath $resolvedTaskFile)) {
        Remove-Item -LiteralPath $resolvedTaskFile -Force -ErrorAction SilentlyContinue
    }
}
