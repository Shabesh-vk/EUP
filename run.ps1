param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ArgsList
)

$env:FFMPEG_DIR = "N:\Concat\ffmpeg-dev"
$env:LIBCLANG_PATH = "N:\llvm\bin"
$env:ORT_DIR = "N:\Concat\onnxruntime-win-x64-1.28.0"
$env:ORT_LIB_LOCATION = "N:\Concat\onnxruntime-win-x64-1.28.0\lib"
$env:ORT_PREFER_DYNAMIC_LINK = "1"
$env:SHERPA_ONNX_LIB_DIR = "N:\Concat\sherpa-libs"
$env:PATH = "N:\Concat\ffmpeg-dev\bin;N:\llvm\bin;N:\Concat\onnxruntime-win-x64-1.28.0\lib;N:\Concat\sherpa-dlls;C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;" + $env:PATH

Set-Location -Path "$PSScriptRoot\src"

if (-not $ArgsList -or $ArgsList.Count -eq 0) {
    Write-Host "Running Concat with quick profile (cargo dev)..." -ForegroundColor Cyan
    cargo dev
} else {
    Write-Host "Running: cargo $($ArgsList -join ' ')..." -ForegroundColor Cyan
    & cargo $ArgsList
}
