@echo off
title UNIVA Network v3.0 - Unified Sovereign L1 Node
chcp 65001 >nul
cd /d "%~dp0"

echo =================================================================
echo    UNIVA NETWORK v3.0.0 - Sovereign Layer 1 Node
echo    PWA / Cüzdan: http://127.0.0.1:5050
echo    P2P WebSocket: ws://0.0.0.0:5051
echo =================================================================
echo.
python run.py --node
pause
