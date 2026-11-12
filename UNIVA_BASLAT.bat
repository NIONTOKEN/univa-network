@echo off
title UNIVA Network v4.0 - Sovereign Layer-1 Mainnet Node
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE=C:\Users\DMC BİLGİSAYAR\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

echo =================================================================
echo    UNIVA NETWORK v4.0.0 - Sovereign Layer-1 Mainnet Node
echo    Yerel Dugum / Cuzdan : http://127.0.0.1:5050
echo    EVM JSON-RPC (210001): http://127.0.0.1:5050/rpc
echo    P2P WebSocket        : ws://0.0.0.0:5051
echo =================================================================
echo.

echo [1/4] Port 5050 ve 5051 temizleniyor...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5050 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5051 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

echo [2/4] Global HTTPS Cloudflare Tuneli baslatiliyor (Tum telefon ve cihazlar icin)...
start "UNIVA Global HTTPS Tunnel" /MIN "%PYTHON_EXE%" start_tunnel.py

echo [3/4] Telegram Mini-App Botu (@UnivaNetworkBot) baslatiliyor...
start "UNIVA Telegram Bot" /MIN "%PYTHON_EXE%" -u telegram_bot.py

echo [4/4] UNIVA L1 Ana Dugumu (Port 5050) baslatiliyor...
start "" "http://127.0.0.1:5050"
"%PYTHON_EXE%" run.py --node
pause
