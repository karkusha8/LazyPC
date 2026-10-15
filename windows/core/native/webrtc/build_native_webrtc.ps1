$ErrorActionPreference = 'Stop'

# Build the native bridge from the canonical sources in the LazyPC monorepo.
# WebRTC itself remains an external checkout because GN must run from its root.
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$NativeSource = $PSScriptRoot
$WindowsRoot = Join-Path $ProjectRoot 'windows'
$WebRtcSrc = if ($env:WEBRTC_SRC) { $env:WEBRTC_SRC } else { 'C:\Dev\webrtc\src' }
$WebRtcSrc = [System.IO.Path]::GetFullPath($WebRtcSrc)
$BuildDir = Join-Path $WebRtcSrc 'out\Default'
$SyncDir = Join-Path $WebRtcSrc 'lazypc_native'
$OutputDir = Join-Path $WindowsRoot 'bin'
$OutputDll = Join-Path $OutputDir 'lazypc_webrtc.dll'

if (-not (Test-Path (Join-Path $WebRtcSrc 'webrtc.gni'))) {
    throw "WebRTC source root not found at '$WebRtcSrc'. Set WEBRTC_SRC to the directory containing webrtc.gni."
}
if (-not (Get-Command gn -ErrorAction SilentlyContinue)) {
    throw 'gn was not found in PATH. Open a Developer/depot_tools shell or add depot_tools to PATH.'
}
if (-not (Get-Command ninja -ErrorAction SilentlyContinue)) {
    throw 'ninja was not found in PATH. Open a Developer/depot_tools shell or add depot_tools to PATH.'
}

New-Item -ItemType Directory -Force -Path $SyncDir | Out-Null
foreach ($File in @('BUILD.gn', 'native_peer.cc', 'native_peer.h', 'wasapi_loopback_audio.cc', 'wasapi_loopback_audio.h')) {
    Copy-Item -Force (Join-Path $NativeSource $File) (Join-Path $SyncDir $File)
}

Push-Location $WebRtcSrc
try {
    Write-Host '[LazyPC] Generating GN build files...' -ForegroundColor Cyan
    & gn gen 'out/Default'
    if ($LASTEXITCODE -ne 0) { throw "gn gen failed with exit code $LASTEXITCODE" }

    Write-Host '[LazyPC] Building //lazypc_native:lazypc_webrtc...' -ForegroundColor Cyan
    & autoninja -C 'out/Default' 'lazypc_native:lazypc_webrtc'
    if ($LASTEXITCODE -ne 0) { throw "autoninja failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

# The GN target is configured to emit the DLL at this known path.
# Avoid `gn desc` here: depot_tools may fail to locate `gn` even after a
# successful `gn gen` and build.
$BuiltDll = Join-Path $BuildDir 'lazypc_webrtc.dll'

if (-not (Test-Path $BuiltDll)) {
    throw "Build succeeded, but the DLL was not found at '$BuiltDll'. Check the GN target output."
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# A running LazyPC process may have the DLL loaded, in which case Windows
# refuses to overwrite it. Do not stop the user's process automatically.
try {
    Copy-Item -Force $BuiltDll $OutputDll -ErrorAction Stop
} catch {
    if (Test-Path $OutputDll) {
        throw "The DLL was built successfully, but the project copy could not be replaced: '$OutputDll'. It is probably loaded by a running LazyPC/Python process. Close LazyPC and any Python agent using it, then run this build script again. Original error: $($_.Exception.Message)"
    }
    throw
}

$CopiedDll = Get-Item $OutputDll
Write-Host "[LazyPC] DLL copied to: $($CopiedDll.FullName)" -ForegroundColor Green
Write-Host "[LazyPC] DLL size: $($CopiedDll.Length) bytes" -ForegroundColor Green
Write-Host '[LazyPC] Build and copy completed successfully.' -ForegroundColor Green
