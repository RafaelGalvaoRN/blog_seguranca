"""
buscador_email.py — Coleta notícias via RSS e envia e-mail com links de aprovação.

Fluxo:
  1. Script roda (manualmente ou agendado no PythonAnywhere)
  2. Busca notícias nos feeds RSS + imagens em paralelo
  3. Envia e-mail HTML com um botão "Publicar no site" por matéria
  4. Ao clicar no botão, a matéria é publicada diretamente no blog

Configurar no .env (mesmo arquivo do Flask):
  EMAIL_USER         — remetente Gmail (ex: seuemail@gmail.com)
  EMAIL_APP_PASSWORD — senha de app do Gmail (não a senha normal)
  EMAIL_DEST         — destinatário (ex: voce@mp.br)
  SITE_URL           — URL do blog
  SECRET_KEY         — mesma chave do Flask (já está no .env)

Gmail: ative "Verificação em 2 etapas" → gere "Senha de app" em
  https://myaccount.google.com/apppasswords
"""

import base64
import html
import os
import re
import smtplib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer

try:
    import trafilatura
except ImportError:
    trafilatura = None

try:
    from googlenewsdecoder import new_decoderv1
except ImportError:
    new_decoderv1 = None

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ── Configuração ──────────────────────────────────────────────────────────────
SITE_URL    = os.getenv("SITE_URL", "https://rafaelgalvao.pythonanywhere.com")
SECRET_KEY  = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao")
SMTP_HOST   = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT   = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER   = os.getenv("EMAIL_USER", "")
SMTP_PASS   = os.getenv("EMAIL_APP_PASSWORD", "")
EMAIL_DEST  = os.getenv("EMAIL_DEST", "")

MAX_POR_FONTE = 15
MAX_WORKERS   = 10
EXPIRA_DIAS   = 7    # links de aprovação expiram em N dias
BUSCAR_IMAGEM = True

FEEDS = [
    ("Google Notícias — Segurança Pública RN",
     "https://news.google.com/rss/search?q=%22seguran%C3%A7a+p%C3%BAblica%22+%22Rio+Grande+do+Norte%22&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
    ("Google Notícias — Polícia RN",
     "https://news.google.com/rss/search?q=pol%C3%ADcia+%22Rio+Grande+do+Norte%22&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
    ("Google Notícias — Segurança Pública (Brasil)",
     "https://news.google.com/rss/search?q=%22seguran%C3%A7a+p%C3%BAblica%22&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
]

# ── Coleta ────────────────────────────────────────────────────────────────────

def limpar_texto(texto, limite=400):
    if not texto:
        return ""
    sem_tags = re.sub(r"<[^>]+>", " ", texto)
    sem_tags = html.unescape(sem_tags)
    sem_tags = re.sub(r"\s+", " ", sem_tags).strip()
    return sem_tags[:limite].rstrip() + ("…" if len(sem_tags) > limite else "")


def formatar_data(entry):
    if getattr(entry, "published_parsed", None):
        try:
            return datetime(*entry.published_parsed[:6]).strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass
    return entry.get("published", entry.get("updated", ""))


def resolver_redirect(link):
    """Resolve a URL real de um link do Google Notícias."""
    if "news.google.com" not in link:
        return link

    # Estratégia 1: googlenewsdecoder
    if new_decoderv1:
        try:
            result = new_decoderv1(link)
            if result and result.get("status") is True:
                decoded = result.get("decoded_url", "")
                if decoded and decoded.startswith("http") and "google.com" not in decoded:
                    return decoded
        except Exception:
            pass

    # Estratégia 2: base64 decode
    m = re.search(r"/articles/([^/?#\s]+)", link)
    if m:
        try:
            article_id = m.group(1)
            padded = article_id + "=" * (-len(article_id) % 4)
            data = base64.urlsafe_b64decode(padded)
            url_m = re.search(
                rb"https?://(?!(?:[\w.-]*\.)?google\.)[^\x00-\x20\x7f-\xff]+", data
            )
            if url_m:
                url = url_m.group(0).decode("utf-8", errors="ignore").rstrip(");,'\"")
                if re.match(r"^https?://[^/]+\.[^/]+", url):
                    return url
        except Exception:
            pass

    # Estratégia 3: segue redirect HTTP
    try:
        import urllib.request
        req = urllib.request.Request(
            link,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            final = resp.geturl()
            if "google.com" not in final:
                return final
            page = resp.read(40000).decode("utf-8", errors="ignore")
        for pat in [
            r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
            r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']',
        ]:
            found = re.search(pat, page, re.IGNORECASE)
            if found:
                u = found.group(1).strip()
                if u.startswith("http") and "google.com" not in u:
                    return u
    except Exception:
        pass

    return link


def enriquecer(link):
    """Busca a imagem de capa (OG image) do artigo original."""
    if not (BUSCAR_IMAGEM and trafilatura and link):
        return ""
    try:
        url_real = resolver_redirect(link)
        baixado = trafilatura.fetch_url(url_real)
        if not baixado:
            return ""
        md = trafilatura.extract_metadata(baixado)
        if md and getattr(md, "image", None):
            return md.image
    except Exception:
        pass
    return ""


def _publicado_hoje(entry):
    """Retorna True se a entrada foi publicada hoje (ou se não tem data)."""
    pub = getattr(entry, "published_parsed", None)
    if not pub:
        return True  # sem data → inclui por precaução
    try:
        pub_date = datetime(*pub[:3]).date()
        return pub_date == datetime.now().date()
    except Exception:
        return True


def coletar():
    """Lê os feeds RSS e busca imagens em paralelo. Retorna apenas matérias de hoje."""
    entradas = []
    vistos = set()
    ignoradas_data = 0
    for nome, url in FEEDS:
        print(f"  Lendo: {nome} ...")
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            print("    (aviso) feed indisponível.")
            continue
        for e in feed.entries[:MAX_POR_FONTE]:
            link = e.get("link", "")
            if not link or link in vistos:
                continue
            if not _publicado_hoje(e):
                ignoradas_data += 1
                continue
            vistos.add(link)
            entradas.append((nome, e, link))
    if ignoradas_data:
        print(f"  ({ignoradas_data} matéria(s) de dias anteriores ignorada(s))")

    if not entradas:
        return []

    imagens = {}
    if BUSCAR_IMAGEM and trafilatura:
        print(f"\n  Buscando imagens ({len(entradas)} matérias em paralelo)...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futuros = {ex.submit(enriquecer, link): (nome, e, link)
                       for nome, e, link in entradas}
            done = 0
            for futuro in as_completed(futuros):
                nome, e, link = futuros[futuro]
                try:
                    img = futuro.result()
                except Exception:
                    img = ""
                imagens[link] = img
                done += 1
                status = "foto ok" if img else "sem foto"
                print(f"    [{done}/{len(entradas)}] {status} :: {e.get('title','')[:55]}")

    return [
        {
            "fonte": nome,
            "titulo": e.get("title", "(sem título)"),
            "link": link,
            "resumo": limpar_texto(e.get("summary", "")),
            "data": formatar_data(e),
            "imagem": imagens.get(link, ""),
        }
        for nome, e, link in entradas
    ]


# ── Token de aprovação ────────────────────────────────────────────────────────

def gerar_link_aprovacao(artigo):
    """Gera URL assinada com prazo de validade para publicar o artigo."""
    s = URLSafeTimedSerializer(SECRET_KEY)
    dados = {
        "t": artigo["titulo"][:255],
        "r": artigo["resumo"][:400],
        "l": artigo["link"][:500],
        "f": artigo["fonte"][:100],
        "i": artigo.get("imagem", "")[:500],
    }
    token = s.dumps(dados, salt="aprovar-noticia")
    return f"{SITE_URL.rstrip('/')}/aprovar/{token}"


# ── E-mail HTML ───────────────────────────────────────────────────────────────

def gerar_html_email(itens):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    cards = ""
    for artigo in itens:
        link_aprovar = gerar_link_aprovacao(artigo)
        img_tag = ""
        if artigo.get("imagem"):
            img_url = html.escape(artigo["imagem"], quote=True)
            img_tag = (
                f'<img src="{img_url}" width="100%"'
                f' style="max-height:200px;object-fit:cover;border-radius:4px;'
                f'display:block;margin-bottom:10px;">'
            )

        cards += f"""
<div style="background:#fff;border:1px solid #d9dee6;border-left:4px solid #b8860b;
            border-radius:8px;padding:16px 20px;margin-bottom:14px;">
  {img_tag}
  <div style="font-size:11px;color:#5a6675;text-transform:uppercase;
              letter-spacing:.4px;margin-bottom:4px;">
    {html.escape(artigo['fonte'])} &middot; {html.escape(artigo['data'])}
  </div>
  <h3 style="margin:0 0 8px;font-size:16px;line-height:1.35;color:#0b2545;">
    <a href="{html.escape(artigo['link'], True)}"
       style="color:#0b2545;text-decoration:none;">
      {html.escape(artigo['titulo'])}
    </a>
  </h3>
  <p style="margin:0 0 14px;color:#33414f;font-size:14px;line-height:1.5;">
    {html.escape(artigo['resumo'])}
  </p>
  <a href="{html.escape(link_aprovar, True)}"
     style="display:inline-block;background:#b8860b;color:#fff;text-decoration:none;
            padding:9px 18px;border-radius:6px;font-weight:700;font-size:14px;">
    &#10003; Publicar no site
  </a>
  &nbsp;&nbsp;
  <a href="{html.escape(artigo['link'], True)}"
     style="display:inline-block;color:#13315c;font-size:13px;font-weight:600;
            text-decoration:none;padding:9px 0;">
    Ler mat&eacute;ria &rarr;
  </a>
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
      <h2 style="margin:0;font-size:20px;">&#128240; Not&iacute;cias para aprova&ccedil;&atilde;o</h2>
      <p style="margin:5px 0 0;font-size:13px;opacity:.75;">
        {len(itens)} mat&eacute;ria(s) &middot; {agora}
      </p>
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


# ── Envio ─────────────────────────────────────────────────────────────────────

def enviar_email(html_body, n):
    if not SMTP_USER:
        raise ValueError("EMAIL_USER não configurado no .env")
    if not SMTP_PASS:
        raise ValueError("EMAIL_APP_PASSWORD não configurado no .env")
    if not EMAIL_DEST:
        raise ValueError("EMAIL_DEST não configurado no .env")

    agora = datetime.now().strftime("%d/%m/%Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Blog Segurança] {n} notícia(s) para aprovação — {agora}"
    msg["From"]    = SMTP_USER
    msg["To"]      = EMAIL_DEST
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.sendmail(SMTP_USER, EMAIL_DEST, msg.as_string())


# ── Principal ─────────────────────────────────────────────────────────────────

def main():
    inicio = datetime.now()
    print(f"[{inicio:%d/%m/%Y %H:%M}] buscador_email iniciado\n")

    print("Coletando notícias...")
    itens = coletar()

    if not itens:
        print("Nenhuma matéria encontrada. E-mail não enviado.")
        return

    print(f"\nPreparando e-mail com {len(itens)} matéria(s)...")
    corpo = gerar_html_email(itens)

    try:
        enviar_email(corpo, len(itens))
        print(f"E-mail enviado para {EMAIL_DEST}  ✓")
    except Exception as exc:
        print(f"Erro ao enviar e-mail: {exc}")

    dur = (datetime.now() - inicio).seconds
    print(f"\nConcluído em {dur}s.")


if __name__ == "__main__":
    main()
