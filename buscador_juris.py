"""Buscador de jurisprudência — múltiplos tribunais.

Roda os coletores, junta os resultados e gera uma página HTML local
com checkbox por item. Você marca e envia ao site (como rascunho),
no mesmo molde do buscador.py de notícias.

USO:
    python buscador_juris.py "dano moral, acidente"
    python buscador_juris.py "dano moral" 3        (3 páginas por tribunal)
    python buscador_juris.py                       (usa o padrão)

Múltiplos termos: separe por vírgula. A frase principal vai ao servidor;
os extras são filtrados localmente (todos precisam aparecer no texto).
    'dano moral, roubo' → busca 'dano moral', filtra exigindo 'roubo'.
"""
import html
import os
import sys
import webbrowser
from datetime import datetime

# --- Registro de coletores. Para plugar um tribunal novo no futuro,
#     importe o coletar dele e adicione à lista COLETORES. ---
from coletores.tjrn import coletar as coletar_tjrn

COLETORES = [
    ("TJRN", coletar_tjrn),
    # ("TJSP", coletar_tjsp),   # futuro: cria coletores/tjsp.py e descomenta
]

# --- Padrões (usados se nada for passado na linha de comando) ---
TERMO = "dano moral"
MAX_PAGES = 1

# --- Envio para o site (mesmos valores do seu buscador.py) ---
SITE_URL = "https://rafaelgalvao.pythonanywhere.com"
IMPORT_TOKEN = "spRN_9fK2mQ7xZ4tB6vL1nP8wD3yH5cJ0aE"

ARQUIVO_SAIDA = "jurisprudencia_encontrada.html"


def coletar_tudo(termo, max_pages):
    """Roda cada coletor e junta tudo numa lista só."""
    todos = []
    for nome, fn_coletar in COLETORES:
        print(f"Buscando em {nome}...")
        try:
            itens = fn_coletar(termo, max_pages=max_pages)
            print(f"  {nome}: {len(itens)} itens")
            todos.extend(itens)
        except Exception as e:
            print(f"  {nome}: ERRO ({e}) — pulando")
    return todos


# Template de cada card (placeholders trocados com .format()).
_CARD_TPL = (
    '<article class="card">'
    '<label class="check"><input type="checkbox" class="sel"'
    ' data-tribunal="{a_trib}" data-processo="{a_proc}" data-classe="{a_classe}"'
    ' data-orgao="{a_orgao}" data-magistrado="{a_mag}"'
    ' data-html="{a_html}" data-texto="{a_texto}">'
    ' Selecionar</label>'
    '<div class="meta">{tribunal} &middot; {classe}</div>'
    '<h3>Processo {processo}</h3>'
    '<div class="sub">{orgao} &middot; {magistrado}</div>'
    '<p class="preview">{preview}</p>'
    '<details><summary>Ler inteiro teor</summary>'
    '<div class="teor">{teor_completo}</div></details>'
    '</article>'
)


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
    if (sel.length === 0) { alert('Marque ao menos uma jurisprudência.'); return; }
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = baseUrl() + '/importar_juris';
    function add(nome, valor) {
      var inp = document.createElement('input');
      inp.type = 'hidden'; inp.name = nome; inp.value = valor;
      form.appendChild(inp);
    }
    add('token', TOKEN);
    for (var i = 0; i < sel.length; i++) {
      var c = sel[i];
      add('tribunal', c.dataset.tribunal);
      add('processo', c.dataset.processo);
      add('classe', c.dataset.classe);
      add('orgao', c.dataset.orgao);
      add('magistrado', c.dataset.magistrado);
      add('html', c.dataset.html);
      add('texto', c.dataset.texto);
    }
    document.body.appendChild(form);
    form.submit();
  }
</script>"""


def gerar_html(itens, termo=TERMO):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    envio_ativo = bool(SITE_URL and IMPORT_TOKEN)

    cards = []
    for i in itens:
        def esc(chave, q=False):
            return html.escape(str(i.get(chave) or ""), quote=q)

        texto_completo = i.get("inteiro_teor_texto") or ""
        preview = texto_completo[:2000]
        cards.append(_CARD_TPL.format(
            a_trib=esc("tribunal", True), a_proc=esc("numero_processo", True),
            a_classe=esc("classe_judicial", True), a_orgao=esc("orgao_julgador", True),
            a_mag=esc("magistrado", True),
            a_html=esc("inteiro_teor_html", True), a_texto=esc("inteiro_teor_texto", True),
            tribunal=esc("tribunal"), classe=esc("classe_judicial"),
            processo=esc("numero_processo"), orgao=esc("orgao_julgador"),
            magistrado=esc("magistrado"),
            preview=html.escape(preview),
            teor_completo=html.escape(texto_completo),  # texto completo, escapado
        ))

    corpo = "\n".join(cards) if cards else "<p>Nenhuma jurisprudência encontrada.</p>"

    if envio_ativo:
        barra = """
        <div class="barra">
            <span id="contador">0 selecionada(s)</span>
            <button id="enviar" onclick="enviarSelecionados()">Enviar selecionadas para o site (rascunho)</button>
        </div>"""
        script = _SCRIPT_ENVIO.replace("__SITE_URL__", html.escape(SITE_URL, quote=True)) \
                              .replace("__TOKEN__", html.escape(IMPORT_TOKEN, quote=True))
    else:
        barra = '<div class="barra aviso">Envio desativado. Preencha SITE_URL e IMPORT_TOKEN.</div>'
        script = ""

    return f"""<!DOCTYPE html>
<html lang="pt-br"><head><meta charset="utf-8">
<title>Jurisprudência encontrada</title>
<style>
  body {{ font-family: Segoe UI, Arial, sans-serif; background:#f4f6f9; color:#1c2733; margin:0; padding:24px 24px 90px; }}
  .topo {{ max-width:820px; margin:0 auto 18px; }}
  h1 {{ color:#0b2545; margin:0 0 4px; }}
  .sub {{ color:#5a6675; font-size:13px; }}
  .card {{ max-width:820px; margin:0 auto 14px; background:#fff; border:1px solid #d9dee6;
          border-left:4px solid #b8860b; border-radius:8px; padding:16px 20px; }}
  .check {{ float:right; font-size:13px; color:#13315c; font-weight:600; cursor:pointer; }}
  .meta {{ font-size:12px; color:#5a6675; text-transform:uppercase; letter-spacing:.4px; }}
  .card h3 {{ margin:6px 0; font-size:16px; color:#0b2545; }}
  .card .sub {{ font-size:12px; color:#5a6675; }}
  .card p {{ margin:8px 0 0; color:#33414f; font-size:14px; }}
  .barra {{ position:fixed; left:0; right:0; bottom:0; background:#0b2545; color:#fff;
           padding:12px 24px; display:flex; align-items:center; gap:16px; justify-content:center; }}
  .barra.aviso {{ background:#7a5b00; font-size:13px; text-align:center; }}
  #enviar {{ background:#b8860b; color:#fff; border:none; padding:10px 18px; border-radius:6px;
            font-weight:600; cursor:pointer; }}
            
    .card details {{ margin-top:8px; }}
  .card summary {{ cursor:pointer; color:#13315c; font-weight:600; font-size:13px; }}
  .card .teor {{ margin-top:8px; font-size:13px; color:#33414f; line-height:1.5;
                max-height:400px; overflow-y:auto; white-space:pre-wrap;
                background:#f8f9fb; padding:12px; border-radius:6px; }}
                
</style></head><body>
<div class="topo">
  <h1>Jurisprudência encontrada</h1>
  <div class="sub">{len(itens)} item(ns) &middot; busca por "{html.escape(termo)}" &middot; gerado em {agora}</div>
</div>
{corpo}
{barra}
{script}
</body></html>"""


def main(termo=None, max_pages=None):
    termo = termo or TERMO
    max_pages = max_pages or MAX_PAGES
    itens = coletar_tudo(termo, max_pages)
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), ARQUIVO_SAIDA)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(gerar_html(itens, termo))
    print(f"\nPronto! {len(itens)} item(ns). Abra:\n  {caminho}")
    try:
        webbrowser.open("file://" + caminho)
    except Exception:
        pass


if __name__ == "__main__":
    # Argumentos: o termo (com aspas), e opcionalmente o número de páginas.
    #   python buscador_juris.py "dano moral, acidente"
    #   python buscador_juris.py "dano moral" 3
    termo_cli = None
    paginas_cli = None

    args = sys.argv[1:]
    # Se o último argumento for um número, trata como nº de páginas.
    if args and args[-1].isdigit():
        paginas_cli = int(args[-1])
        args = args[:-1]
    if args:
        termo_cli = " ".join(args)

    main(termo_cli, paginas_cli)