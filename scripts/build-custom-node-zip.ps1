<#
.SYNOPSIS
Builds an installable ZIP for ComfyUI's custom_nodes directory.

.DESCRIPTION
Creates a versioned archive containing a single top-level custom-node folder.
Extract the archive directly into ComfyUI/custom_nodes, then restart ComfyUI.

.PARAMETER OutputDirectory
Directory for the ZIP. Relative paths are resolved from the repository root.

.PARAMETER PackageName
Name of the top-level folder stored in the ZIP.

.PARAMETER Force
Replaces an archive that already exists.

.PARAMETER SkipFrontendBuild
Uses the existing web/index.js instead of rebuilding it. Intended only for CI
jobs that already ran the complete frontend check immediately beforehand.

.EXAMPLE
./scripts/build-custom-node-zip.ps1

.EXAMPLE
./scripts/build-custom-node-zip.ps1 -Force

.EXAMPLE
./scripts/build-custom-node-zip.ps1 -OutputDirectory C:\Builds
#>
[CmdletBinding()]
param(
    [string]$OutputDirectory = "dist",
    [string]$PackageName = "ComfyUI-Ollama-ImageList",
    [switch]$Force,
    [switch]$SkipFrontendBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $resolvedOutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
}
else {
    $resolvedOutputDirectory = [System.IO.Path]::GetFullPath(
        (Join-Path $repoRoot $OutputDirectory)
    )
}

if ([string]::IsNullOrWhiteSpace($PackageName) -or
    $PackageName -in @(".", "..") -or
    $PackageName -match '[\\/]' -or
    $PackageName.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0) {
    throw "PackageName must be a valid single directory name."
}

$pyprojectPath = Join-Path $repoRoot "pyproject.toml"
$pyproject = Get-Content -LiteralPath $pyprojectPath -Raw
$versionMatch = [regex]::Match(
    $pyproject,
    '(?m)^\s*version\s*=\s*"([^"]+)"\s*$'
)

if (-not $versionMatch.Success) {
    throw "Could not read the project version from $pyprojectPath."
}

$version = $versionMatch.Groups[1].Value
$archiveName = "$PackageName-$version.zip"
$archivePath = Join-Path $resolvedOutputDirectory $archiveName

if ((Test-Path -LiteralPath $archivePath) -and -not $Force) {
    throw "Archive already exists: $archivePath. Re-run with -Force to replace it."
}

$rootFiles = @(
    "__init__.py",
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    "LICENSE"
)

$optionalRootFiles = @(
    "requirements.txt"
)

$packageDirectories = @(
    "backend",
    "web",
    "assets",
    "presets",
    "locales",
    "docs",
    "workflows"
)

if (-not $SkipFrontendBuild) {
    $bun = Get-Command "bun" -ErrorAction SilentlyContinue
    if ($null -eq $bun) {
        throw "Bun is required to build the packaged frontend. Install Bun or use -SkipFrontendBuild only after a verified frontend build."
    }
    Push-Location $repoRoot
    try {
        & $bun.Source run build
        if ($LASTEXITCODE -ne 0) {
            throw "The frontend build failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

$webBundle = Join-Path $repoRoot "web/index.js"
if (-not (Test-Path -LiteralPath $webBundle -PathType Leaf)) {
    throw "Required frontend bundle is missing: $webBundle. Run 'bun run build' first."
}

$webJavaScriptFiles = @(
    Get-ChildItem -LiteralPath (Join-Path $repoRoot "web") -Filter "*.js" -File -Recurse
)
if ($webJavaScriptFiles.Count -ne 1 -or $webJavaScriptFiles[0].Name -ne "index.js") {
    throw "The web directory must contain exactly one JavaScript bundle named index.js."
}

$stagingRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) ("comfyui-node-zip-" + [guid]::NewGuid().ToString("N"))
$stagedPackage = Join-Path $stagingRoot $PackageName

try {
    New-Item -ItemType Directory -Path $stagedPackage -Force | Out-Null

    foreach ($relativePath in $rootFiles) {
        $source = Join-Path $repoRoot $relativePath
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required package file is missing: $source"
        }

        Copy-Item -LiteralPath $source -Destination $stagedPackage
    }

    foreach ($relativePath in $optionalRootFiles) {
        $source = Join-Path $repoRoot $relativePath
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination $stagedPackage
        }
    }

    foreach ($relativePath in $packageDirectories) {
        $source = Join-Path $repoRoot $relativePath
        if (Test-Path -LiteralPath $source -PathType Container) {
            Copy-Item -LiteralPath $source -Destination $stagedPackage -Recurse
        }
    }

    Get-ChildItem -LiteralPath $stagedPackage -Recurse -Force |
        Where-Object {
            $_.Name -eq "__pycache__" -or
            $_.Extension -in @(".pyc", ".pyo")
        } |
        Sort-Object { $_.FullName.Length } -Descending |
        Remove-Item -Recurse -Force

    New-Item -ItemType Directory -Path $resolvedOutputDirectory -Force | Out-Null

    $compressParameters = @{
        LiteralPath      = $stagedPackage
        DestinationPath  = $archivePath
        CompressionLevel = "Optimal"
    }

    if ($Force) {
        $compressParameters.Force = $true
    }

    Compress-Archive @compressParameters
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}

$archive = Get-Item -LiteralPath $archivePath
Write-Output "Built ComfyUI custom-node archive:"
Write-Output $archive.FullName
Write-Output ("Size: {0:N0} bytes" -f $archive.Length)
