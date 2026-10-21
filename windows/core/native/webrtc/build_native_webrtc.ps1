$ErrorActionPreference = 'Stop'

# Build LazyPC's native WebRTC bridge from the canonical files in this folder.
# Set WEBRTC_SRC to the root of a checked-out WebRTC source tree (the folder
# containing webrtc.gni), if it is not C:\Dev\webrtc\src.

$NativeRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$WebRtcSrc = if ($env:WEBRTC_SRC) { $env:WEBRTC_SRC } else { 'C:\Dev\webrtc\src' }
$WebRtcSrc = [System.IO.Path]::GetFullPath($WebRtcSrc)
$BuildDir = Join-Path $WebRtcSrc 'out\Default'
$SyncDir = Join-Path $WebRtcSrc 'lazypc_native'
$OutputDir = Join-Path $ProjectRoot 'windows\bin'
$OutputDll = Join-Path $OutputDir 'lazypc_webrtc.dll'

if (-not (Test-Path (Join-Path $WebRtcSrc 'webrtc.gni'))) {
    throw "WebRTC source root not found at '$WebRtcSrc'. Set WEBRTC_SRC to the directory containing webrtc.gni."
}
if (-not (Get-Command gn -ErrorAction SilentlyContinue)) {
    throw 'gn was not found in PATH. Open a depot_tools shell or add depot_tools to PATH.'
}
# This output directory has Siso state. Always build through depot_tools' autoninja,
# which selects the correct backend. Do not fall back to plain ninja.
$AutoninjaCommand = Get-Command autoninja -ErrorAction SilentlyContinue
if (-not $AutoninjaCommand) {
    throw 'autoninja was not found in PATH. Open a depot_tools-enabled PowerShell and rerun this script. Plain ninja is intentionally not used because out\Default contains Siso state.'
}

# Sync the complete source tree while preserving the include layout expected by
# BUILD.gn. This avoids missing audio/video sources and stale files.
New-Item -ItemType Directory -Force -Path $SyncDir | Out-Null
Copy-Item -Force (Join-Path $NativeRoot 'BUILD.gn') (Join-Path $SyncDir 'BUILD.gn')
foreach ($Folder in @('webrtc', 'audio', 'video')) {
    $SourceFolder = Join-Path $NativeRoot $Folder
    $TargetFolder = Join-Path $SyncDir $Folder
    New-Item -ItemType Directory -Force -Path $TargetFolder | Out-Null
    Get-ChildItem -LiteralPath $SourceFolder -File |
        Where-Object { $_.Extension -ne '.bak' } |
        Copy-Item -Destination $TargetFolder -Force
}

Push-Location $WebRtcSrc
try {
    Write-Host '[LazyPC] Generating GN build files...' -ForegroundColor Cyan
    & gn gen 'out/Default'
    if ($LASTEXITCODE -ne 0) { throw "gn gen failed with exit code $LASTEXITCODE" }

    Write-Host '[LazyPC] Building //lazypc_native:lazypc_webrtc...' -ForegroundColor Cyan
    & $AutoninjaCommand.Source -C 'out/Default' 'lazypc_native:lazypc_webrtc'
    if ($LASTEXITCODE -ne 0) { throw "Ninja build failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

$BuiltDll = Join-Path $BuildDir 'lazypc_webrtc.dll'
if (-not (Test-Path $BuiltDll)) {
    throw "Build finished, but DLL was not found at '$BuiltDll'. Check the GN target output under '$BuildDir'."
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
try {
    Copy-Item -Force $BuiltDll $OutputDll -ErrorAction Stop
} catch {
    if (Test-Path $OutputDll) {
        throw "DLL was built, but '$OutputDll' could not be replaced. Close LazyPC/Python processes that may have loaded it, then retry. Details: $($_.Exception.Message)"
    }
    throw
}

$CopiedDll = Get-Item $OutputDll
Write-Host "[LazyPC] DLL copied to: $($CopiedDll.FullName)" -ForegroundColor Green
Write-Host "[LazyPC] DLL size: $($CopiedDll.Length) bytes" -ForegroundColor Green
Write-Host '[LazyPC] Build and copy completed successfully.' -ForegroundColor Green
