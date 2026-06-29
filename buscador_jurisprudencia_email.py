"""
buscador_jurisprudencia_email.py — Busca jurisprudências via Ollama + TJRN e
envia e-mail com links de aprovação de um clique.

Fluxo:
  1. Garante que o Ollama está rodando (inicia se necessário)
  2. Escolhe uma seção jurídica aleatória
  3. Pede ao Ollama expressões de busca para o tema
  4. Busca no TJRN com cada expressão (via coletar_tjrn)
  5. Deduplica e limita a 15 resultados
  6. Gera tokens assinados e envia e-mail HTML com botão "Publicar"

Rodar:
    python buscador_jurisprudencia_email.py

Agendar no Task Scheduler do Windows para rodar 3x ao dia.

Variáveis de ambiente (.env):
    EMAIL_USER, EMAIL_APP_PASSWORD, EMAIL_DEST
    SITE_URL, SECRET_KEY
    OLLAMA_MODEL   (padrão: gemma4:12b)
"""

import html
import os
import random
import requests
import smtplib
import subprocess
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote as urlquote

# spaCy carregado sob demanda (evita custo de startup se não for usar)
_nlp = None

from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer

from coletores.tjrn import coletar as coletar_tjrn

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ── Configuração ──────────────────────────────────────────────────────────────
SITE_URL      = os.getenv("SITE_URL", "https://rafaelgalvao.pythonanywhere.com")
SECRET_KEY    = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao")
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("EMAIL_USER", "")
SMTP_PASS     = os.getenv("EMAIL_APP_PASSWORD", "")
EMAIL_DEST    = os.getenv("EMAIL_DEST", "")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "gemma4:12b")
OLLAMA_URL    = "http://localhost:11434"

EXPIRA_DIAS   = 7
MAX_RESULTADOS = 5

SECOES = [
    "Busca e Apreensão",
    "Prisão",
    "Abordagem Policial",
    "Uso da Força",
    "Armas e Munições",
    "Drogas",
    "Audiência de Custódia",
    "Provas",
    "Crimes Contra a Vida",
    "Processo Penal",
]


# ── 1. Ollama ─────────────────────────────────────────────────────────────────

def garantir_ollama():
    """Verifica se o Ollama está rodando; se não, inicia e aguarda até 20s."""
    try:
        requests.get(OLLAMA_URL, timeout=3)
        print("  Ollama já está rodando.")
        return
    except Exception:
        pass

    print("  Iniciando Ollama...")
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for i in range(20):
        time.sleep(1)
        try:
            requests.get(OLLAMA_URL, timeout=2)
            print(f"  Ollama pronto (após {i + 1}s).")
            return
        except Exception:
            pass
    raise RuntimeError("Ollama não iniciou em 20 segundos.")


# ── 2. Expressões de busca via Ollama ─────────────────────────────────────────

def gerar_expressoes(secao):
    """Pede ao Ollama de 2 a 4 expressões de busca para o tema."""
    prompt = (
        f'Você é um assistente jurídico. Gere de 2 a 4 expressões de busca '
        f'(máximo 2 palavras cada) para pesquisar jurisprudências favoráveis '
        f'à ação policial sobre o tema: "{secao}".\n'
        f'Retorne APENAS as expressões, uma por linha, sem numeração, sem explicações.'
    )

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    texto = resp.json()["message"]["content"]

    expressoes = [
        linha.strip()
        for linha in texto.splitlines()
        if linha.strip()
    ]
    return expressoes[:4]


# ── 3. Coleta e deduplicação ──────────────────────────────────────────────────

def coletar_jurisprudencias(expressoes):
    """Busca no TJRN com todas as expressões em uma única chamada; deduplica por numero_processo."""
    termo_busca = ", ".join(expressoes)
    print(f"  Buscando: '{termo_busca}' ...")

    try:
        itens = coletar_tjrn(termo=termo_busca, max_pages=2)
        print(f"    {len(itens)} resultado(s)")
    except Exception as e:
        print(f"    ERRO: {e}")
        return []

    vistos = set()
    resultados = []
    for item in itens:
        proc = (item.get("numero_processo") or "").strip()
        chave = proc or item.get("inteiro_teor_texto", "")[:80]
        if chave and chave not in vistos:
            vistos.add(chave)
            resultados.append(item)
        if len(resultados) >= MAX_RESULTADOS:
            break

    return resultados


# ── 4. Anonimização de nomes ─────────────────────────────────────────────────

def _get_nlp():
    """Carrega o modelo spaCy português (apenas uma vez por execução)."""
    global _nlp
    if _nlp is None:
        try:
            import spacy
        except ImportError:
            raise RuntimeError(
                "spaCy não instalado. Execute:\n"
                "  .venv\\Scripts\\pip install spacy\n"
                "  .venv\\Scripts\\python -m spacy download pt_core_news_lg"
            )
        for modelo in ("pt_core_news_lg", "pt_core_news_sm"):
            try:
                _nlp = spacy.load(modelo)
                print(f"  spaCy: modelo '{modelo}' carregado.")
                break
            except OSError:
                continue
        if _nlp is None:
            raise RuntimeError(
                "Nenhum modelo português encontrado. Execute:\n"
                "  .venv\\Scripts\\python -m spacy download pt_core_news_lg"
            )
    return _nlp


def anonimizar(texto):
    """Substitui nomes de pessoas (PER) por [NOME 1], [NOME 2], …"""
    if not texto:
        return texto
    try:
        nlp = _get_nlp()
        # spaCy processa até 5000 chars para performance
        doc = nlp(texto[:5000])
        nomes = {}
        contador = 1
        for ent in doc.ents:
            if ent.label_ == "PER":
                nome = ent.text.strip()
                if nome and nome not in nomes:
                    nomes[nome] = f"[NOME {contador}]"
                    contador += 1
        # substitui do maior para o menor (evita substituições parciais)
        for nome in sorted(nomes, key=len, reverse=True):
            texto = texto.replace(nome, nomes[nome])
        return texto
    except Exception as e:
        print(f"  [AVISO] Erro na anonimização: {e}")
        return texto


# ── 5. Tokens de aprovação ────────────────────────────────────────────────────

def gerar_token(item, secao_nome):
    """Gera token assinado com os dados do julgado."""
    s = URLSafeTimedSerializer(SECRET_KEY)
    teor = item.get("inteiro_teor_texto") or ""
    dados = {
        "numero_processo":  (item.get("numero_processo") or "")[:120],
        "tribunal":         (item.get("tribunal") or "")[:60],
        "orgao_julgador":   (item.get("orgao_julgador") or "")[:160],
        "magistrado":       (item.get("magistrado") or "")[:160],
        "classe_judicial":  (item.get("classe_judicial") or "")[:80],
        "secao_nome":       secao_nome,
        "tese":             teor[:1000],   # ementa/resumo → campo Tese/Destaque
        "ementa":           teor[:1000],   # idem no campo Ementa
        "conteudo":         teor[:8000],   # inteiro teor (limite para URL não estourar)
    }
    return s.dumps(dados, salt="aprovar-juris")


# ── 5. E-mail HTML ────────────────────────────────────────────────────────────

def gerar_html_email(itens, secao_nome, expressoes=None):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    base = SITE_URL.rstrip("/")
    termos_str = html.escape(", ".join(expressoes)) if expressoes else "—"

    cards = ""
    for item in itens:
        token = gerar_token(item, secao_nome)
        link_aprovar = f"{base}/aprovar_juris/{urlquote(token, safe='')}"
        teor = anonimizar(item.get("inteiro_teor_texto") or "")
        trecho = html.escape(teor[:300])
        proc = html.escape(item.get("numero_processo") or "(sem número)")
        orgao = html.escape(item.get("orgao_julgador") or "")
        magistrado = html.escape(item.get("magistrado") or "")
        classe = html.escape(item.get("classe_judicial") or "")

        cards += f"""
<div style="background:#fff;border:1px solid #d9dee6;border-left:4px solid #b8860b;
            border-radius:8px;padding:16px 20px;margin-bottom:14px;">
  <div style="font-size:11px;color:#5a6675;text-transform:uppercase;
              letter-spacing:.4px;margin-bottom:4px;">
    TJRN &middot; {classe}
  </div>
  <h3 style="margin:0 0 6px;font-size:15px;line-height:1.35;color:#0b2545;">
    Processo {proc}
  </h3>
  <div style="font-size:12px;color:#5a6675;margin-bottom:8px;">
    {orgao} &middot; Rel. {magistrado}
  </div>
  <p style="margin:0 0 14px;color:#33414f;font-size:13px;line-height:1.5;">
    {trecho}{"&hellip;" if len(teor) > 300 else ""}
  </p>
  <a href="{html.escape(link_aprovar, True)}"
     style="display:inline-block;background:#b8860b;color:#fff;text-decoration:none;
            padding:9px 18px;border-radius:6px;font-weight:700;font-size:14px;">
    &#10003; Publicar Jurisprud&ecirc;ncia
  </a>
  <div style="margin-top:12px;border-top:1px solid #e0e0e0;padding-top:10px;">
    <p style="margin:0 0 6px 0;color:#1a3a5c;font-weight:bold;font-size:13px;">&#128196; Inteiro teor</p>
    <div style="background:#f8f8f8;border:1px solid #ddd;border-radius:6px;padding:14px;white-space:pre-wrap;font-size:12px;line-height:1.6;color:#333;">
{html.escape(teor[:3000])}{"…" if len(teor) > 3000 else ""}
    </div>
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f4f6f9;
             font-family:Segoe UI,Arial,sans-serif;">
  <div style="max-width:640px;margin:0 auto;padding:24px 16px 40px;">

    <div style="background:#0b2545;color:#fff;padding:18px 24px;
                border-radius:8px 8px 0 0;margin-bottom:2px;">
      <h2 style="margin:0;font-size:20px;">&#9878; Jurisprud&ecirc;ncias para aprova&ccedil;&atilde;o</h2>
      <p style="margin:5px 0 0;font-size:13px;opacity:.75;">
        {len(itens)} julgado(s) &middot; Tema: {html.escape(secao_nome)} &middot; {agora}
      </p>
    </div>

    <div style="background:#1a3a5c;color:white;padding:20px;border-radius:0;margin-bottom:0;">
      <h2 style="margin:0 0 8px 0;font-size:18px;">&#128269; Busca de Jurisprud&ecirc;ncia</h2>
      <p style="margin:4px 0;"><strong>Tema:</strong> {html.escape(secao_nome)}</p>
      <p style="margin:4px 0;"><strong>Termos pesquisados:</strong> {termos_str}</p>
      <p style="margin:4px 0;font-size:12px;opacity:0.8;">{len(itens)} resultado(s) encontrado(s)</p>
    </div>

    <div style="background:#f4f6f9;padding:14px 0;">
      {cards}
    </div>

    <p style="font-size:12px;color:#999;text-align:center;margin-top:8px;">
      Bot&otilde;es v&aacute;lidos por {EXPIRA_DIAS} dias &middot;
      <a href="{html.escape(SITE_URL)}/admin" style="color:#999;">Acessar painel</a>
    </p>
  </div>
</body>
</html>"""


# ── 6. Envio de e-mail ────────────────────────────────────────────────────────

def enviar_email(html_body, n, secao_nome):
    if not SMTP_USER:
        raise ValueError("EMAIL_USER não configurado no .env")
    if not SMTP_PASS:
        raise ValueError("EMAIL_APP_PASSWORD não configurado no .env")
    if not EMAIL_DEST:
        raise ValueError("EMAIL_DEST não configurado no .env")

    agora = datetime.now().strftime("%d/%m/%Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"[Blog Segurança] {n} jurisprudência(s) para aprovação "
        f"— {agora} — Tema: {secao_nome}"
    )
    msg["From"] = SMTP_USER
    msg["To"]   = EMAIL_DEST
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.sendmail(SMTP_USER, EMAIL_DEST, msg.as_string())


# ── Principal ─────────────────────────────────────────────────────────────────

def main():
    inicio = datetime.now()
    print(f"[{inicio:%d/%m/%Y %H:%M}] buscador_jurisprudencia_email iniciado\n")

    # 1. Ollama
    print("Verificando Ollama...")
    garantir_ollama()

    # 2. Seção aleatória
    secao = random.choice(SECOES)
    print(f"\nSeção escolhida: {secao}")

    # 3. Expressões de busca
    print(f"\nGerando expressões de busca com {OLLAMA_MODEL}...")
    try:
        expressoes = gerar_expressoes(secao)
    except Exception as e:
        print(f"Erro ao chamar Ollama: {e}")
        return
    print(f"  Expressões: {expressoes}")

    # 4. Coleta
    print("\nColetando jurisprudências no TJRN...")
    itens = coletar_jurisprudencias(expressoes)
    print(f"\n{len(itens)} julgado(s) encontrado(s) após deduplicação.")

    if not itens:
        print("Nenhum resultado. E-mail não enviado.")
        return

    # 5. E-mail
    print(f"\nPreparando e-mail com {len(itens)} julgado(s)...")
    corpo = gerar_html_email(itens, secao, expressoes)

    try:
        enviar_email(corpo, len(itens), secao)
        print(f"E-mail enviado para {EMAIL_DEST}  ✓")
    except Exception as exc:
        print(f"Erro ao enviar e-mail: {exc}")

    dur = (datetime.now() - inicio).seconds
    print(f"\nConcluído em {dur}s.")


if __name__ == "__main__":
    main()
