import json
import logging
import sys
from pathlib import Path
import requests
import urllib3

RUTA_BASE_PROYECTO = Path(__file__).resolve().parent.parent
if str(RUTA_BASE_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RUTA_BASE_PROYECTO))

from datos_web.conversor_md import html_a_markdown
from datos_web.procesador_archivos import procesar_archivo_binario

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sincronizar_web")

RUTA_DATOS_WEB = Path(__file__).resolve().parent
RUTA_CATALOGO = RUTA_DATOS_WEB / "catalogo_urls.json"
RUTA_CONOCIMIENTO = RUTA_DATOS_WEB / "conocimiento"

HEADERS_WEB = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def descargar_pagina_html(url: str) -> str:
    """Descarga una página web de Logroño Deporte y la convierte a Markdown."""
    try:
        resp = requests.get(url, headers=HEADERS_WEB, timeout=6, verify=False)
        if resp.status_code == 200:
            return html_a_markdown(resp.text)
    except Exception as e:
        logger.warning(f"No se pudo descargar HTML {url}: {e}")
    return ""


def descargar_documento_adjunto(url: str) -> str:
    """Descarga un PDF, Word o Excel de Logroño Deporte y lo convierte a Markdown."""
    try:
        resp = requests.get(url, headers=HEADERS_WEB, timeout=8, verify=False)
        if resp.status_code == 200:
            ct = resp.headers.get("Content-Type", "")
            return procesar_archivo_binario(resp.content, url, ct)
    except Exception as e:
        logger.warning(f"No se pudo procesar documento {url}: {e}")
    return ""


def sincronizar_conocimiento() -> None:
    """
    Lee catalogo_urls.json, descarga las páginas HTML y los documentos PDF/Excel vigentes, y genera los 5 archivos .md en datos_web/conocimiento/.
    """
    RUTA_CONOCIMIENTO.mkdir(parents=True, exist_ok=True)
    datos_catalogo = json.loads(RUTA_CATALOGO.read_text(encoding="utf-8"))
    secciones = datos_catalogo.get("archivos_conocimiento", [])

    for sec in secciones:
        nombre_archivo = sec["archivo"]
        titulo = sec["titulo"]
        resumen = sec.get("resumen_verificado", "").strip()

        bloques_md = [f"# {titulo}"]
        if resumen:
            bloques_md.append(f"## Resumen Oficial Verificado\n{resumen}")

        for url_html in sec.get("urls_html", []):
            md_web = descargar_pagina_html(url_html)
            if len(md_web) > 40:
                bloques_md.append(f"## Fuente Oficial: {url_html}\n\n{md_web}")

        for url_doc in sec.get("urls_documentos", []):
            md_doc = descargar_documento_adjunto(url_doc)
            if len(md_doc) > 40:
                logger.info(f"  + PDF/Documento procesado: {url_doc.split('/')[-1]} ({len(md_doc)} chars)")
                bloques_md.append(f"## Documento Adjunto Oficial: {url_doc}\n\n{md_doc}")

        documento_final = "\n\n---\n\n".join(bloques_md) + "\n"
        (RUTA_CONOCIMIENTO / nombre_archivo).write_text(documento_final, encoding="utf-8")
        logger.info(f"[OK] {nombre_archivo} actualizado ({len(documento_final)} caracteres).")


if __name__ == "__main__":
    sincronizar_conocimiento()