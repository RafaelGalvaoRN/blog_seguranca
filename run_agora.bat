@echo off
cd /d "C:\Users\User\PycharmProjects\blog_seguranca"
echo Rodando buscador de jurisprudencias...
.venv\Scripts\python.exe buscador_jurisprudencia_email.py
echo.
echo Concluido.
pause
