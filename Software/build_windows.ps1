param(
    [string]$ColmapDir = "",
    [string]$BrushDir = "",
    [string]$FfmpegDir = "",
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallationRoot = Split-Path -Parent $ProjectDir

if (-not $ColmapDir) {
    $ColmapDir = Join-Path $InstallationRoot "Colmap"
}
if (-not $BrushDir) {
    $BrushDir = Join-Path $InstallationRoot "Brush"
}
if (-not $FfmpegDir) {
    $FfmpegDir = Join-Path $InstallationRoot "FFmpeg"
}

if (-not (Test-Path $ColmapDir -PathType Container)) {
    throw "COLMAP directory not found at '$ColmapDir'. Download and extract a Windows release into the 'Colmap' directory."
}
if (-not (Test-Path $BrushDir -PathType Container)) {
    throw "Brush directory not found at '$BrushDir'. Download and extract the Windows x64 Brush release into the 'Brush' directory."
}
if (-not (Test-Path $FfmpegDir -PathType Container)) {
    throw "FFmpeg directory not found at '$FfmpegDir'. Download a Windows FFmpeg build containing ffmpeg.exe and ffprobe.exe, or pass -FfmpegDir."
}

$ColmapDir = (Resolve-Path $ColmapDir).Path
$BrushDir = (Resolve-Path $BrushDir).Path
$FfmpegDir = (Resolve-Path $FfmpegDir).Path
$ColmapExecutable = Get-ChildItem -Path $ColmapDir -Filter "colmap.exe" -File -Recurse | Select-Object -First 1
$BrushExecutable = Get-ChildItem -Path $BrushDir -Include "brush.exe", "brush-app.exe" -File -Recurse | Select-Object -First 1
$FfmpegExecutable = Get-ChildItem -Path $FfmpegDir -Filter "ffmpeg.exe" -File -Recurse | Select-Object -First 1
$FfprobeExecutable = Get-ChildItem -Path $FfmpegDir -Filter "ffprobe.exe" -File -Recurse | Select-Object -First 1
$ColmapQtCore = Get-ChildItem -Path $ColmapDir -Filter "Qt*Core.dll" -File -Recurse | Select-Object -First 1
$ColmapQtPlatformPlugin = Get-ChildItem -Path $ColmapDir -Filter "qwindows.dll" -File -Recurse |
    Where-Object { $_.Directory.Name -eq "platforms" } |
    Select-Object -First 1

if (-not $ColmapExecutable) {
    throw "colmap.exe was not found below '$ColmapDir'."
}
if (-not $BrushExecutable) {
    throw "brush.exe or brush-app.exe was not found below '$BrushDir'."
}
if (-not $FfmpegExecutable -or -not $FfprobeExecutable) {
    throw "ffmpeg.exe and ffprobe.exe must both exist below '$FfmpegDir'."
}
if ($ColmapQtCore -and -not $ColmapQtPlatformPlugin) {
    throw "The selected COLMAP build uses Qt, but platforms\qwindows.dll is missing. Keep the complete official COLMAP archive or use a headless COLMAP build."
}

$ColmapFeatureHelp = & $ColmapExecutable.FullName feature_extractor -h 2>&1 | Out-String
if (
    $LASTEXITCODE -ne 0 -or
    $ColmapFeatureHelp -notmatch [regex]::Escape("--FeatureExtraction.num_threads")
) {
    throw "The selected COLMAP build is incompatible. COLMAP 4.1.1 or newer is required."
}

$VirtualEnvironment = Join-Path $ProjectDir ".venv-windows"
$Python = Join-Path $VirtualEnvironment "Scripts\python.exe"

if (-not (Test-Path $Python -PathType Leaf)) {
    py -3.12 -m venv $VirtualEnvironment
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the Python 3.12 virtual environment."
    }
}

& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Could not upgrade pip in the Windows build environment."
}
& $Python -m pip install -r (Join-Path $ProjectDir "requirements-windows-build.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Could not install the Windows build dependencies."
}

$env:COLMAP_BUNDLE_DIR = $ColmapDir
$env:BRUSH_BUNDLE_DIR = $BrushDir
$env:FFMPEG_BUNDLE_DIR = $FfmpegDir

Push-Location $ProjectDir
try {
    & $Python -m PyInstaller --noconfirm --clean windows.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }
} finally {
    Pop-Location
    Remove-Item Env:COLMAP_BUNDLE_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:BRUSH_BUNDLE_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:FFMPEG_BUNDLE_DIR -ErrorAction SilentlyContinue
}

$OutputDir = Join-Path $ProjectDir "dist\GaussianReconstruction"
$OutputExe = Join-Path $OutputDir "GaussianReconstruction.exe"
$BundledColmap = Join-Path $OutputDir "_internal\tools\colmap"
$BundledBrush = Join-Path $OutputDir "_internal\tools\brush"
$BundledFfmpeg = Join-Path $OutputDir "_internal\tools\ffmpeg"

if (-not (Test-Path $OutputExe -PathType Leaf)) {
    throw "The packaged application executable was not created at '$OutputExe'."
}
foreach ($BundledTool in @($BundledColmap, $BundledBrush, $BundledFfmpeg)) {
    if (-not (Test-Path $BundledTool -PathType Container)) {
        throw "The packaged application is incomplete: '$BundledTool' is missing."
    }
}

Write-Host "Windows application folder created: $OutputDir"
Write-Host "Executable: $OutputExe"
Write-Host "Distribute the complete GaussianReconstruction folder, not the executable alone."

if (-not $SkipZip) {
    $ArchivePath = Join-Path (Split-Path -Parent $OutputDir) "GaussianReconstruction-Windows-x64.zip"
    Compress-Archive -Path $OutputDir -DestinationPath $ArchivePath -CompressionLevel Optimal -Force

    $Archive = Get-Item $ArchivePath
    $ArchiveHash = (Get-FileHash -Path $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $DecimalMegabytes = [math]::Round($Archive.Length / 1000000, 2)
    $BinaryMebibytes = [math]::Round($Archive.Length / 1MB, 2)
    $HashPath = "$ArchivePath.sha256"
    Set-Content -Path $HashPath -Value "$ArchiveHash  $($Archive.Name)" -Encoding ascii

    Write-Host "Release archive: $ArchivePath"
    Write-Host "Archive size: $($Archive.Length) bytes ($DecimalMegabytes MB / $BinaryMebibytes MiB)"
    Write-Host "SHA-256: $ArchiveHash"
    Write-Host "Checksum file: $HashPath"
}
