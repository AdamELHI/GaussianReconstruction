param(
    [string]$ColmapDir = "",
    [string]$ColmapNoCudaDir = "",
    [string]$BrushDir = "",
    [string]$FfmpegDir = "",
    [string]$SplatTransformVersion = "3.1.7"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallationRoot = Split-Path -Parent $ProjectDir

if (-not $ColmapDir) {
    $ColmapDir = Join-Path $InstallationRoot "Colmap"
}
if (-not $ColmapNoCudaDir) {
    $ColmapNoCudaDir = Join-Path $InstallationRoot "Colmap_no_cuda"
}
if (-not $BrushDir) {
    $BrushDir = Join-Path $InstallationRoot "Brush"
}
if (-not $FfmpegDir) {
    $FfmpegDir = Join-Path $InstallationRoot "FFmpeg"
}

if (-not (Test-Path $ColmapDir -PathType Container)) {
    throw "CUDA COLMAP directory not found at '$ColmapDir'. Download and extract the CUDA Windows release into the 'Colmap' directory."
}
if (-not (Test-Path $ColmapNoCudaDir -PathType Container)) {
    throw "CPU COLMAP directory not found at '$ColmapNoCudaDir'. Download and extract the no-CUDA Windows release into the 'Colmap_no_cuda' directory."
}
if (-not (Test-Path $BrushDir -PathType Container)) {
    throw "Brush directory not found at '$BrushDir'. Download and extract the Windows x64 Brush release into the 'Brush' directory."
}
if (-not (Test-Path $FfmpegDir -PathType Container)) {
    throw "FFmpeg directory not found at '$FfmpegDir'. Download a Windows FFmpeg build containing ffmpeg.exe and ffprobe.exe, or pass -FfmpegDir."
}
if (-not $SplatTransformVersion) {
    throw "SplatTransformVersion must not be empty."
}

$ColmapDir = (Resolve-Path $ColmapDir).Path
$ColmapNoCudaDir = (Resolve-Path $ColmapNoCudaDir).Path
$BrushDir = (Resolve-Path $BrushDir).Path
$FfmpegDir = (Resolve-Path $FfmpegDir).Path
$NodeExecutable = Get-Command "node.exe" -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
$NpmExecutable = Get-Command "npm.cmd" -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
$ColmapExecutable = Get-ChildItem -Path $ColmapDir -Filter "colmap.exe" -File -Recurse | Select-Object -First 1
$ColmapNoCudaExecutable = Get-ChildItem -Path $ColmapNoCudaDir -Filter "colmap.exe" -File -Recurse | Select-Object -First 1
$BrushExecutable = Get-ChildItem -Path $BrushDir -Include "brush.exe", "brush-app.exe", "brush_app.exe" -File -Recurse | Select-Object -First 1
$FfmpegExecutable = Get-ChildItem -Path $FfmpegDir -Filter "ffmpeg.exe" -File -Recurse | Select-Object -First 1
$FfprobeExecutable = Get-ChildItem -Path $FfmpegDir -Filter "ffprobe.exe" -File -Recurse | Select-Object -First 1
$ColmapQtCore = Get-ChildItem -Path $ColmapDir -Filter "Qt*Core.dll" -File -Recurse | Select-Object -First 1
$ColmapQtPlatformPlugin = Get-ChildItem -Path $ColmapDir -Filter "qwindows.dll" -File -Recurse |
    Where-Object { $_.Directory.Name -eq "platforms" } |
    Select-Object -First 1
$ColmapNoCudaQtCore = Get-ChildItem -Path $ColmapNoCudaDir -Filter "Qt*Core.dll" -File -Recurse | Select-Object -First 1
$ColmapNoCudaQtPlatformPlugin = Get-ChildItem -Path $ColmapNoCudaDir -Filter "qwindows.dll" -File -Recurse |
    Where-Object { $_.Directory.Name -eq "platforms" } |
    Select-Object -First 1

if (-not $ColmapExecutable) {
    throw "CUDA colmap.exe was not found below '$ColmapDir'."
}
if (-not $ColmapNoCudaExecutable) {
    throw "CPU colmap.exe was not found below '$ColmapNoCudaDir'."
}
if (-not $BrushExecutable) {
    throw "brush.exe, brush-app.exe, or brush_app.exe was not found below '$BrushDir'."
}
if (-not $FfmpegExecutable -or -not $FfprobeExecutable) {
    throw "ffmpeg.exe and ffprobe.exe must both exist below '$FfmpegDir'."
}
if (-not $NodeExecutable -or -not $NpmExecutable) {
    throw "Node.js and npm are required to bundle splat-transform. Install a 64-bit Node.js release and ensure node.exe and npm.cmd are in PATH."
}
if ($ColmapQtCore -and -not $ColmapQtPlatformPlugin) {
    throw "The CUDA COLMAP build uses Qt, but platforms\qwindows.dll is missing. Keep the complete official archive."
}
if ($ColmapNoCudaQtCore -and -not $ColmapNoCudaQtPlatformPlugin) {
    throw "The CPU COLMAP build uses Qt, but platforms\qwindows.dll is missing. Keep the complete official archive."
}

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$ColmapFeatureHelp = & $ColmapExecutable.FullName feature_extractor -h 2>&1 | Out-String
$ColmapFeatureExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference
if (
    $ColmapFeatureExitCode -ne 0 -or
    $ColmapFeatureHelp -notmatch [regex]::Escape("--FeatureExtraction.num_threads") -or
    $ColmapFeatureHelp -notmatch "with CUDA"
) {
    throw "The CUDA COLMAP build is incompatible. A CUDA-enabled COLMAP 4.1.1 or newer build is required."
}

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$ColmapNoCudaFeatureHelp = & $ColmapNoCudaExecutable.FullName feature_extractor -h 2>&1 | Out-String
$ColmapNoCudaFeatureExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference
if (
    $ColmapNoCudaFeatureExitCode -ne 0 -or
    $ColmapNoCudaFeatureHelp -notmatch [regex]::Escape("--FeatureExtraction.num_threads") -or
    $ColmapNoCudaFeatureHelp -notmatch "without CUDA"
) {
    throw "The CPU COLMAP build is incompatible. A no-CUDA COLMAP 4.1.1 or newer build is required."
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

$OpenCvPackages = @(
    "opencv-python",
    "opencv-python-headless",
    "opencv-contrib-python",
    "opencv-contrib-python-headless"
)

Write-Host "Removing existing OpenCV Python packages."
& $Python -m pip uninstall --yes @OpenCvPackages
if ($LASTEXITCODE -ne 0) {
    throw "Could not remove the existing OpenCV Python packages."
}

& $Python -m pip install -r (Join-Path $InstallationRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Could not install the Windows build dependencies."
}

Push-Location $ProjectDir
try {
    & $Python -m PyInstaller --noconfirm --clean windows.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }
} finally {
    Pop-Location
}

$OutputDir = Join-Path $ProjectDir "dist\GaussianReconstruction"
$OutputExe = Join-Path $OutputDir "GaussianReconstruction.exe"
$BundledToolsRoot = Join-Path $OutputDir "_internal\tools"
$BundledColmapCuda = Join-Path $OutputDir "_internal\tools\colmap-cuda"
$BundledColmapNoCuda = Join-Path $OutputDir "_internal\tools\colmap-no-cuda"
$BundledBrush = Join-Path $OutputDir "_internal\tools\brush"
$BundledFfmpeg = Join-Path $OutputDir "_internal\tools\ffmpeg"
$BundledSplatTransform = Join-Path $OutputDir "_internal\tools\splat-transform"

if (-not (Test-Path $OutputExe -PathType Leaf)) {
    throw "The packaged application executable was not created at '$OutputExe'."
}

function Add-ToolBundle {
    param(
        [Parameter(Mandatory)]
        [string]$Source,
        [Parameter(Mandatory)]
        [string]$Destination
    )

    if (Test-Path $Destination) {
        throw "The tool destination already exists after the PyInstaller build: '$Destination'."
    }

    $Source = (Resolve-Path $Source).Path.TrimEnd("\")
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null

    Get-ChildItem -LiteralPath $Source -Directory -Recurse -Force |
        Sort-Object { $_.FullName.Length } |
        ForEach-Object {
            $RelativePath = $_.FullName.Substring($Source.Length).TrimStart("\")
            New-Item -ItemType Directory -Path (Join-Path $Destination $RelativePath) -Force |
                Out-Null
        }

    Get-ChildItem -LiteralPath $Source -File -Recurse -Force |
        ForEach-Object {
            $RelativePath = $_.FullName.Substring($Source.Length).TrimStart("\")
            $DestinationFile = Join-Path $Destination $RelativePath
            try {
                New-Item -ItemType HardLink -Path $DestinationFile -Target $_.FullName |
                    Out-Null
            } catch {
                throw "Could not preserve Windows trust metadata for '$($_.FullName)'. Keep the tool directory on the same NTFS volume as the build output. $($_.Exception.Message)"
            }
        }
}

New-Item -ItemType Directory -Path $BundledToolsRoot -Force | Out-Null
Write-Host "Adding external tools without PyInstaller processing."
Add-ToolBundle -Source $ColmapDir -Destination $BundledColmapCuda
Add-ToolBundle -Source $ColmapNoCudaDir -Destination $BundledColmapNoCuda
Add-ToolBundle -Source $BrushDir -Destination $BundledBrush
Add-ToolBundle -Source $FfmpegDir -Destination $BundledFfmpeg

Write-Host "Installing splat-transform $SplatTransformVersion into the application folder."
New-Item -ItemType Directory -Path $BundledSplatTransform -Force | Out-Null
& $NpmExecutable.Source install `
    --prefix $BundledSplatTransform `
    --omit=dev `
    --no-audit `
    --no-fund `
    "@playcanvas/splat-transform@$SplatTransformVersion"
if ($LASTEXITCODE -ne 0) {
    throw "npm failed to install @playcanvas/splat-transform@$SplatTransformVersion."
}

$BundledSplatTransformBin = Join-Path $BundledSplatTransform "node_modules\.bin"
$PackagedSplatTransform = Join-Path $BundledSplatTransformBin "splat-transform.cmd"
$BundledNodeExecutable = Join-Path $BundledSplatTransformBin "node.exe"
if (-not (Test-Path $PackagedSplatTransform -PathType Leaf)) {
    throw "The packaged application is incomplete: splat-transform.cmd is missing."
}
try {
    Copy-Item -LiteralPath $NodeExecutable.Source -Destination $BundledNodeExecutable
} catch {
    throw "Could not bundle node.exe for splat-transform. $($_.Exception.Message)"
}

foreach ($BundledTool in @($BundledColmapCuda, $BundledColmapNoCuda, $BundledBrush, $BundledFfmpeg, $BundledSplatTransform)) {
    if (-not (Test-Path $BundledTool -PathType Container)) {
        throw "The packaged application is incomplete: '$BundledTool' is missing."
    }
}

$PackagedColmapCudaExecutable = Get-ChildItem -Path $BundledColmapCuda -Filter "colmap.exe" -File -Recurse |
    Select-Object -First 1
$PackagedColmapNoCudaExecutable = Get-ChildItem -Path $BundledColmapNoCuda -Filter "colmap.exe" -File -Recurse |
    Select-Object -First 1
if (-not $PackagedColmapCudaExecutable -or -not $PackagedColmapNoCudaExecutable) {
    throw "The packaged application is incomplete: a CUDA or CPU colmap.exe is missing."
}

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$PackagedColmapCudaHelp = & $PackagedColmapCudaExecutable.FullName -h 2>&1 | Out-String
$PackagedColmapCudaExitCode = $LASTEXITCODE
$PackagedColmapNoCudaHelp = & $PackagedColmapNoCudaExecutable.FullName -h 2>&1 | Out-String
$PackagedColmapNoCudaExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference
if (
    $PackagedColmapCudaExitCode -ne 0 -or
    $PackagedColmapCudaHelp -notmatch "with CUDA"
) {
    throw "The packaged CUDA COLMAP executable failed its startup check with exit code $PackagedColmapCudaExitCode. Check the Windows Code Integrity log for a blocked DLL."
}
if (
    $PackagedColmapNoCudaExitCode -ne 0 -or
    $PackagedColmapNoCudaHelp -notmatch "without CUDA"
) {
    throw "The packaged CPU COLMAP executable failed its startup check with exit code $PackagedColmapNoCudaExitCode. Check the Windows Code Integrity log for a blocked DLL."
}

$SplatTransformVersionCommand = "`"$PackagedSplatTransform`" --version 2>&1"
$PackagedSplatTransformVersion = & $env:ComSpec /d /c $SplatTransformVersionCommand |
    Out-String
$PackagedSplatTransformExitCode = $LASTEXITCODE
if (
    $PackagedSplatTransformExitCode -ne 0 -or
    -not $PackagedSplatTransformVersion.Trim()
) {
    throw "The packaged splat-transform command failed its startup check with exit code $PackagedSplatTransformExitCode."
}

Write-Host "Windows application folder created: $OutputDir"
Write-Host "Executable: $OutputExe"
Write-Host "Bundled COLMAP: CUDA and CPU variants"
Write-Host "Bundled splat-transform: $($PackagedSplatTransformVersion.Trim())"
Write-Host "Distribute the complete GaussianReconstruction folder, not the executable alone."
