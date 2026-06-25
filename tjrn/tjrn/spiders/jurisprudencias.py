import scrapy
import json


class JurisprudenciaSpider(scrapy.Spider):
    name = "jurisprudencia"

    home_url = "https://jurisprudencia.tjrn.jus.br/"
    api_url = "https://jurisprudencia.tjrn.jus.br/api/pesquisar"
    termo = "dano moral"

    async def start(self):
        yield scrapy.Request(
            url=self.home_url,
            meta={
                "playwright": True,
                "playwright_include_page": True,   # ← nos dá acesso ao objeto page
            },
            callback=self.parse,
        )

    async def parse(self, response):
        # Pegamos o objeto 'page' do Playwright que veio no meta
        page = response.meta["playwright_page"]

        # Monta o payload (mesmo de sempre)
        payload = {
            "jurisprudencia": {
                "ementa": "",
                "inteiro_teor": self.termo,
                "nr_processo": "",
                "id_classe_judicial": "",
                "id_orgao_julgador": "",
                "id_relator": "",
                "id_colegiado": "",
                "id_juiz": "",
                "id_vara": "",
                "dt_inicio": "",
                "dt_fim": "",
                "origem": "",
                "sistema": "PJE",
                "decisoes": "",
                "jurisdicoes": "",
                "grau": "",
            },
            "page": 1,
            "usuario": {"matricula": "", "token": ""},
        }

        # Executa um fetch() DENTRO do navegador, na sessão já validada
        resultado = await page.evaluate(
            """async (payload) => {
                const resp = await fetch('/api/pesquisar', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                return await resp.json();
            }""",
            payload,
        )

        # Fecha a página do navegador (boa prática)
        await page.close()

        # Agora 'resultado' é o JSON da API — mesmo formato de antes
        for hit in resultado["hits"]["hits"]:
            fonte = hit["_source"]
            yield {
                "numero_processo": fonte["numero_processo"],
                "classe_judicial": fonte["classe_judicial"],
                "orgao_julgador": fonte["orgao_julgador"],
                "magistrado": fonte["magistrado"],
                "inteiro_teor_html": fonte["inteiro_teor"],  # original
                "inteiro_teor_texto": fonte["inteiro_teor"],  # será limpo pelo pipeline
            }