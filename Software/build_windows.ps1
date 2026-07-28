param(
    [string]$ColmapDir = "",
    [string]$BrushDir = "",
    [string]$FfmpegDir = ""
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
$BrushExecutable = Get-ChildItem -Path $BrushDir -Include "brush.exe", "brush-app.exe", "brush_app.exe" -File -Recurse | Select-Object -First 1
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
    throw "brush.exe, brush-app.exe, or brush_app.exe was not found below '$BrushDir'."
}
if (-not $FfmpegExecutable -or -not $FfprobeExecutable) {
    throw "ffmpeg.exe and ffprobe.exe must both exist below '$FfmpegDir'."
}
if ($ColmapQtCore -and -not $ColmapQtPlatformPlugin) {
    throw "The selected COLMAP build uses Qt, but platforms\qwindows.dll is missing. Keep the complete official COLMAP archive or use a headless COLMAP build."
}

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$ColmapFeatureHelp = & $ColmapExecutable.FullName feature_extractor -h 2>&1 | Out-String
$ColmapFeatureExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference
if (
    $ColmapFeatureExitCode -ne 0 -or
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
$BundledColmap = Join-Path $OutputDir "_internal\tools\colmap"
$BundledBrush = Join-Path $OutputDir "_internal\tools\brush"
$BundledFfmpeg = Join-Path $OutputDir "_internal\tools\ffmpeg"

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
Add-ToolBundle -Source $ColmapDir -Destination $BundledColmap
Add-ToolBundle -Source $BrushDir -Destination $BundledBrush
Add-ToolBundle -Source $FfmpegDir -Destination $BundledFfmpeg

foreach ($BundledTool in @($BundledColmap, $BundledBrush, $BundledFfmpeg)) {
    if (-not (Test-Path $BundledTool -PathType Container)) {
        throw "The packaged application is incomplete: '$BundledTool' is missing."
    }
}

$PackagedColmapExecutable = Get-ChildItem -Path $BundledColmap -Filter "colmap.exe" -File -Recurse |
    Select-Object -First 1
if (-not $PackagedColmapExecutable) {
    throw "The packaged application is incomplete: colmap.exe is missing."
}

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$PackagedColmapHelp = & $PackagedColmapExecutable.FullName -h 2>&1 | Out-String
$PackagedColmapExitCode = $LASTEXITCODE
$ErrorActionPreference = $PreviousErrorActionPreference
if (
    $PackagedColmapExitCode -ne 0 -or
    $PackagedColmapHelp -notmatch "COLMAP"
) {
    throw "The packaged COLMAP executable failed its startup check with exit code $PackagedColmapExitCode. Check the Windows Code Integrity log for a blocked DLL."
}

Write-Host "Windows application folder created: $OutputDir"
Write-Host "Executable: $OutputExe"
Write-Host "Distribute the complete GaussianReconstruction folder, not the executable alone."
