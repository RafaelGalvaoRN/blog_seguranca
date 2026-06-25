from parsel import Selector
import re


class LimparTeorPipeline:
    def process_item(self, item, spider):
        html = item.get("inteiro_teor_texto", "")
        if html:
            texto = " ".join(Selector(text=html).css("*::text").getall())
            texto = re.sub(r"\s+", " ", texto).strip()
            item["inteiro_teor_texto"] = texto
        return item