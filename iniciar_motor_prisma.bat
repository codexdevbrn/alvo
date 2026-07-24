@echo off
title Motor Prisma (Python/FastAPI)
echo =======================================================
echo Iniciando o Motor do Projeto Prisma
echo =======================================================
echo O servidor estara rodando em segundo plano (porta 8003).
echo Mantenha esta janela aberta enquanto quiser usar o sistema.
echo.
cd backend
python -m uvicorn main:app --port 8003 --host 127.0.0.1
pause
