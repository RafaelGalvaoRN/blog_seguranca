"""Configuração da aplicação.

Os valores podem ser sobrescritos por variáveis de ambiente (arquivo .env),
o que é útil ao hospedar o blog na internet.
"""
import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    # Troque a SECRET_KEY em produção (defina a variável de ambiente SECRET_KEY).
    SECRET_KEY = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")

    # Banco de dados. Por padrão usa SQLite (arquivo local). Para hospedar,
    # você pode apontar DATABASE_URL para um Postgres, por exemplo.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(basedir, "blog.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Credenciais do primeiro administrador (criadas automaticamente na 1ª execução).
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

    # Itens por página nas listagens.
    ITEMS_PER_PAGE = int(os.environ.get("ITEMS_PER_PAGE", "10"))

    # Upload de imagens: tamanho máximo 10 MB.
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024

    # Token para importação de notícias pelo buscador (defina no .env do servidor).
    # Se ficar vazio, a importação fica desativada (endpoint recusa).
    IMPORT_TOKEN = os.environ.get("IMPORT_TOKEN", "")
