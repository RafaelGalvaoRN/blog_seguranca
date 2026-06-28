@echo off
REM Registra a tarefa diaria no Agendador de Tarefas do Windows (usuario atual)
schtasks /Create /TN "BuscadorEmailBlogSeguranca" /TR "\"C:\Users\User\PycharmProjects\blog_seguranca\run_buscador_email.bat\"" /SC DAILY /ST 08:00 /F > "C:\Users\User\PycharmProjects\blog_seguranca\logs\install_result.txt" 2>&1
schtasks /Query /TN "BuscadorEmailBlogSeguranca" /V /FO LIST >> "C:\Users\User\PycharmProjects\blog_seguranca\logs\install_result.txt" 2>&1
type "C:\Users\User\PycharmProjects\blog_seguranca\logs\install_result.txt"
echo.
echo ============================================================
echo Tarefa criada. Pressione qualquer tecla para fechar.
pause >nul
