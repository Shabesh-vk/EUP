param(
    [switch]$Rebuild,
    [switch]$Fast = $true,
    [switch]$Preview
)

if ($Preview) {
    Write-Host "Opening Instant AI Conversation Dashboard Preview in browser..." -ForegroundColor Green
    Start-Process "C:\Users\Nathan\.gemini\antigravity\brain\28324b7d-9085-4c1e-ac84-611b9fe5bf1b\ai_conversation_preview.html"
    exit 0
}

# EUP Desktop Editor Launcher with AI Conversation Tab
$env:FFMPEG_DIR = "N:\Concat\ffmpeg-dev"
$env:LIBCLANG_PATH = "N:\llvm\bin"
$env:ORT_DIR = "N:\Concat\onnxruntime-win-x64-1.28.0"
$env:ORT_LIB_LOCATION = "N:\Concat\onnxruntime-win-x64-1.28.0\lib"
$env:ORT_PREFER_DYNAMIC_LINK = "1"
$env:SHERPA_ONNX_LIB_DIR = "N:\Concat\sherpa-libs"
$env:PATH = "N:\Concat\ffmpeg-dev\bin;N:\llvm\bin;N:\Concat\onnxruntime-win-x64-1.28.0\lib;N:\Concat\sherpa-dlls;C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;" + $env:PATH

Set-Location -Path "$PSScriptRoot\src"

$exePath = "$PSScriptRoot\src\target\quick\eup.exe"

if (-not $Rebuild -and (Test-Path $exePath)) {
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  FAST LAUNCH: Starting EUP Desktop Editor (Instant Mode)" -ForegroundColor Green
    Write-Host "  Binary: $exePath" -ForegroundColor DarkGray
    Write-Host "  (To do a full cargo rebuild instead, run: .\run_ui.ps1 -Rebuild)" -ForegroundColor DarkGray
    Write-Host "  (To preview the dashboard in 0ms, run: .\run_ui.ps1 -Preview)" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Cyan
    & $exePath $args
} else {
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  REBUILD MODE: Compiling and launching EUP via cargo dev..." -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Cyan
    cargo dev $args
}
