"""Modelos de dados do blog de Segurança Pública."""
from datetime import datetime, date

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class Usuario(UserMixin, db.Model):
    """Administrador que pode inserir notícias e julgados."""
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    nome = db.Column(db.String(120))
    senha_hash = db.Column(db.String(255), nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def checar_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)


class Categoria(db.Model):
    """Seções da área de Julgados (Busca e apreensão, Prisão, etc)."""
    __tablename__ = "categorias"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), unique=True, nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    descricao = db.Column(db.String(255))
    ordem = db.Column(db.Integer, default=0)

    julgados = db.relationship("Julgado", backref="categoria", lazy=True)

    @property
    def total_julgados(self):
        return Julgado.query.filter_by(
            categoria_id=self.id, publicado=True
        ).count()


class Noticia(db.Model):
    """Notícia da área de Notícias."""
    __tablename__ = "noticias"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(280), unique=True, nullable=False)
    resumo = db.Column(db.String(500))
    conteudo = db.Column(db.Text, nullable=False)
    imagem_url = db.Column(db.String(500))
    url_origem = db.Column(db.String(500))   # URL da matéria na fonte original
    autor = db.Column(db.String(120))
    publicado = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Artigo(db.Model):
    """Artigo (texto autoral / doutrina) da área de Artigos."""
    __tablename__ = "artigos"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(280), unique=True, nullable=False)
    resumo = db.Column(db.String(500))
    conteudo = db.Column(db.Text, nullable=False)
    imagem_url = db.Column(db.String(500))
    autor = db.Column(db.String(120))
    publicado = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Julgado(db.Model):
    """Julgado (jurisprudência) da área de Julgados."""
    __tablename__ = "julgados"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(300), nullable=False)
    slug = db.Column(db.String(330), unique=True, nullable=False)

    categoria_id = db.Column(
        db.Integer, db.ForeignKey("categorias.id"), nullable=False
    )

    tribunal = db.Column(db.String(60))          # STF, STJ, TJRN, TJ, etc.
    numero_processo = db.Column(db.String(120))  # nº do processo / recurso
    relator = db.Column(db.String(160))
    orgao_julgador = db.Column(db.String(160))   # Turma, Câmara, Plenário...
    data_julgamento = db.Column(db.Date)

    tese = db.Column(db.Text)        # tese/destaque (frase-chave)
    ementa = db.Column(db.Text)      # resumo/ementa
    conteudo = db.Column(db.Text)    # inteiro teor / comentários
    tags = db.Column(db.String(400)) # palavras-chave separadas por vírgula

    publicado = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @property
    def lista_tags(self):
        if not self.tags:
            return []
        return [t.strip() for t in self.tags.split(",") if t.strip()]
