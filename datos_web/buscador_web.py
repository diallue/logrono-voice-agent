import re
import json
import logging
from pathlib import Path
import requests
import urllib3

from datos_web.conversor_md import html_a_markdown
from datos_web.procesador_archivos import EXTENSIONES_DOCUMENTOS, procesar_archivo_binario

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("datos_web.buscador_web")

URL_BASE_WEB = "https://www.logronodeporte.es"
RUTA_CATALOGO_URLS = Path(__file__).resolve().parent / "catalogo_urls.json"

HEADERS_WEB = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_RUTAS_EXCLUIDAS = ("/component/", "/templates/", "/media/", "/noticias", "/portal-del-abonado")
_REGEX_ENLACES_HTML = re.compile(r'<a\b[^>]*?\bhref=["\']([^"\'?#]+)["\']', re.IGNORECASE)


def cargar_catalogo_urls() -> dict[str, str]:
    """Lee el diccionario 'urls_especificas_vivo' desde catalogo_urls.json."""
    if not RUTA_CATALOGO_URLS.exists():
        return {}
    datos = json.loads(RUTA_CATALOGO_URLS.read_text(encoding="utf-8"))
    return datos.get("urls_especificas_vivo", {})


def _descargar_url_a_md(url: str) -> str:
    """Descarga una página HTML o un PDF/documento en vivo y devuelve su contenido en Markdown."""
    try:
        resp = requests.get(url, headers=HEADERS_WEB, timeout=6, verify=False)
        if resp.status_code != 200:
            return ""

        ct = resp.headers.get("Content-Type", "").lower()
        if url.lower().endswith(EXTENSIONES_DOCUMENTOS) or "application/pdf" in ct:
            md = procesar_archivo_binario(resp.content, url, ct)
        elif "text/html" in ct:
            md = html_a_markdown(resp.text)
        else:
            return ""

        return f"## Fuente Web en Vivo: {url}\n\n{md[:3500]}" if len(md) > 40 else ""
    except Exception as e:
        logger.debug(f"No se pudo descargar {url}: {e}")
        return ""


def _consultar_buscador_joomla(termino: str) -> list[str]:
    """Pregunta al buscador oficial de logronodeporte.es y devuelve las URLs de resultados."""
    urls: list[str] = []
    try:
        resp = requests.get(
            f"{URL_BASE_WEB}/component/search/",
            params={"searchword": termino, "searchphrase": "any", "ordering": "newest"},
            headers=HEADERS_WEB,
            timeout=5,
            verify=False,
        )
        if resp.status_code == 200:
            for href in _REGEX_ENLACES_HTML.findall(resp.text):
                if href.startswith("/") and not any(x in href.lower() for x in _RUTAS_EXCLUIDAS):
                    url_completa = f"{URL_BASE_WEB}{href.rstrip('/')}"
                    if url_completa not in urls:
                        urls.append(url_completa)
    except Exception as e:
        logger.debug(f"Buscador Joomla no disponible: {e}")
    return urls


def buscar_en_web_en_vivo(consulta: str, palabras: list[str]) -> list[str]:
    """Obtiene hasta 2 páginas o documentos en tiempo real desde logronodeporte.es."""
    catalogo = cargar_catalogo_urls()
    urls_candidatas: list[str] = []

    for p in palabras:
        if p in catalogo and catalogo[p] not in urls_candidatas:
            urls_candidatas.append(catalogo[p])

    termino = " ".join(palabras[:4]) if palabras else consulta
    for url_joomla in _consultar_buscador_joomla(termino):
        if url_joomla not in urls_candidatas:
            urls_candidatas.append(url_joomla)

    bloques_descargados: list[str] = []
    for url in urls_candidatas[:4]:
        if len(bloques_descargados) >= 2:
            break
        md = _descargar_url_a_md(url)
        if md:
            logger.info(f"Página/PDF descargado en vivo: {url}")
            bloques_descargados.append(md)

    return bloques_descargados