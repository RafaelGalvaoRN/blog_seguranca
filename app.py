"""Blog de Segurança Pública do RN.

Aplicação Flask com:
  - Área de Notícias
  - Área de Julgados (com seções, busca e filtros)
  - Painel administrativo para inserção fácil de textos

Como rodar:
    python init_db.py     # cria o banco e os dados iniciais (só na 1ª vez)
    python app.py         # inicia o servidor em http://localhost:5000
"""
import html
import os
import uuid
from datetime import datetime

import bleach
from flask import (
    Flask, render_template, request, redirect, url_for, flash, abort
)
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from werkzeug.utils import secure_filename
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from slugify import slugify
from sqlalchemy import or_

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])

from config import Config
from models import db, Usuario, Categoria, Noticia, Julgado, Artigo

TAGS_PERMITIDAS = [
    "p", "br", "b", "strong", "i", "em", "u", "s", "blockquote",
    "h1", "h2", "h3", "h4", "ul", "ol", "li", "a", "img", "span",
    "table", "thead", "tbody", "tr", "th", "td", "hr", "pre", "code",
]
ATRIBUTOS_PERMITIDOS = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
}

EXTENSOES_IMAGEM = {"png", "jpg", "jpeg", "gif", "webp"}
EXPIRA_DIAS = 7   # validade dos links de aprovação por e-mail


def _extensao_permitida(nome_arquivo):
    return (
        "." in nome_arquivo
        and nome_arquivo.rsplit(".", 1)[1].lower() in EXTENSOES_IMAGEM
    )


def limpar_html(texto):
    if not texto:
        return ""
    return bleach.clean(
        texto, tags=TAGS_PERMITIDAS, attributes=ATRIBUTOS_PERMITIDOS, strip=True
    )


def gerar_slug(texto, modelo):
    base = slugify(texto)[:280] or "item"
    slug = base
    i = 2
    while db.session.query(modelo).filter_by(slug=slug).first() is not None:
        slug = f"{base}-{i}"
        i += 1
    return slug


def parse_data(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError:
        return None


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    os.makedirs(os.path.join(app.root_path, "static", "uploads"), exist_ok=True)

    login_manager = LoginManager()
    login_manager.login_view = "admin_login"
    login_manager.login_message = "Faça login para acessar o painel."
    login_manager.init_app(app)

    @app.after_request
    def security_headers(response):
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-eval' https://cdn.quilljs.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.quilljs.com; "
            "img-src 'self' data: https:; "
            "font-src 'self' https://cdn.quilljs.com; "
            "connect-src 'self';"
        )
        return response

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Usuario, int(user_id))

    @app.template_filter("imgsrc")
    def imgsrc(url):
        """Retorna a URL da imagem só se for válida; senão '' (evita thumb quebrado)."""
        if not url:
            return ""
        u = str(url).strip()
        if u.lower() in ("none", "null"):
            return ""
        if not u.startswith(("http://", "https://", "/")):
            return ""
        return u

    @app.context_processor
    def injetar_globais():
        categorias = Categoria.query.order_by(Categoria.ordem, Categoria.nome).all()

        def url_pagina(numero):
            args = request.args.to_dict(flat=True)
            args["page"] = numero
            return url_for(request.endpoint, **args)

        return {
            "menu_categorias": categorias,
            "ano_atual": datetime.now().year,
            "url_pagina": url_pagina,
        }

    @app.route("/")
    def index():
        noticias = (
            Noticia.query.filter_by(publicado=True)
            .order_by(Noticia.criado_em.desc())
            .limit(4)
            .all()
        )
        julgados = (
            Julgado.query.filter_by(publicado=True)
            .order_by(Julgado.criado_em.desc())
            .limit(6)
            .all()
        )
        return render_template("index.html", noticias=noticias, julgados=julgados)

    @app.route("/noticias")
    def noticias():
        page = request.args.get("page", 1, type=int)
        busca = request.args.get("q", "", type=str).strip()
        query = Noticia.query.filter_by(publicado=True)
        if busca:
            termo = f"%{busca}%"
            query = query.filter(
                or_(Noticia.titulo.ilike(termo), Noticia.resumo.ilike(termo))
            )
        pagination = query.order_by(Noticia.criado_em.desc()).paginate(
            page=page, per_page=app.config["ITEMS_PER_PAGE"], error_out=False
        )
        return render_template("noticias.html", pagination=pagination, busca=busca)

    @app.route("/noticia/<slug>")
    def noticia_detalhe(slug):
        noticia = Noticia.query.filter_by(slug=slug, publicado=True).first()
        if not noticia:
            abort(404)
        relacionadas = (
            Noticia.query.filter(Noticia.publicado == True, Noticia.id != noticia.id)
            .order_by(Noticia.criado_em.desc())
            .limit(4)
            .all()
        )
        return render_template(
            "noticia_detalhe.html", noticia=noticia, relacionadas=relacionadas
        )

    # ---- Artigos ----
    @app.route("/artigos")
    def artigos():
        page = request.args.get("page", 1, type=int)
        busca = request.args.get("q", "", type=str).strip()
        query = Artigo.query.filter_by(publicado=True)
        if busca:
            termo = f"%{busca}%"
            query = query.filter(
                or_(Artigo.titulo.ilike(termo), Artigo.resumo.ilike(termo))
            )
        pagination = query.order_by(Artigo.criado_em.desc()).paginate(
            page=page, per_page=app.config["ITEMS_PER_PAGE"], error_out=False
        )
        return render_template("artigos.html", pagination=pagination, busca=busca)

    @app.route("/artigo/<slug>")
    def artigo_detalhe(slug):
        artigo = Artigo.query.filter_by(slug=slug, publicado=True).first()
        if not artigo:
            abort(404)
        relacionados = (
            Artigo.query.filter(Artigo.publicado == True, Artigo.id != artigo.id)
            .order_by(Artigo.criado_em.desc())
            .limit(4)
            .all()
        )
        return render_template(
            "artigo_detalhe.html", artigo=artigo, relacionados=relacionados
        )

    # ---- Sobre / Contato ----
    @app.route("/sobre")
    def sobre():
        return render_template("sobre.html")

    @app.route("/julgados")
    def julgados():
        page = request.args.get("page", 1, type=int)
        busca = request.args.get("q", "", type=str).strip()
        secao = request.args.get("secao", "", type=str).strip()
        tribunal = request.args.get("tribunal", "", type=str).strip()

        query = Julgado.query.filter_by(publicado=True)

        categoria_atual = None
        if secao:
            categoria_atual = Categoria.query.filter_by(slug=secao).first()
            if categoria_atual:
                query = query.filter(Julgado.categoria_id == categoria_atual.id)

        if tribunal:
            query = query.filter(Julgado.tribunal == tribunal)

        if busca:
            termo = f"%{busca}%"
            query = query.filter(
                or_(
                    Julgado.titulo.ilike(termo),
                    Julgado.tese.ilike(termo),
                    Julgado.ementa.ilike(termo),
                    Julgado.tags.ilike(termo),
                    Julgado.relator.ilike(termo),
                    Julgado.numero_processo.ilike(termo),
                )
            )

        pagination = query.order_by(
            Julgado.data_julgamento.desc().nullslast(),
            Julgado.criado_em.desc()
        ).paginate(page=page, per_page=app.config["ITEMS_PER_PAGE"], error_out=False)

        tribunais = [
            t[0] for t in db.session.query(Julgado.tribunal)
            .filter(Julgado.tribunal.isnot(None), Julgado.tribunal != "")
            .distinct().order_by(Julgado.tribunal).all()
        ]

        return render_template(
            "julgados.html",
            pagination=pagination,
            categoria_atual=categoria_atual,
            tribunais=tribunais,
            busca=busca,
            secao=secao,
            tribunal=tribunal,
        )

    @app.route("/julgado/<slug>")
    def julgado_detalhe(slug):
        julgado = Julgado.query.filter_by(slug=slug, publicado=True).first()
        if not julgado:
            abort(404)
        relacionados = (
            Julgado.query.filter(
                Julgado.publicado == True,
                Julgado.categoria_id == julgado.categoria_id,
                Julgado.id != julgado.id,
            )
            .order_by(Julgado.criado_em.desc())
            .limit(5)
            .all()
        )
        return render_template(
            "julgado_detalhe.html", julgado=julgado, relacionados=relacionados
        )

    @app.route("/admin/login", methods=["GET", "POST"])
    @limiter.limit("10 per minute", error_message="Muitas tentativas. Aguarde 1 minuto.")
    def admin_login():
        if current_user.is_authenticated:
            return redirect(url_for("admin_dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            senha = request.form.get("senha", "")
            usuario = Usuario.query.filter_by(username=username).first()
            if usuario and usuario.checar_senha(senha):
                login_user(usuario)
                return redirect(url_for("admin_dashboard"))
            flash("Usuário ou senha inválidos.", "erro")
        return render_template("admin/login.html")

    @app.route("/admin/logout", methods=["POST"])
    @login_required
    def admin_logout():
        logout_user()
        return redirect(url_for("index"))

    @app.route("/admin")
    @login_required
    def admin_dashboard():
        return render_template(
            "admin/dashboard.html",
            total_noticias=Noticia.query.count(),
            total_julgados=Julgado.query.count(),
            total_artigos=Artigo.query.count(),
            total_categorias=Categoria.query.count(),
            ultimas_noticias=Noticia.query.order_by(Noticia.criado_em.desc()).limit(5).all(),
            ultimos_julgados=Julgado.query.order_by(Julgado.criado_em.desc()).limit(5).all(),
        )

    @app.route("/admin/noticias")
    @login_required
    def admin_noticias():
        lista = Noticia.query.order_by(Noticia.criado_em.desc()).all()
        return render_template("admin/noticias_lista.html", noticias=lista)

    @app.route("/admin/noticia/nova", methods=["GET", "POST"])
    @app.route("/admin/noticia/<int:noticia_id>/editar", methods=["GET", "POST"])
    @login_required
    def admin_noticia_form(noticia_id=None):
        noticia = db.session.get(Noticia, noticia_id) if noticia_id else None
        if noticia_id and noticia is None:
            abort(404)

        if request.method == "POST":
            titulo = request.form.get("titulo", "").strip()
            if not titulo:
                flash("O título é obrigatório.", "erro")
                return render_template("admin/noticia_form.html", noticia=noticia)

            if noticia is None:
                noticia = Noticia(slug=gerar_slug(titulo, Noticia))
                db.session.add(noticia)
            noticia.titulo = titulo
            noticia.resumo = request.form.get("resumo", "").strip()
            noticia.conteudo = limpar_html(request.form.get("conteudo", ""))
            noticia.autor = request.form.get("autor", "").strip()
            noticia.publicado = request.form.get("acao") == "publicar"

            arquivo = request.files.get("imagem")
            if arquivo and arquivo.filename:
                if not _extensao_permitida(arquivo.filename):
                    flash("Formato inválido. Use PNG, JPG, GIF ou WebP.", "erro")
                    return render_template("admin/noticia_form.html", noticia=noticia)
                ext = secure_filename(arquivo.filename).rsplit(".", 1)[1].lower()
                nome_seguro = f"{uuid.uuid4().hex}.{ext}"
                pasta = os.path.join(app.root_path, "static", "uploads")
                arquivo.save(os.path.join(pasta, nome_seguro))
                noticia.imagem_url = f"/static/uploads/{nome_seguro}"
            else:
                url_digitada = request.form.get("imagem_url", "").strip()
                if url_digitada:
                    noticia.imagem_url = url_digitada

            db.session.commit()
            if noticia.publicado:
                flash("Notícia publicada com sucesso.", "ok")
            else:
                flash("Notícia salva como rascunho.", "ok")
            return redirect(url_for("admin_noticias"))

        return render_template("admin/noticia_form.html", noticia=noticia)

    @app.route("/admin/noticia/<int:noticia_id>/excluir", methods=["POST"])
    @login_required
    def admin_noticia_excluir(noticia_id):
        noticia = db.session.get(Noticia, noticia_id)
        if noticia:
            db.session.delete(noticia)
            db.session.commit()
            flash("Notícia excluída.", "ok")
        return redirect(url_for("admin_noticias"))

    @app.route("/admin/artigos")
    @login_required
    def admin_artigos():
        lista = Artigo.query.order_by(Artigo.criado_em.desc()).all()
        return render_template("admin/artigos_lista.html", artigos=lista)

    @app.route("/admin/artigo/novo", methods=["GET", "POST"])
    @app.route("/admin/artigo/<int:artigo_id>/editar", methods=["GET", "POST"])
    @login_required
    def admin_artigo_form(artigo_id=None):
        artigo = db.session.get(Artigo, artigo_id) if artigo_id else None
        if artigo_id and artigo is None:
            abort(404)

        if request.method == "POST":
            titulo = request.form.get("titulo", "").strip()
            if not titulo:
                flash("O título é obrigatório.", "erro")
                return render_template("admin/artigo_form.html", artigo=artigo)

            if artigo is None:
                artigo = Artigo(slug=gerar_slug(titulo, Artigo))
                db.session.add(artigo)
            artigo.titulo = titulo
            artigo.resumo = request.form.get("resumo", "").strip()
            artigo.conteudo = limpar_html(request.form.get("conteudo", ""))
            artigo.autor = request.form.get("autor", "").strip()
            artigo.publicado = request.form.get("acao") == "publicar"

            arquivo = request.files.get("imagem")
            if arquivo and arquivo.filename:
                if not _extensao_permitida(arquivo.filename):
                    flash("Formato inválido. Use PNG, JPG, GIF ou WebP.", "erro")
                    return render_template("admin/artigo_form.html", artigo=artigo)
                ext = secure_filename(arquivo.filename).rsplit(".", 1)[1].lower()
                nome_seguro = f"{uuid.uuid4().hex}.{ext}"
                pasta = os.path.join(app.root_path, "static", "uploads")
                arquivo.save(os.path.join(pasta, nome_seguro))
                artigo.imagem_url = f"/static/uploads/{nome_seguro}"
            else:
                url_digitada = request.form.get("imagem_url", "").strip()
                if url_digitada:
                    artigo.imagem_url = url_digitada

            db.session.commit()
            if artigo.publicado:
                flash("Artigo publicado com sucesso.", "ok")
            else:
                flash("Artigo salvo como rascunho.", "ok")
            return redirect(url_for("admin_artigos"))

        return render_template("admin/artigo_form.html", artigo=artigo)

    @app.route("/admin/artigo/<int:artigo_id>/excluir", methods=["POST"])
    @login_required
    def admin_artigo_excluir(artigo_id):
        artigo = db.session.get(Artigo, artigo_id)
        if artigo:
            db.session.delete(artigo)
            db.session.commit()
            flash("Artigo excluído.", "ok")
        return redirect(url_for("admin_artigos"))

    @app.route("/admin/julgados")
    @login_required
    def admin_julgados():
        lista = Julgado.query.order_by(Julgado.criado_em.desc()).all()
        return render_template("admin/julgados_lista.html", julgados=lista)

    @app.route("/admin/julgado/novo", methods=["GET", "POST"])
    @app.route("/admin/julgado/<int:julgado_id>/editar", methods=["GET", "POST"])
    @login_required
    def admin_julgado_form(julgado_id=None):
        julgado = db.session.get(Julgado, julgado_id) if julgado_id else None
        if julgado_id and julgado is None:
            abort(404)
        categorias = Categoria.query.order_by(Categoria.ordem, Categoria.nome).all()

        if request.method == "POST":
            titulo = request.form.get("titulo", "").strip()
            categoria_id = request.form.get("categoria_id", type=int)
            if not titulo or not categoria_id:
                flash("Título e seção são obrigatórios.", "erro")
                return render_template(
                    "admin/julgado_form.html", julgado=julgado, categorias=categorias
                )

            if julgado is None:
                julgado = Julgado(slug=gerar_slug(titulo, Julgado))
                db.session.add(julgado)
            julgado.titulo = titulo
            julgado.categoria_id = categoria_id
            julgado.tribunal = request.form.get("tribunal", "").strip()
            julgado.numero_processo = request.form.get("numero_processo", "").strip()
            julgado.relator = request.form.get("relator", "").strip()
            julgado.orgao_julgador = request.form.get("orgao_julgador", "").strip()
            julgado.data_julgamento = parse_data(request.form.get("data_julgamento", ""))
            julgado.tese = limpar_html(request.form.get("tese", ""))
            julgado.ementa = limpar_html(request.form.get("ementa", ""))
            julgado.conteudo = limpar_html(request.form.get("conteudo", ""))
            julgado.tags = request.form.get("tags", "").strip()
            julgado.publicado = request.form.get("acao") == "publicar"
            db.session.commit()
            if julgado.publicado:
                flash("Julgado publicado com sucesso.", "ok")
            else:
                flash("Julgado salvo como rascunho.", "ok")
            return redirect(url_for("admin_julgados"))

        return render_template(
            "admin/julgado_form.html", julgado=julgado, categorias=categorias
        )

    @app.route("/admin/julgado/<int:julgado_id>/excluir", methods=["POST"])
    @login_required
    def admin_julgado_excluir(julgado_id):
        julgado = db.session.get(Julgado, julgado_id)
        if julgado:
            db.session.delete(julgado)
            db.session.commit()
            flash("Julgado excluído.", "ok")
        return redirect(url_for("admin_julgados"))

    @app.route("/admin/secoes", methods=["GET", "POST"])
    @login_required
    def admin_secoes():
        if request.method == "POST":
            nome = request.form.get("nome", "").strip()
            if nome:
                if Categoria.query.filter_by(nome=nome).first():
                    flash("Já existe uma seção com esse nome.", "erro")
                else:
                    cat = Categoria(
                        nome=nome,
                        slug=gerar_slug(nome, Categoria),
                        descricao=request.form.get("descricao", "").strip(),
                        ordem=request.form.get("ordem", 0, type=int),
                    )
                    db.session.add(cat)
                    db.session.commit()
                    flash("Seção criada com sucesso.", "ok")
            return redirect(url_for("admin_secoes"))

        categorias = Categoria.query.order_by(Categoria.ordem, Categoria.nome).all()
        return render_template("admin/secoes.html", categorias=categorias)

    @app.route("/admin/secao/<int:cat_id>/excluir", methods=["POST"])
    @login_required
    def admin_secao_excluir(cat_id):
        cat = db.session.get(Categoria, cat_id)
        if cat:
            if cat.julgados:
                flash(
                    "Não é possível excluir uma seção que possui julgados. "
                    "Remova ou reatribua os julgados antes.",
                    "erro",
                )
            else:
                db.session.delete(cat)
                db.session.commit()
                flash("Seção excluída.", "ok")
        return redirect(url_for("admin_secoes"))

    @app.route("/admin/conta", methods=["GET", "POST"])
    @login_required
    def admin_conta():
        if request.method == "POST":
            senha_atual = request.form.get("senha_atual", "")
            novo_usuario = request.form.get("username", "").strip()
            nova_senha = request.form.get("nova_senha", "")
            confirma = request.form.get("confirma_senha", "")

            if not current_user.checar_senha(senha_atual):
                flash("Senha atual incorreta.", "erro")
                return redirect(url_for("admin_conta"))

            if novo_usuario and novo_usuario != current_user.username:
                existe = Usuario.query.filter(
                    Usuario.username == novo_usuario,
                    Usuario.id != current_user.id,
                ).first()
                if existe:
                    flash("Já existe um usuário com esse nome.", "erro")
                    return redirect(url_for("admin_conta"))
                current_user.username = novo_usuario

            if nova_senha:
                if nova_senha != confirma:
                    flash("A confirmação não confere com a nova senha.", "erro")
                    return redirect(url_for("admin_conta"))
                if len(nova_senha) < 6:
                    flash("A nova senha deve ter pelo menos 6 caracteres.", "erro")
                    return redirect(url_for("admin_conta"))
                current_user.set_senha(nova_senha)

            db.session.commit()
            flash("Dados da conta atualizados com sucesso.", "ok")
            return redirect(url_for("admin_conta"))

        return render_template("admin/conta.html")

    # -------------------------------------------------------------------
    # IMPORTAÇÃO (recebe itens do buscador → cria notícias como RASCUNHO)
    # -------------------------------------------------------------------
    @app.route("/importar", methods=["POST"])
    @csrf.exempt
    def importar():
        token = request.form.get("token", "")
        esperado = app.config.get("IMPORT_TOKEN", "")
        if not esperado or token != esperado:
            abort(403)

        titulos = request.form.getlist("titulo")
        links = request.form.getlist("link")
        resumos = request.form.getlist("resumo")
        fontes = request.form.getlist("fonte")
        corpos = request.form.getlist("corpo")
        imagens = request.form.getlist("imagem")

        criadas = 0
        ignoradas = 0
        for i, titulo in enumerate(titulos):
            titulo = (titulo or "").strip()
            if not titulo:
                continue
            link = (links[i] if i < len(links) else "").strip()
            resumo = (resumos[i] if i < len(resumos) else "").strip()
            fonte = (fontes[i] if i < len(fontes) else "").strip()
            corpo = (corpos[i] if i < len(corpos) else "").strip()
            imagem = (imagens[i] if i < len(imagens) else "").strip()

            existe = None
            if link:
                existe = Noticia.query.filter(
                    or_(Noticia.titulo == titulo, Noticia.conteudo.ilike(f"%{link}%"))
                ).first()
            else:
                existe = Noticia.query.filter_by(titulo=titulo).first()
            if existe:
                ignoradas += 1
                continue

            partes = []
            if corpo:
                partes.append(corpo)
            elif resumo:
                partes.append(f"<p>{resumo}</p>")
            if link:
                rotulo = fonte or link
                partes.append(
                    f'<p>Fonte: <a href="{link}" target="_blank" '
                    f'rel="noopener">{rotulo}</a></p>'
                )
            conteudo = limpar_html("".join(partes)) or "<p>(sem conteúdo)</p>"

            noticia = Noticia(
                titulo=titulo,
                slug=gerar_slug(titulo, Noticia),
                resumo=resumo[:480],
                conteudo=conteudo,
                imagem_url=(imagem or None),
                autor=fonte or "Importado",
                publicado=False,
            )
            db.session.add(noticia)
            criadas += 1

        db.session.commit()
        return render_template(
            "importado.html",
            criadas=criadas, ignoradas=ignoradas, total=len(titulos)
        )

    # -------------------------------------------------------------------
    # IMPORTAÇÃO DE JURISPRUDÊNCIA (recebe itens do buscador_juris.py)
    # -------------------------------------------------------------------
    @app.route("/importar_juris", methods=["POST"])
    @csrf.exempt
    def importar_juris():
        token = request.form.get("token", "")
        esperado = app.config.get("IMPORT_TOKEN", "")
        if not esperado or token != esperado:
            abort(403)

        tribunais   = request.form.getlist("tribunal")
        processos   = request.form.getlist("processo")
        classes     = request.form.getlist("classe")
        orgaos      = request.form.getlist("orgao")
        magistrados = request.form.getlist("magistrado")
        htmls       = request.form.getlist("html")
        textos      = request.form.getlist("texto")

        # Categoria reservada para importações automáticas.
        # O admin reatribui a seção definitiva ao revisar o rascunho.
        cat = Categoria.query.filter_by(slug="importados").first()
        if not cat:
            cat = Categoria(
                nome="Importados",
                slug="importados",
                descricao="Julgados importados automaticamente — reatribuir seção antes de publicar.",
                ordem=99,
            )
            db.session.add(cat)
            db.session.flush()

        criados   = 0
        ignorados = 0
        total     = len(tribunais)

        for i, trib in enumerate(tribunais):
            processo  = (processos[i]   if i < len(processos)   else "").strip()
            classe    = (classes[i]     if i < len(classes)     else "").strip()
            orgao     = (orgaos[i]      if i < len(orgaos)      else "").strip()
            mag       = (magistrados[i] if i < len(magistrados) else "").strip()
            html_teor = (htmls[i]       if i < len(htmls)       else "").strip()
            texto     = (textos[i]      if i < len(textos)      else "").strip()
            trib      = trib.strip()

            if not processo and not html_teor:
                ignorados += 1
                continue

            if processo and Julgado.query.filter_by(numero_processo=processo).first():
                ignorados += 1
                continue

            partes_titulo = []
            if classe:
                partes_titulo.append(classe)
            if processo:
                partes_titulo.append(processo)
            titulo_base = " – ".join(partes_titulo) if partes_titulo else "Julgado importado"
            if trib:
                titulo_base = f"{titulo_base} ({trib})"

            tese = texto[:500].strip() if texto else ""

            julgado = Julgado(
                titulo=titulo_base[:300],
                slug=gerar_slug(titulo_base, Julgado),
                categoria_id=cat.id,
                tribunal=trib[:60]         if trib     else None,
                numero_processo=processo[:120] if processo else None,
                relator=mag[:160]          if mag      else None,
                orgao_julgador=orgao[:160] if orgao    else None,
                tese=tese,
                conteudo=limpar_html(html_teor) or texto or "(sem conteúdo)",
                publicado=False,
            )
            db.session.add(julgado)
            criados += 1

        db.session.commit()
        return render_template(
            "importado_juris.html",
            criados=criados, ignorados=ignorados, total=total,
        )

    # -------------------------------------------------------------------
    # APROVAÇÃO POR E-MAIL — publica notícia ao clicar no link do e-mail
    # -------------------------------------------------------------------
    @app.route("/aprovar/<token>")
    def aprovar_noticia(token):
        s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
        try:
            dados = s.loads(
                token, salt="aprovar-noticia", max_age=EXPIRA_DIAS * 24 * 3600
            )
        except SignatureExpired:
            return render_template("aprovado.html",
                                   erro="Link expirado. Rode o buscador_email novamente.")
        except BadSignature:
            return render_template("aprovado.html",
                                   erro="Link inválido ou adulterado.")

        titulo = (dados.get("t") or "").strip()
        if not titulo:
            return render_template("aprovado.html", erro="Dados incompletos no link.")

        # Deduplicação: evita publicar a mesma matéria duas vezes
        if Noticia.query.filter_by(titulo=titulo).first():
            return render_template("aprovado.html",
                                   aviso="Esta matéria já foi publicada anteriormente.")

        resumo    = dados.get("r", "")
        link_orig = dados.get("l", "")
        fonte     = dados.get("f", "")
        imagem    = dados.get("i", "") or None

        conteudo = f"<p>{resumo}</p>"
        if link_orig:
            fonte_label = fonte or link_orig
            conteudo += (
                f'<p>Fonte: <a href="{link_orig}" target="_blank" '
                f'rel="noopener">{fonte_label}</a></p>'
            )

        noticia = Noticia(
            titulo=titulo,
            slug=gerar_slug(titulo, Noticia),
            resumo=resumo,
            conteudo=limpar_html(conteudo),
            imagem_url=imagem,
            autor=fonte or "Importado",
            publicado=True,
        )
        db.session.add(noticia)
        db.session.commit()

        return render_template("aprovado.html", noticia=noticia)


    # -------------------------------------------------------------------
    # APROVAÇÃO DE JURISPRUDÊNCIA POR E-MAIL — publica julgado via link
    # -------------------------------------------------------------------
    @app.route("/aprovar_juris/<token>")
    def aprovar_juris(token):
        s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
        try:
            dados = s.loads(token, salt="aprovar-juris", max_age=604800)
        except (SignatureExpired, BadSignature):
            return "Link inválido ou expirado.", 400

        existente = Julgado.query.filter_by(
            numero_processo=dados["numero_processo"]
        ).first()
        if existente:
            return render_template(
                "aprovado.html",
                mensagem="Esta jurisprudência já está cadastrada no site.",
            )

        cat = Categoria.query.filter_by(nome=dados["secao_nome"]).first()
        if not cat:
            cat = Categoria.query.filter_by(nome="Importados").first()

        base_slug = slugify(dados["numero_processo"])
        slug = base_slug
        contador = 1
        while Julgado.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{contador}"
            contador += 1

        titulo = (
            f"{dados['classe_judicial']} — {dados['numero_processo']}"
            if dados.get("classe_judicial")
            else dados["numero_processo"]
        )

        novo = Julgado(
            titulo=titulo,
            slug=slug,
            categoria_id=cat.id if cat else None,
            tribunal=dados.get("tribunal", ""),
            numero_processo=dados["numero_processo"],
            relator=dados.get("magistrado", ""),
            orgao_julgador=dados.get("orgao_julgador", ""),
            tese=limpar_html(dados.get("tese", "")),
            ementa=limpar_html(dados.get("ementa", "")),
            conteudo=limpar_html(dados.get("conteudo", "")),
            tags=dados.get("secao_nome", ""),
            publicado=True,
        )
        db.session.add(novo)
        db.session.commit()
        return render_template(
            "aprovado.html",
            mensagem="Jurisprudência publicada com sucesso!",
        )

    # -------------------------------------------------------------------
    # VISUALIZAÇÃO DO INTEIRO TEOR — exibe o texto antes de publicar
    # -------------------------------------------------------------------
    @app.route("/ver_juris/<token>")
    def ver_juris(token):
        s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
        try:
            dados = s.loads(token, salt="aprovar-juris", max_age=604800)
        except SignatureExpired:
            return "<p>Link expirado.</p>", 400
        except BadSignature:
            return "<p>Link inv&aacute;lido.</p>", 400

        proc     = html.escape(dados.get("numero_processo", "") or "")
        orgao    = html.escape(dados.get("orgao_julgador", "") or "")
        relator  = html.escape(dados.get("magistrado", "") or "")
        classe   = html.escape(dados.get("classe_judicial", "") or "")
        conteudo = html.escape(dados.get("conteudo", "") or "")
        link_publicar = f"/aprovar_juris/{token}"

        meta_parts = []
        if classe:
            meta_parts.append(classe)
        if orgao:
            meta_parts.append(orgao)
        if relator:
            meta_parts.append(f"Rel. {relator}")
        meta_str = " &middot; ".join(meta_parts)

        return f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Inteiro Teor &mdash; {proc}</title>
  <style>
    body {{{{ font-family: Segoe UI, Arial, sans-serif; background: #f4f6f9; margin: 0; padding: 24px 16px; }}}}
    .card {{{{ background: #fff; border: 1px solid #d9dee6; border-radius: 8px; padding: 24px; max-width: 800px; margin: 0 auto; }}}}
    h1 {{{{ color: #0b2545; font-size: 20px; margin: 0 0 8px; }}}}
    .meta {{{{ color: #5a6675; font-size: 13px; margin-bottom: 16px; }}}}
    .conteudo {{{{ white-space: pre-wrap; font-size: 14px; line-height: 1.7; color: #33414f;
                 border-top: 1px solid #e5e9f0; padding-top: 16px; margin-top: 16px; }}}}
    .btns {{{{ margin-top: 24px; display: flex; gap: 12px; flex-wrap: wrap; }}}}
    a.btn {{{{ display: inline-block; padding: 10px 20px; border-radius: 6px;
             font-weight: 700; font-size: 14px; text-decoration: none; }}}}
    a.btn-voltar {{{{ background: #5a6675; color: #fff; }}}}
    a.btn-publicar {{{{ background: #b8860b; color: #fff; }}}}
  </style>
</head>
<body>
  <div class="card">
    <h1>Processo {proc}</h1>
    <div class="meta">{meta_str}</div>
    <div class="conteudo">{conteudo}</div>
    <div class="btns">
      <a class="btn btn-voltar" href="javascript:history.back()">&#8592; Voltar</a>
      <a class="btn btn-publicar" href="{link_publicar}">&#10003; Publicar esta jurisprud&ecirc;ncia</a>
    </div>
  </div>
</body>
</html>"""

    @app.errorhandler(404)
    def nao_encontrado(e):
        return render_template("404.html"), 404

    return app


app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, port=5000)
