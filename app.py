"""Blog de Segurança Pública do RN.

Aplicação Flask com:
  - Área de Notícias
  - Área de Julgados (com seções, busca e filtros)
  - Painel administrativo para inserção fácil de textos

Como rodar:
    python init_db.py     # cria o banco e os dados iniciais (só na 1ª vez)
    python app.py         # inicia o servidor em http://localhost:5000
"""
import os
from datetime import datetime

import bleach
from flask import (
    Flask, render_template, request, redirect, url_for, flash, abort
)
from werkzeug.utils import secure_filename
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from slugify import slugify
from sqlalchemy import or_

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
    os.makedirs(os.path.join(app.root_path, "static", "uploads"), exist_ok=True)

    login_manager = LoginManager()
    login_manager.login_view = "admin_login"
    login_manager.login_message = "Faça login para acessar o painel."
    login_manager.init_app(app)

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

    @app.route("/admin/logout")
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
            noticia.publicado = request.form.get("publicado") == "on"

            arquivo = request.files.get("imagem")
            if arquivo and arquivo.filename:
                if not _extensao_permitida(arquivo.filename):
                    flash("Formato inválido. Use PNG, JPG, GIF ou WebP.", "erro")
                    return render_template("admin/noticia_form.html", noticia=noticia)
                nome_seguro = secure_filename(arquivo.filename)
                pasta = os.path.join(app.root_path, "static", "uploads")
                arquivo.save(os.path.join(pasta, nome_seguro))
                noticia.imagem_url = f"/static/uploads/{nome_seguro}"
            else:
                url_digitada = request.form.get("imagem_url", "").strip()
                if url_digitada:
                    noticia.imagem_url = url_digitada

            db.session.commit()
            flash("Notícia salva com sucesso.", "ok")
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
            artigo.publicado = request.form.get("publicado") == "on"

            arquivo = request.files.get("imagem")
            if arquivo and arquivo.filename:
                if not _extensao_permitida(arquivo.filename):
                    flash("Formato inválido. Use PNG, JPG, GIF ou WebP.", "erro")
                    return render_template("admin/artigo_form.html", artigo=artigo)
                nome_seguro = secure_filename(arquivo.filename)
                pasta = os.path.join(app.root_path, "static", "uploads")
                arquivo.save(os.path.join(pasta, nome_seguro))
                artigo.imagem_url = f"/static/uploads/{nome_seguro}"
            else:
                url_digitada = request.form.get("imagem_url", "").strip()
                if url_digitada:
                    artigo.imagem_url = url_digitada

            db.session.commit()
            flash("Artigo salvo com sucesso.", "ok")
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
            julgado.publicado = request.form.get("publicado") == "on"
            db.session.commit()
            flash("Julgado salvo com sucesso.", "ok")
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
    def importar():
        token = request.form.get("token", "")
        esperado = app.config.get("IMPORT_TOKEN", "")
        if not esperado or token != esperado:
            abort(403)

        titulos = request.form.getlist("titulo")
        links = request.form.getlist("link")
        resumos = request.form.getlist("resumo")
        fontes = request.form.getlist("fonte")

        criadas = 0
        ignoradas = 0
        for i, titulo in enumerate(titulos):
            titulo = (titulo or "").strip()
            if not titulo:
                continue
            link = (links[i] if i < len(links) else "").strip()
            resumo = (resumos[i] if i < len(resumos) else "").strip()
            fonte = (fontes[i] if i < len(fontes) else "").strip()

            # Evita duplicar: mesmo título ou mesmo link já importado.
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
            if resumo:
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
                autor=fonte or "Importado",
                publicado=False,  # entra como RASCUNHO
            )
            db.session.add(noticia)
            criadas += 1

        db.session.commit()
        return render_template(
            "importado.html",
            criadas=criadas, ignoradas=ignoradas, total=len(titulos)
        )

    @app.errorhandler(404)
    def nao_encontrado(e):
        return render_template("404.html"), 404

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
