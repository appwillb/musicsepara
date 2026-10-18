@echo off
setlocal enabledelayedexpansion
title tunemusic Pro - Compilador de Instalador Oficial
cd /d "%~dp0"

echo ==============================================================================
echo                 tunemusic Pro - BUILDER DE INSTALADOR OFICIAL
echo ==============================================================================
echo.

:: 1. Localizar Compilador C# (csc.exe)
set CSC="C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist %CSC% (
    echo [ERRO] Compilador csc.exe nao encontrado em %CSC%
    pause
    exit /b 1
)

:: 2. Compilar Launcher Nativo tunemusic.exe
echo [1/3] Compilando Launcher Nativo Windows (tunemusic.exe)...
%CSC% /target:winexe /win32icon:app_icon.ico /out:tunemusic.exe launcher\Program.cs launcher\AssemblyInfo.cs >nul
if %errorlevel% neq 0 (
    echo [ERRO] Falha ao compilar tunemusic.exe!
    pause
    exit /b 1
)
echo       [OK] tunemusic.exe compilado com sucesso! (Icone oficial e metadados embutidos)

:: 3. Localizar Compilador Inno Setup (ISCC.exe)
set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if not exist %ISCC% (
    echo [AVISO] Inno Setup 6 nao encontrado nos caminhos padroes.
    echo         Instalando automaticamente via winget...
    winget install --id JRSoftware.InnoSetup --silent --accept-source-agreements --accept-package-agreements
    set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
)

if not exist %ISCC% (
    echo [ERRO] Nao foi possivel localizar o ISCC.exe. Instale o Inno Setup 6 manualmente: https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

:: 4. Compilar Instalador Oficial
echo.
echo [2/3] Empacotando e comprimindo instalador (LZMA2 Ultra Solid)...
if not exist "dist_installer" mkdir "dist_installer"
%ISCC% installer\tunemusic_setup.iss
if %errorlevel% neq 0 (
    echo [ERRO] Falha ao compilar instalador no Inno Setup!
    pause
    exit /b 1
)

echo.
echo [3/3] Concluido com sucesso!
echo ==============================================================================
echo Instalador gerado em: dist_installer\tunemusic_Pro_v1.0_Instalador.exe
echo ==============================================================================
echo.
pause
