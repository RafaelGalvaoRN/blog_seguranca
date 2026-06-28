@echo off
cd /d "C:\Users\User\PycharmProjects\blog_seguranca"
echo Instalando spaCy...
.venv\Scripts\pip install spacy --quiet
echo.
echo Baixando modelo portugues (pt_core_news_lg)...
.venv\Scripts\python -m spacy download pt_core_news_lg
echo.
echo Pronto! spaCy instalado com sucesso.
pause
