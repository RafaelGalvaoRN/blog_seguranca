"""Ponto de entrada para servidores de produção (gunicorn/uwsgi).

Exemplo:
    gunicorn wsgi:app --bind 0.0.0.0:8000
"""
from app import app

if __name__ == "__main__":
    app.run()
