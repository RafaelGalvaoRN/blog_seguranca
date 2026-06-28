@echo off
echo Configurando agendamento do buscador de jurisprudencias...

REM Busca matutina - 07:00
schtasks /create /tn "BlogSeguranca_Juris_Manha" /tr "\"C:\Users\User\PycharmProjects\blog_seguranca\.venv\Scripts\python.exe\" \"C:\Users\User\PycharmProjects\blog_seguranca\buscador_jurisprudencia_email.py\"" /sc daily /st 07:00 /f

REM Busca noturna - 22:00
schtasks /create /tn "BlogSeguranca_Juris_Noite" /tr "\"C:\Users\User\PycharmProjects\blog_seguranca\.venv\Scripts\python.exe\" \"C:\Users\User\PycharmProjects\blog_seguranca\buscador_jurisprudencia_email.py\"" /sc daily /st 22:00 /f

echo.
echo Tarefas criadas:
echo  - BlogSeguranca_Juris_Manha (07:00 diario)
echo  - BlogSeguranca_Juris_Noite (22:00 diario)
pause
