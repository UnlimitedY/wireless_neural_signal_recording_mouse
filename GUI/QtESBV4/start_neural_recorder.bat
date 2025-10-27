@echo off
echo Starting Neural Recorder GUI...
cd /d "%~dp0"
if exist "dist\NeuralRecorderGUI.exe" (
    start "" "dist\NeuralRecorderGUI.exe"
) else (
    echo Error: NeuralRecorderGUI.exe not found!
    pause
)
