"""Buscador de notícias por RSS — versão 2 (sem filtros, sem LLM).

O que ele faz:
  - Lê os feeds RSS listados em FEEDS (edite à vontade).
  - Gera 'noticias_encontradas.html' com uma CAIXA DE SELEÇÃO em cada notícia.
  - Você marca as que quiser e clica em "Enviar selecionados para o site".
    Elas entram no site como RASCUNHO (não publicadas), para você revisar
    e publicar no painel (Notícias).

Como usar (no seu computador):
    pip install feedparser            # só na primeira vez
    python buscador.py
Depois abra 'noticias_encontradas.html', marque e envie.

CONFIGURAÇÃO DO ENVIO (faça uma vez):
  1) No servidor (PythonAnywhere), defina no arquivo .env uma senha-token:
         IMPORT_TOKEN=algumacoisa-bem-secreta-e-longa
     e clique em Reload na aba Web.
  2) Aqui embaixo, preencha SITE_URL e IMPORT_TOKEN com os MESMOS valores.
"""
import html
import os
import re
import webbrowser
from datetime import datetime

import feedparser

# ---------------------------------------------------------------------------
# ENVIO PARA O SITE — preencha para habilitar o botão de envio.
# ---------------------------------------------------------------------------
SITE_URL = "https://rafaelgalvao.pythonanywhere.com"   # endereço do seu site
IMPORT_TOKEN = "spRN_9fK2mQ7xZ4tB6vL1nP8wD3yH5cJ0aE"   # cole aqui o MESMO token definido no .env do servidor

# ---------------------------------------------------------------------------
# FONTES — edite esta lista. Formato: ("Nome da fonte", "URL do RSS")
# ---------------------------------------------------------------------------
FEEDS = [
    ("Google Notícias — Segurança Pública RN",
     "https://news.google.com/rss/search?q=%22seguran%C3%A7a+p%C3%BAblica%22+%22Rio+Grande+do+Norte%22&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
    ("Google Notícias — Polícia RN",
     "https://news.google.com/rss/search?q=pol%C3%ADcia+%22Rio+Grande+do+Norte%22&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
    ("Google Notícias — Segurança Pública (Brasil)",
     "https://news.google.com/rss/search?q=%22seguran%C3%A7a+p%C3%BAblica%22&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
]

MAX_POR_FONTE = 20
ARQUIVO_SAIDA = "noticias_encontradas.html"

# Template de cada notícia na lista (placeholders trocados com .format()).
_CARD_TPL = (
    '<article class="card">'
    '<label class="check"><input type="checkbox" class="sel"'
    ' data-titulo="{at}" data-link="{al}" data-resumo="{ar}" data-fonte="{af}">'
    ' Selecionar</label>'
    '<div class="meta">{fonte} &middot; {data}</div>'
    '<h3><a href="{link}" target="_blank" rel="noopener">{titulo}</a></h3>'
    '<p>{resumo}</p>'
    '<a class="fonte" href="{link}" target="_blank" rel="noopener">'
    'Abrir mat&eacute;ria original &rarr;</a>'
    '</article>'
)

# JavaScript do botão de envio (string normal; placeholders trocados em runtime).
_SCRIPT_ENVIO = """
<script>
  var SITE_URL = "__SITE_URL__";
  var TOKEN = "__TOKEN__";
  function atualizar() {
    var n = document.querySelectorAll('.sel:checked').length;
    document.getElementById('contador').textContent = n + ' selecionada(s)';
  }
  document.addEventListener('change', function (e) {
    if (e.target.classList.contains('sel')) atualizar();
  });
  function baseUrl() {
    return SITE_URL.charAt(SITE_URL.length - 1) === '/'
      ? SITE_URL.slice(0, -1) : SITE_URL;
  }
  function enviarSelecionados() {
    var sel = document.querySelectorAll('.sel:checked');
    if (sel.length === 0) { alert('Marque ao menos uma notícia.'); return; }
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = baseUrl() + '/importar';
    function add(nome, valor) {
      var inp = document.createElement('input');
      inp.type = 'hidden'; inp.name = nome; inp.value = valor;
      form.appendChild(inp);
    }
    add('token', TOKEN);
    for (var i = 0; i < sel.length; i++) {
      var c = sel[i];
      add('titulo', c.dataset.titulo);
      add('link', c.dataset.link);
      add('resumo', c.dataset.resumo);
      add('fonte', c.dataset.fonte);
    }
    document.body.appendChild(form);
    form.submit();
  }
</script>"""


def limpar_texto(texto, limite=300):
    if not texto:
        return ""
    sem_tags = re.sub(r"<[^>]+>", " ", texto)
    sem_tags = html.unescape(sem_tags)
    sem_tags = re.sub(r"\s+", " ", sem_tags).strip()
    if len(sem_tags) > limite:
        sem_tags = sem_tags[:limite].rstrip() + "…"
    return sem_tags


def formatar_data(entry):
    if getattr(entry, "published_parsed", None):
        try:
            return datetime(*entry.published_parsed[:6]).strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass
    return entry.get("published", entry.get("updated", ""))


def coletar():
    itens = []
    vistos = set()
    for nome, url in FEEDS:
        print(f"Lendo: {nome} ...")
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            print("  (aviso) não consegui ler este feed agora.")
            continue
        for e in feed.entries[:MAX_POR_FONTE]:
            link = e.get("link", "")
            if not link or link in vistos:
                continue
            vistos.add(link)
            itens.append({
                "fonte": nome,
                "titulo": e.get("title", "(sem título)"),
                "link": link,
                "resumo": limpar_texto(e.get("summary", "")),
                "data": formatar_data(e),
            })
    return itens


def gerar_html(itens):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    envio_ativo = bool(SITE_URL and IMPORT_TOKEN)

    cards = []
    for i in itens:
        def esc(campo, q=False):
            return html.escape(i.get(campo, ""), quote=q)
        cards.append(_CARD_TPL.format(
            at=esc("titulo", True), al=esc("link", True),
            ar=esc("resumo", True), af=esc("fonte", True),
            fonte=esc("fonte"), data=esc("data"),
            link=esc("link"), titulo=esc("titulo"), resumo=esc("resumo"),
        ))
    corpo = "\n".join(cards) if cards else "<p>Nenhuma notícia encontrada.</p>"

    if envio_ativo:
        barra = """
        <div class="barra">
            <span id="contador">0 selecionada(s)</span>
            <button id="enviar" onclick="enviarSelecionados()">Enviar selecionados para o site (como rascunho)</button>
        </div>"""
        script = _SCRIPT_ENVIO.replace("__SITE_URL__", html.escape(SITE_URL, quote=True)) \
                              .replace("__TOKEN__", html.escape(IMPORT_TOKEN, quote=True))
    else:
        barra = """
        <div class="barra aviso">
            Envio desativado. Para habilitar, preencha SITE_URL e IMPORT_TOKEN no
            topo do arquivo buscador.py (e defina o mesmo IMPORT_TOKEN no .env do servidor).
            Por enquanto, copie e cole as notícias manualmente no painel.
        </div>"""
        script = ""

    return f"""<!DOCTYPE html>
<html lang="pt-br"><head><meta charset="utf-8">
<title>Notícias encontradas</title>
<style>
  body {{ font-family: Segoe UI, Arial, sans-serif; background:#f4f6f9; color:#1c2733; margin:0; padding:24px 24px 90px; }}
  .topo {{ max-width:820px; margin:0 auto 18px; }}
  h1 {{ color:#0b2545; margin:0 0 4px; }}
  .sub {{ color:#5a6675; font-size:14px; }}
  .card {{ max-width:820px; margin:0 auto 14px; background:#fff; border:1px solid #d9dee6;
          border-left:4px solid #b8860b; border-radius:8px; padding:16px 20px; }}
  .check {{ float:right; font-size:13px; color:#13315c; font-weight:600; cursor:pointer; }}
  .meta {{ font-size:12px; color:#5a6675; text-transform:uppercase; letter-spacing:.4px; }}
  .card h3 {{ margin:6px 0; font-size:17px; }}
  .card h3 a {{ color:#0b2545; text-decoration:none; }}
  .card p {{ margin:0 0 8px; color:#33414f; font-size:14px; }}
  .fonte {{ font-size:13px; color:#13315c; font-weight:600; text-decoration:none; }}
  .barra {{ position:fixed; left:0; right:0; bottom:0; background:#0b2545; color:#fff;
           padding:12px 24px; display:flex; align-items:center; gap:16px; justify-content:center; }}
  .barra.aviso {{ background:#7a5b00; font-size:13px; text-align:center; }}
  #enviar {{ background:#b8860b; color:#fff; border:none; padding:10px 18px; border-radius:6px;
            font-weight:600; cursor:pointer; }}
  #contador {{ font-size:14px; }}
</style></head><body>
<div class="topo">
  <h1>Notícias encontradas</h1>
  <div class="sub">{len(itens)} item(ns) · gerado em {agora}. Marque as que quiser e envie; elas entram como rascunho no site.</div>
</div>
{corpo}
{barra}
{script}
</body></html>"""


def main():
    itens = coletar()
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), ARQUIVO_SAIDA)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(gerar_html(itens))
    print(f"\nPronto! {len(itens)} notícia(s). Abra o arquivo:\n  {caminho}")
    try:
        webbrowser.open("file://" + caminho)
    except Exception:
        pass


if __name__ == "__main__":
    main()
