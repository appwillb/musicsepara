@echo off
title StagePrompter + VocalRemover Desktop Studio
cd /d "%~dp0"

echo ========================================================
echo   STAGEPROMPTER + VOCAL REMOVER - STUDIO WORKSTATION
echo ========================================================
echo.

:: 1. Verificar se o servidor Python ja esta rodando na porta 8000
netstat -ano | findstr :8000 | findstr LISTENING >nul
if %errorlevel% neq 0 (
    echo [1/2] Iniciando Servidor Studio Local...
    start /b "" ".venv\Scripts\python.exe" server.py
    timeout /t 2 /nobreak >nul
) else (
    echo [1/2] Servidor Studio ativo na porta 8000.
)

:: 2. Iniciar no PC em Modo Aplicativo Desktop Standalone (Sem bordas de navegador)
echo [2/2] Abrindo Estacao Desktop...
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --app="http://127.0.0.1:8000/" --window-size=1440,900 --start-maximized
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --app="http://127.0.0.1:8000/" --window-size=1440,900 --start-maximized
) else if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --app="http://127.0.0.1:8000/" --window-size=1440,900 --start-maximized
) else if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files\Microsoft\Edge\Application\msedge.exe" --app="http://127.0.0.1:8000/" --window-size=1440,900 --start-maximized
) else (
    start "" "http://127.0.0.1:8000/"
)

echo.
echo Studio Desktop aberto com sucesso!
exit
