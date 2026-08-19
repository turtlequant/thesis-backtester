[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$SkipArchive,
    [switch]$PrivateBaseline,
    [switch]$ShowConsole
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$entryPoint = Join-Path $projectRoot "src\desktop\main.py"
$iconPath = Join-Path $projectRoot "src\desktop\assets\icon.ico"
$buildRoot = Join-Path $projectRoot ".build\nuitka"
$buildEnvironment = Join-Path $projectRoot ".build\packaging-venv"
$distRoot = Join-Path $projectRoot "dist"
$pythonVersion = "3.11"

function Assert-ProjectPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $prefix = $projectRoot.TrimEnd('\') + '\'
    if (-not $full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the project: $full"
    }
    return $full
}

function Remove-ProjectDirectory([string]$Path) {
    $full = Assert-ProjectPath $Path
    if (Test-Path -LiteralPath $full) {
        Remove-Item -LiteralPath $full -Recurse -Force
    }
}

function Copy-Directory([string]$Source, [string]$RelativeDestination) {
    $sourcePath = Join-Path $projectRoot $Source
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
        throw "Required runtime directory is missing: $sourcePath"
    }
    $destination = Join-Path $releaseDir $RelativeDestination
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Copy-Item -Path (Join-Path $sourcePath '*') -Destination $destination -Recurse -Force
}

function Copy-File([string]$Source, [string]$RelativeDestination) {
    $sourcePath = Join-Path $projectRoot $Source
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Required runtime file is missing: $sourcePath"
    }
    $destination = Join-Path $releaseDir $RelativeDestination
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destination -Force
}

if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
    throw "Run this script from a complete thesis-backtester checkout."
}

$versionSourcePath = Join-Path $projectRoot "src\version.py"
$versionSource = Get-Content -Raw -Encoding UTF8 -LiteralPath $versionSourcePath
$appNameMatch = [regex]::Match($versionSource, '(?m)^APP_NAME\s*=\s*"([^"]+)"')
$releaseStageMatch = [regex]::Match($versionSource, '(?m)^RELEASE_STAGE\s*=\s*"([^"]+)"')
$versionMatch = [regex]::Match($versionSource, '(?m)^__version__\s*=\s*"([^"]+)"')
if (-not $appNameMatch.Success -or -not $releaseStageMatch.Success -or -not $versionMatch.Success) {
    throw "Unable to read the application identity from src/version.py"
}
$appName = $appNameMatch.Groups[1].Value
$releaseStage = $releaseStageMatch.Groups[1].Value
$version = $versionMatch.Groups[1].Value
$displayVersion = "$releaseStage v$version"
$releaseStageSlug = ($releaseStage -replace '[^A-Za-z0-9.-]', '-').Trim('-')
$releaseName = "ThesisBacktester-$releaseStageSlug-v$version-windows-x64"
$releaseDir = Join-Path $distRoot $releaseName
$archivePath = Join-Path $distRoot "$releaseName.zip"
$privateReleaseName = "ThesisBacktester-$releaseStageSlug-v$version-private-baseline-windows-x64"
$privateArchivePath = Join-Path $distRoot "$privateReleaseName.zip"
$privateStageDir = Join-Path $projectRoot ".build\private-baseline\$privateReleaseName"

if ($Clean) {
    Remove-ProjectDirectory $buildRoot
    Remove-ProjectDirectory $releaseDir
    Remove-ProjectDirectory $privateStageDir
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath (Assert-ProjectPath $archivePath) -Force
    }
    if ($PrivateBaseline -and (Test-Path -LiteralPath $privateArchivePath)) {
        Remove-Item -LiteralPath (Assert-ProjectPath $privateArchivePath) -Force
    }
}
elseif (
    (Test-Path -LiteralPath $releaseDir) -or
    (Test-Path -LiteralPath $archivePath) -or
    ($PrivateBaseline -and (Test-Path -LiteralPath $privateArchivePath))
) {
    throw "Release $releaseName already exists. Use -Clean only after preserving its workspace."
}

New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
New-Item -ItemType Directory -Path $distRoot -Force | Out-Null

$env:UV_CACHE_DIR = Join-Path $projectRoot ".uv-cache"
$env:NUITKA_CACHE_DIR = Join-Path $projectRoot ".build\nuitka-cache"
$env:MPLBACKEND = "Agg"
$env:UV_PROJECT_ENVIRONMENT = $buildEnvironment
$consoleMode = if ($ShowConsole) { "force" } else { "disable" }
$reportPath = Join-Path $buildRoot "compilation-report.xml"
$managedPythonOutput = & uv python find $pythonVersion --managed-python
$managedPython = if ($managedPythonOutput) { ([string]$managedPythonOutput).Trim() } else { "" }
if ($LASTEXITCODE -ne 0 -or -not $managedPython) {
    Write-Host "Installing uv-managed CPython $pythonVersion..."
    & uv python install $pythonVersion
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to install uv-managed CPython $pythonVersion"
    }
    $managedPythonOutput = & uv python find $pythonVersion --managed-python
    $managedPython = if ($managedPythonOutput) { ([string]$managedPythonOutput).Trim() } else { "" }
}

Write-Host "Synchronizing isolated packaging environment with $managedPython..."
& uv sync --group build --python $managedPython --no-install-project
if ($LASTEXITCODE -ne 0) {
    throw "Unable to synchronize the isolated packaging environment"
}
$packagingPython = Join-Path $buildEnvironment "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $packagingPython -PathType Leaf)) {
    throw "Packaging Python was not created: $packagingPython"
}

$nuitkaArgs = @(
    "-m", "nuitka",
    "--standalone",
    "--assume-yes-for-downloads",
    "--enable-plugin=no-qt",
    "--disable-plugins=pywebview",
    "--include-module=webview.platforms.winforms",
    "--include-module=webview.platforms.win32",
    "--include-module=webview.platforms.edgechromium",
    "--include-module=webview.platforms.mshtml",
    "--nofollow-import-to=webview.platforms.android",
    "--nofollow-import-to=webview.platforms.cocoa",
    "--nofollow-import-to=webview.platforms.gtk",
    "--nofollow-import-to=webview.platforms.qt",
    "--nofollow-import-to=webview.platforms.cef",
    "--include-package-data=akshare",
    "--windows-console-mode=$consoleMode",
    "--windows-icon-from-ico=$iconPath",
    "--output-filename=ThesisBacktester.exe",
    "--output-dir=$buildRoot",
    "--report=$reportPath",
    $entryPoint
)

Push-Location $projectRoot
try {
    Write-Host "Building $appName $displayVersion with Nuitka..."
    & $packagingPython @nuitkaArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Nuitka failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$standaloneDir = Get-ChildItem -LiteralPath $buildRoot -Directory |
    Where-Object { $_.Name.EndsWith('.dist') } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $standaloneDir) {
    throw "Nuitka standalone directory was not produced under $buildRoot"
}

Remove-ProjectDirectory $releaseDir
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
Copy-Item -Path (Join-Path $standaloneDir.FullName '*') -Destination $releaseDir -Recurse -Force

$unusedWebviewAsset = Join-Path $releaseDir "webview\lib\pywebview-android.jar"
if (Test-Path -LiteralPath $unusedWebviewAsset) {
    Remove-Item -LiteralPath $unusedWebviewAsset -Force
}

# Program resources stay outside the executable. A read-only workspace seed is
# staged separately; first launch materializes it under workspace/ without
# overwriting later user edits. Databases and reports are never bundled.
Copy-Directory "src\desktop\frontend" "src\desktop\frontend"
Copy-Directory "src\desktop\assets" "src\desktop\assets"
Copy-Directory "src\data\catalog" "src\data\catalog"
Copy-Directory "workspace\operators\v1" "resources\workspace_seed\operators\v1"

$operatorV2Directories = @(
    "bank", "consumer", "decision", "forward_risk", "fundamental",
    "history_adapters", "manufacturing", "screening", "special", "tech", "valuation"
)
foreach ($directory in $operatorV2Directories) {
    Copy-Directory "workspace\operators\v2\$directory" "resources\workspace_seed\operators\v2\$directory"
}
Copy-File "workspace\operators\v2\README.md" "resources\workspace_seed\operators\v2\README.md"

$seedFactors = Join-Path $releaseDir "resources\workspace_seed\factors"
New-Item -ItemType Directory -Path $seedFactors -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $projectRoot "workspace\factors") -File -Filter "*.py" |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $seedFactors -Force }
Copy-Directory "workspace\factors\definitions" "resources\workspace_seed\factors\definitions"
Copy-Directory "workspace\screening_strategies" "resources\workspace_seed\screening_strategies"

$builtInStrategies = @("bank_analysis", "income_focus", "quick_scan", "v6_enhanced", "v6_value")
foreach ($strategy in $builtInStrategies) {
    Copy-File "workspace\strategies\$strategy\strategy.yaml" "resources\workspace_seed\strategies\$strategy\strategy.yaml"
}

Copy-File "docs\PRODUCT_GUIDE.md" "docs\PRODUCT_GUIDE.md"
Copy-File "packaging\README_WINDOWS.md" "README.md"
Copy-File "LICENSE" "LICENSE"

$buildInfo = [ordered]@{
    name = $appName
    version = $version
    release_stage = $releaseStage
    display_version = $displayVersion
    platform = "windows-x64"
    packaging = "nuitka-standalone"
    built_at_utc = [DateTime]::UtcNow.ToString("o")
}
$buildInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $releaseDir "BUILD_INFO.json") -Encoding UTF8

$requiredPaths = @(
    "ThesisBacktester.exe",
    "src\desktop\frontend\index.html",
    "src\desktop\assets\icon.ico",
    "src\data\catalog\native_fields.yaml",
    "resources\workspace_seed\operators\v2\README.md",
    "resources\workspace_seed\factors\definitions",
    "resources\workspace_seed\screening_strategies",
    "resources\workspace_seed\strategies\v6_value\strategy.yaml",
    "docs\PRODUCT_GUIDE.md",
    "LICENSE"
)
foreach ($relativePath in $requiredPaths) {
    if (-not (Test-Path -LiteralPath (Join-Path $releaseDir $relativePath))) {
        throw "Release validation failed; missing $relativePath"
    }
}

$runtimeProbeOptions = @{
    FilePath = Join-Path $releaseDir "ThesisBacktester.exe"
    ArgumentList = "--runtime-check"
    WindowStyle = "Hidden"
    Wait = $true
    PassThru = $true
}
$runtimeProbe = Start-Process @runtimeProbeOptions
if ($runtimeProbe.ExitCode -ne 0) {
    $runtimeReport = Join-Path $releaseDir "runtime-check.json"
    if (Test-Path -LiteralPath $runtimeReport) {
        Write-Host (Get-Content -Raw -Encoding UTF8 -LiteralPath $runtimeReport)
    }
    throw "Packaged runtime check failed with exit code $($runtimeProbe.ExitCode)"
}
$workspaceRequiredPaths = @(
    "workspace\operators\v2\README.md",
    "workspace\factors\definitions",
    "workspace\screening_strategies",
    "workspace\strategies\v6_value\strategy.yaml"
)
foreach ($relativePath in $workspaceRequiredPaths) {
    if (-not (Test-Path -LiteralPath (Join-Path $releaseDir $relativePath))) {
        throw "Workspace initialization failed; missing $relativePath"
    }
}
$runtimeReport = Join-Path $releaseDir "runtime-check.json"
if (Test-Path -LiteralPath $runtimeReport) {
    Remove-Item -LiteralPath $runtimeReport -Force
}

if (-not $SkipArchive) {
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath (Assert-ProjectPath $archivePath) -Force
    }
    Compress-Archive -Path (Join-Path $releaseDir '*') -DestinationPath $archivePath -CompressionLevel Optimal

    if ($PrivateBaseline) {
        Write-Host "Building sanitized private Tushare baseline archive..."
        try {
            & $packagingPython (Join-Path $projectRoot "scripts\package_private_baseline.py") `
                --project-root $projectRoot `
                --source-workspace (Join-Path $projectRoot "workspace") `
                --standard-release $releaseDir `
                --staging-dir $privateStageDir `
                --archive $privateArchivePath `
                --display-version $displayVersion
            if ($LASTEXITCODE -ne 0) {
                throw "Private baseline packaging failed with exit code $LASTEXITCODE"
            }
        }
        finally {
            Remove-ProjectDirectory $privateStageDir
        }
    }
}

Write-Host ""
Write-Host "Release directory: $releaseDir"
if (-not $SkipArchive) {
    Write-Host "Release archive:   $archivePath"
    if ($PrivateBaseline) {
        Write-Host "Private baseline:  $privateArchivePath"
    }
}
Write-Host "Compilation report: $reportPath"
