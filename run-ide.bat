@echo off
rem Starts the TI-89 IDE on Windows:  run-ide.bat [file.c | file.s | file.asm]
cd /d "%~dp0"
if exist python\python.exe (
    python\python.exe ide89\ide89.py %*
) else (
    py -3 ide89\ide89.py %*
)
