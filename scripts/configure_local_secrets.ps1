param(
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$envPath = Join-Path $ProjectRoot ".env"
$examplePath = Join-Path $ProjectRoot ".env.example"

if (-not (Test-Path $envPath)) {
    Copy-Item $examplePath $envPath
    Write-Host "Created .env from .env.example."
}

function New-RandomBytes {
    param([int]$Count)

    $bytes = New-Object byte[] $Count
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return ,$bytes
}

function New-UrlSafeToken {
    param([int]$ByteCount)

    return [Convert]::ToBase64String((New-RandomBytes $ByteCount)).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function New-FernetKey {
    return [Convert]::ToBase64String((New-RandomBytes 32)).Replace("+", "-").Replace("/", "_")
}

function Get-DotEnvValue {
    param(
        [string]$Text,
        [string]$Name
    )

    $pattern = "(?m)^" + [Regex]::Escape($Name) + "=(.*)$"
    $match = [Regex]::Match($Text, $pattern)
    if ($match.Success) {
        return $match.Groups[1].Value.Trim()
    }
    return ""
}

function Set-DotEnvValue {
    param(
        [string]$Text,
        [string]$Name,
        [string]$Value
    )

    $pattern = "(?m)^" + [Regex]::Escape($Name) + "=.*$"
    $line = "$Name=$Value"
    if ([Regex]::IsMatch($Text, $pattern)) {
        return [Regex]::Replace($Text, $pattern, $line)
    }
    return $Text.TrimEnd() + [Environment]::NewLine + $line + [Environment]::NewLine
}

$text = [System.IO.File]::ReadAllText($envPath)
$changed = $false

$serviceToken = Get-DotEnvValue $text "ASSESSMENT_SERVICE_TOKEN"
if ([string]::IsNullOrWhiteSpace($serviceToken) -or $serviceToken -match "^(replace-|dev-service-token)") {
    $text = Set-DotEnvValue $text "ASSESSMENT_SERVICE_TOKEN" (New-UrlSafeToken 48)
    $changed = $true
}

$adminToken = Get-DotEnvValue $text "ASSESSMENT_ADMIN_TOKEN"
if ([string]::IsNullOrWhiteSpace($adminToken) -or $adminToken -match "^(replace-|dev-admin-token)") {
    $text = Set-DotEnvValue $text "ASSESSMENT_ADMIN_TOKEN" (New-UrlSafeToken 48)
    $changed = $true
}

$audioKey = Get-DotEnvValue $text "AUDIO_ENCRYPTION_KEY"
if ($audioKey -notmatch "^[A-Za-z0-9_-]{43}=$") {
    $text = Set-DotEnvValue $text "AUDIO_ENCRYPTION_KEY" (New-FernetKey)
    $changed = $true
}

# Keep an existing installation on the code and item-bank versions shipped
# with this release. Secrets and provider keys are preserved.
$previousAssessmentVersion = Get-DotEnvValue $text "ASSESSMENT_VERSION"
if ($previousAssessmentVersion -ne "0.2.1") {
    $text = Set-DotEnvValue $text "ASSESSMENT_VERSION" "0.2.1"
    $changed = $true
}

# v0.2.0 inherited the more quota-constrained Flash model from older .env
# files. Flash-Lite is sufficient for this compact structured rubric and is
# substantially cheaper. Users can deliberately switch back after migration.
$geminiModel = Get-DotEnvValue $text "GEMINI_MODEL"
if (
    [string]::IsNullOrWhiteSpace($geminiModel) -or
    ($previousAssessmentVersion -ne "0.2.1" -and $geminiModel -eq "gemini-2.5-flash")
) {
    $text = Set-DotEnvValue $text "GEMINI_MODEL" "gemini-2.5-flash-lite"
    $changed = $true
}

if ((Get-DotEnvValue $text "GEMINI_API_VERSION") -ne "v1") {
    $text = Set-DotEnvValue $text "GEMINI_API_VERSION" "v1"
    $changed = $true
}

if ([string]::IsNullOrWhiteSpace((Get-DotEnvValue $text "ASSESSMENT_RESPONSE_COLLECTION_DELAY_SECONDS"))) {
    $text = Set-DotEnvValue $text "ASSESSMENT_RESPONSE_COLLECTION_DELAY_SECONDS" "4.00"
    $changed = $true
}

# The placement flow no longer contains a standalone pronunciation task.
# Remove the obsolete switch while preserving every credential and storage setting.
$legacyPronunciationPattern = "(?m)^PRONUNCIATION_TASK_ENABLED=.*(?:\r?\n)?"
if ([Regex]::IsMatch($text, $legacyPronunciationPattern)) {
    $text = [Regex]::Replace($text, $legacyPronunciationPattern, "")
    $changed = $true
}
if ((Get-DotEnvValue $text "ITEM_BANK_VERSION") -ne "0.2.0") {
    $text = Set-DotEnvValue $text "ITEM_BANK_VERSION" "0.2.0"
    $changed = $true
}

foreach ($versionSetting in @{
    "RUBRIC_VERSION" = "0.2.1"
    "SCORER_VERSION" = "0.2.1"
}.GetEnumerator()) {
    if ((Get-DotEnvValue $text $versionSetting.Key) -ne $versionSetting.Value) {
        $text = Set-DotEnvValue $text $versionSetting.Key $versionSetting.Value
        $changed = $true
    }
}

$requestTimeout = Get-DotEnvValue $text "ASSESSMENT_REQUEST_TIMEOUT_SECONDS"
if (
    [string]::IsNullOrWhiteSpace($requestTimeout) -or
    $requestTimeout -eq "20" -or
    $requestTimeout -eq "90"
) {
    $text = Set-DotEnvValue $text "ASSESSMENT_REQUEST_TIMEOUT_SECONDS" "120"
    $changed = $true
}

$evaluatorTimeout = Get-DotEnvValue $text "EVALUATOR_TIMEOUT_SECONDS"
if ([string]::IsNullOrWhiteSpace($evaluatorTimeout) -or $evaluatorTimeout -eq "25") {
    $text = Set-DotEnvValue $text "EVALUATOR_TIMEOUT_SECONDS" "15"
    $changed = $true
}

$evaluatorRetries = Get-DotEnvValue $text "EVALUATOR_MAX_RETRIES"
if ([string]::IsNullOrWhiteSpace($evaluatorRetries) -or $evaluatorRetries -eq "1") {
    $text = Set-DotEnvValue $text "EVALUATOR_MAX_RETRIES" "3"
    $changed = $true
}

if ([string]::IsNullOrWhiteSpace((Get-DotEnvValue $text "EVALUATOR_MAX_RETRY_WAIT_SECONDS"))) {
    $text = Set-DotEnvValue $text "EVALUATOR_MAX_RETRY_WAIT_SECONDS" "60"
    $changed = $true
}

if ([string]::IsNullOrWhiteSpace((Get-DotEnvValue $text "ASSESSMENT_TTS_TIMEOUT_SECONDS"))) {
    $text = Set-DotEnvValue $text "ASSESSMENT_TTS_TIMEOUT_SECONDS" "20"
    $changed = $true
}

if ([string]::IsNullOrWhiteSpace((Get-DotEnvValue $text "ASSESSMENT_TTS_MAX_RETRIES"))) {
    $text = Set-DotEnvValue $text "ASSESSMENT_TTS_MAX_RETRIES" "4"
    $changed = $true
}

if ($changed) {
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($envPath, $text, $utf8WithoutBom)
    Write-Host "Updated local secrets and release-version settings in .env where needed."
}
else {
    Write-Host "Local service tokens and audio-encryption key are already configured."
}
