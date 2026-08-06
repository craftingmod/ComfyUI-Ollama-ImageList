<#
.SYNOPSIS
Deploys the current custom-node project to the configured portable ComfyUI instance.

.DESCRIPTION
Builds the same runtime-only package as build-custom-node-zip.ps1, stages it next
to the destination, and replaces the installed custom-node directory. If the
replacement fails after the existing directory is moved aside, the script restores
the previous installation.

The fixed destination is:
V:\ComfyUI\portable_260711\ComfyUI\custom_nodes\ComfyUI-Ollama-Multimodal

.EXAMPLE
./scripts/deploy-to-portable.ps1

.EXAMPLE
./scripts/deploy-to-portable.ps1 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$packageName = "ComfyUI-Ollama-Multimodal"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$targetDirectory = [System.IO.Path]::GetFullPath(
    "V:\ComfyUI\portable_260711\ComfyUI\custom_nodes\ComfyUI-Ollama-Multimodal"
)
$targetParent = [System.IO.Path]::GetDirectoryName($targetDirectory)
$buildScript = Join-Path $PSScriptRoot "build-custom-node-zip.ps1"

function Test-ReparsePoint {
    param([System.IO.FileSystemInfo]$Item)

    return ($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
}

if ([System.IO.Path]::GetFileName($targetDirectory) -ne $packageName) {
    throw "The deployment target must end with the expected package name: $packageName"
}

if ([System.IO.Path]::GetFileName($targetParent) -ne "custom_nodes") {
    throw "The deployment target must be a direct child of a custom_nodes directory."
}

if ($repoRoot.TrimEnd("\") -eq $targetDirectory.TrimEnd("\")) {
    throw "The source repository and deployment target must be different directories."
}

if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw "Package build script is missing: $buildScript"
}

$targetParentItem = Get-Item -LiteralPath $targetParent -Force
if (-not $targetParentItem.PSIsContainer) {
    throw "The target parent is not a directory: $targetParent"
}
if (Test-ReparsePoint $targetParentItem) {
    throw "The custom_nodes directory cannot be a symbolic link or junction: $targetParent"
}

$existingTarget = $null
$existingEntryCount = 0
if (Test-Path -LiteralPath $targetDirectory) {
    $existingTarget = Get-Item -LiteralPath $targetDirectory -Force
    if (-not $existingTarget.PSIsContainer) {
        throw "The deployment target exists but is not a directory: $targetDirectory"
    }
    if (Test-ReparsePoint $existingTarget) {
        throw "The deployment target cannot be a symbolic link or junction: $targetDirectory"
    }

    $existingEntries = @(Get-ChildItem -LiteralPath $targetDirectory -Recurse -Force)
    $reparsePoints = @($existingEntries | Where-Object { Test-ReparsePoint $_ })
    if ($reparsePoints.Count -gt 0) {
        $paths = $reparsePoints.FullName -join [Environment]::NewLine
        throw "The deployment target contains symbolic links or junctions and will not be replaced:`n$paths"
    }
    $existingEntryCount = $existingEntries.Count + 1
}

$operationId = [guid]::NewGuid().ToString("N")
$temporaryRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) "comfyui-node-deploy-$operationId"
$archiveDirectory = Join-Path $temporaryRoot "archive"
$deploymentRoot = Join-Path $targetParent ".$packageName.deploy-$operationId"
$backupDirectory = Join-Path $targetParent ".$packageName.backup-$operationId"

Write-Output "Source: $repoRoot"
Write-Output "Target: $targetDirectory"
if ($null -ne $existingTarget) {
    Write-Output "Existing target entries to replace: $existingEntryCount"
}
else {
    Write-Output "Existing target: not installed"
}

if (-not $PSCmdlet.ShouldProcess($targetDirectory, "Replace installed custom node")) {
    return
}

try {
    New-Item -ItemType Directory -Path $archiveDirectory | Out-Null
    & $buildScript -OutputDirectory $archiveDirectory -PackageName $packageName -Force

    $archives = @(Get-ChildItem -LiteralPath $archiveDirectory -Filter "*.zip" -File)
    if ($archives.Count -ne 1) {
        throw "Expected exactly one deployment archive, found $($archives.Count)."
    }

    if ((Test-Path -LiteralPath $deploymentRoot) -or
        (Test-Path -LiteralPath $backupDirectory)) {
        throw "A generated staging or backup path already exists. Re-run the script."
    }

    New-Item -ItemType Directory -Path $deploymentRoot | Out-Null
    Expand-Archive -LiteralPath $archives[0].FullName -DestinationPath $deploymentRoot

    $stagedPackage = Join-Path $deploymentRoot $packageName
    if (-not (Test-Path -LiteralPath (Join-Path $stagedPackage "__init__.py") -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $stagedPackage "backend") -PathType Container)) {
        throw "The staged package is missing required custom-node files."
    }

    $movedExistingTarget = $false
    try {
        if ($null -ne $existingTarget) {
            Move-Item -LiteralPath $targetDirectory -Destination $backupDirectory
            $movedExistingTarget = $true
        }

        Move-Item -LiteralPath $stagedPackage -Destination $targetDirectory

        if ($movedExistingTarget) {
            Remove-Item -LiteralPath $backupDirectory -Recurse -Force
            $movedExistingTarget = $false
        }
    }
    catch {
        if ($movedExistingTarget -and
            -not (Test-Path -LiteralPath $targetDirectory) -and
            (Test-Path -LiteralPath $backupDirectory -PathType Container)) {
            Move-Item -LiteralPath $backupDirectory -Destination $targetDirectory
            $movedExistingTarget = $false
        }
        throw
    }

    Write-Output "Deployed custom node successfully:"
    Write-Output $targetDirectory
    Write-Output "Restart ComfyUI to load the updated node."
}
finally {
    if (Test-Path -LiteralPath $deploymentRoot) {
        Remove-Item -LiteralPath $deploymentRoot -Recurse -Force
    }
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
