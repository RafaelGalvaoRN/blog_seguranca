"""Inicializa o banco de dados, cria o administrador e as seções iniciais.

Rode UMA vez antes de iniciar o blog:
    python init_db.py

Pode rodar de novo com segurança: não duplica dados que já existem.
"""
from datetime import date

from slugify import slugify
from sqlalchemy import text

from app import create_app
from models import db, Usuario, Categoria, Noticia, Julgado

# Seções iniciais da área de Julgados (você pode editar/adicionar no painel).
SECOES_INICIAIS = [
    ("Busca e Apreensão", "Busca domiciliar, pessoal, veicular e mandados."),
    ("Prisão", "Flagrante, preventiva, temporária e relaxamento."),
    ("Abordagem Policial", "Fundada suspeita, revista e abordagem."),
    ("Uso da Força", "Legítima defesa, uso de arma e proporcionalidade."),
    ("Armas e Munições", "Porte, posse e Estatuto do Desarmamento."),
    ("Drogas", "Tráfico, porte para consumo e Lei 11.343/06."),
    ("Audiência de Custódia", "Prazos, nulidades e regras da custódia."),
    ("Provas", "Cadeia de custódia, ilicitude e validade probatória."),
    ("Crimes Contra a Vida", "Homicídio, feminicídio e tribunal do júri."),
    ("Processo Penal", "Procedimentos, recursos e nulidades em geral."),
]


def _migrar_colunas(engine):
    """Adiciona colunas novas a tabelas existentes (sem apagar dados)."""
    with engine.connect() as conn:
        # imagem_url em noticias (adicionada na v2)
        cols = [row[1] for row in conn.execute(
            text("PRAGMA table_info(noticias)")
        )]
        if "imagem_url" not in cols:
            conn.execute(text(
                "ALTER TABLE noticias ADD COLUMN imagem_url VARCHAR(500)"
            ))
            conn.commit()
            print("Migração: coluna imagem_url adicionada à tabela noticias.")
        if "url_origem" not in cols:
            conn.execute(text(
                "ALTER TABLE noticias ADD COLUMN url_origem VARCHAR(500)"
            ))
            conn.commit()
            print("Migração: coluna url_origem adicionada à tabela noticias.")


def main():
    app = create_app()
    with app.app_context():
        db.create_all()
        _migrar_colunas(db.engine)

        # --- Administrador ---
        if Usuario.query.first() is None:
            admin = Usuario(
                username=app.config["ADMIN_USERNAME"],
                nome="Administrador",
            )
            admin.set_senha(app.config["ADMIN_PASSWORD"])
            db.session.add(admin)
            print(f"Administrador criado: {app.config['ADMIN_USERNAME']} / "
                  f"{app.config['ADMIN_PASSWORD']}  (troque a senha!)")

        # --- Seções ---
        ordem = 0
        for nome, desc in SECOES_INICIAIS:
            if Categoria.query.filter_by(nome=nome).first() is None:
                db.session.add(Categoria(
                    nome=nome, slug=slugify(nome), descricao=desc, ordem=ordem
                ))
            ordem += 1
        db.session.commit()

        # --- Conteúdo de exemplo (apenas se ainda não houver nada) ---
        if Noticia.query.first() is None:
            db.session.add(Noticia(
                titulo="Bem-vindo ao portal de Segurança Pública do RN",
                slug=slugify("bem-vindo-ao-portal-de-seguranca-publica-do-rn"),
                resumo="Espaço de notícias e jurisprudência para policiais "
                       "militares e civis do Rio Grande do Norte.",
                conteudo="<p>Este portal reúne <strong>notícias</strong> da "
                         "área de segurança pública e uma base de "
                         "<strong>julgados</strong> organizada por temas como "
                         "busca e apreensão, prisão, abordagem policial e "
                         "outros.</p><p>Use o menu para navegar e a busca para "
                         "encontrar rapidamente o que precisa.</p>",
                autor="Equipe Editorial",
            ))

        if Julgado.query.first() is None:
            cat_busca = Categoria.query.filter_by(nome="Busca e Apreensão").first()
            if cat_busca:
                db.session.add(Julgado(
                    titulo="Busca pessoal exige fundada suspeita concreta",
                    slug=slugify("busca-pessoal-exige-fundada-suspeita-concreta"),
                    categoria_id=cat_busca.id,
                    tribunal="STJ",
                    numero_processo="HC 000000/RN",
                    relator="Min. Exemplo",
                    orgao_julgador="Sexta Turma",
                    data_julgamento=date(2025, 3, 10),
                    tese="A busca pessoal depende de elementos concretos de "
                         "fundada suspeita, não bastando a sensação subjetiva "
                         "do agente.",
                    ementa="<p>Exemplo de ementa. Edite ou exclua este julgado "
                           "pelo painel administrativo.</p>",
                    tags="busca pessoal, fundada suspeita, abordagem",
                ))

        db.session.commit()
        print("Banco inicializado com sucesso.")


if __name__ == "__main__":
    main()
