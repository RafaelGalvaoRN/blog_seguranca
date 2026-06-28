@echo off
REM Wrapper para rodar o buscador_email.py com o Python do .venv
cd /d "C:\Users\User\PycharmProjects\blog_seguranca"
".venv\Scripts\python.exe" "buscador_email.py" >> "logs\buscador_email.log" 2>&1
