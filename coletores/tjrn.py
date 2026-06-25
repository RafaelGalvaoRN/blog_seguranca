"""Coletor de jurisprudência do TJRN (Scrapy + Playwright).

VERSÃO DE DIAGNÓSTICO: janela visível + pausa, para inspecionar o WAF.
"""
import multiprocessing
import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy.signalmanager import dispatcher
from scrapy import signals
from parsel import Selector
import re

TRIBUNAL = "TJRN"


class _SpiderTJRN(scrapy.Spider):
    name = "tjrn"
    home_url = "https://jurisprudencia.tjrn.jus.br/"
    termo = "dano moral"
    max_pages = 1

    custom_settings = {
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": False},
        "LOG_LEVEL": "DEBUG",
    }

    async def start(self):
        yield scrapy.Request(
            url=self.home_url,
            meta={
                "playwright": True,
                "playwright_include_page": True,
            },
            callback=self.parse,
        )

    async def parse(self, response):
        page = response.meta["playwright_page"]
        numero_pagina = 1

        while numero_pagina <= int(self.max_pages):
            payload = {
                "jurisprudencia": {
                    "ementa": "", "inteiro_teor": self.termo, "nr_processo": "",
                    "id_classe_judicial": "", "id_orgao_julgador": "", "id_relator": "",
                    "id_colegiado": "", "id_juiz": "", "id_vara": "", "dt_inicio": "",
                    "dt_fim": "", "origem": "", "sistema": "PJE", "decisoes": "",
                    "jurisdicoes": "", "grau": "",
                },
                "page": numero_pagina,
                "usuario": {"matricula": "", "token": ""},
            }

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

            hits = resultado["hits"]["hits"]
            if not hits:
                break

            for hit in hits:
                fonte = hit["_source"]
                html_teor = fonte.get("inteiro_teor") or ""
                texto = " ".join(Selector(text=html_teor).css("*::text").getall())
                texto = re.sub(r"\s+", " ", texto).strip()
                yield {
                    "tribunal": TRIBUNAL,
                    "numero_processo": fonte.get("numero_processo"),
                    "classe_judicial": fonte.get("classe_judicial"),
                    "orgao_julgador": fonte.get("orgao_julgador"),
                    "magistrado": fonte.get("magistrado"),
                    "inteiro_teor_html": html_teor,
                    "inteiro_teor_texto": texto,
                    "link": "",
                }

            numero_pagina += 1

        await page.close()


def _processo_worker(termo, max_pages, fila):
    itens = []

    def _guardar(item, response, spider):
        itens.append(dict(item))

    dispatcher.connect(_guardar, signal=signals.item_scraped)

    process = CrawlerProcess(settings={
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": False},
        "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "LOG_LEVEL": "ERROR",
    })
    process.crawl(_SpiderTJRN, termo=termo, max_pages=max_pages)
    process.start()

    fila.put(itens)



def coletar(termo, max_pages=1):
    fila = multiprocessing.Queue()
    p = multiprocessing.Process(target=_processo_worker, args=(termo, max_pages, fila))
    p.start()
    itens = fila.get()
    p.join()
    return itens


if __name__ == "__main__":
    multiprocessing.freeze_support()
    resultados = coletar("dano moral", max_pages=1)
    print(f"\n[coletar()] TJRN: {len(resultados)} itens")
    if resultados:
        print("1º processo:", resultados[0]["numero_processo"])
        print("Texto (80):", resultados[0]["inteiro_teor_texto"][:80])