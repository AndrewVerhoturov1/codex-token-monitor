param(
    [switch]$Validate,
    [string]$MarkerFile
)

$ErrorActionPreference = "Stop"

$projectDir = "D:\Codex+opencode_new\Codex-opencode_tests"
$model = "opencode/deepseek-v4-flash-free"

Remove-Item Env:XDG_DATA_HOME -ErrorAction SilentlyContinue

$env:OPENCODE_CONFIG_CONTENT = @{
    model = $model
    provider = @{
        opencode = @{
            models = @{
                "deepseek-v4-flash-free" = @{
                    options = @{
                        reasoningEffort = "max"
                    }
                }
            }
        }
    }
} | ConvertTo-Json -Depth 10 -Compress

Set-Location -LiteralPath $projectDir

if ($Validate) {
    $resolved = ((& opencode debug config 2>$null) -join "`n") | ConvertFrom-Json
    $result = @(
        "model=$($resolved.model)"
        "reasoningEffort=$($resolved.provider.opencode.models.'deepseek-v4-flash-free'.options.reasoningEffort)"
        "cwd=$((Get-Location).Path)"
        "projectDir=$projectDir"
    )

    if ($MarkerFile) {
        Set-Content -LiteralPath $MarkerFile -Value $result -Encoding UTF8
    }
    else {
        $result
    }
    exit 0
}

& opencode . --model $model
$openCodeExitCode = $LASTEXITCODE

Write-Host ""
Write-Host "OpenCode exited with code $openCodeExitCode"
exit $openCodeExitCode
