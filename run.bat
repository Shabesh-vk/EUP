@echo off
set "FFMPEG_DIR=N:\Concat\ffmpeg-dev"
set "LIBCLANG_PATH=N:\llvm\bin"
set "ORT_DIR=N:\Concat\onnxruntime-win-x64-1.28.0"
set "ORT_LIB_LOCATION=N:\Concat\onnxruntime-win-x64-1.28.0\lib"
set "ORT_PREFER_DYNAMIC_LINK=1"
set "SHERPA_ONNX_LIB_DIR=N:\Concat\sherpa-libs"
set "PATH=N:\Concat\ffmpeg-dev\bin;N:\llvm\bin;N:\Concat\onnxruntime-win-x64-1.28.0\lib;N:\Concat\sherpa-dlls;C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;%PATH%"

cd /d "%~dp0src"

if "%~1"=="" (
    echo Starting Concat with quick profile...
    cargo dev
) else (
    cargo %*
)
