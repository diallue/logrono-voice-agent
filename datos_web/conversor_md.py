import html
import re
from html.parser import HTMLParser

_ETIQUETAS_IGNORADAS = {"head", "title", "script", "style", "nav", "footer", "header", "noscript", "svg", "select", "option"}

_MARCADORES_FIN_ARTICULO = ("volver arriba", "Mostrando artículos:", "COMPRAS Y RESERVAS", "LOGROÑO DEPORTE\nEmpresa",)

_REGEX_CABECERA_BUSQUEDA = re.compile(r"^.*?Buscar\s*-\s*Videos\s*", re.IGNORECASE | re.DOTALL)

_REGEX_ANTISPAM_EMAIL = re.compile(
    r"Esta direcci[oó]n de correo electr[oó]nico est[aá] siendo protegida contra los robots de spam\."
    r"\s*Necesita tener JavaScript habilitado para poder verlo\.",
    re.IGNORECASE,
)

_REGEX_CARACTERES_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_REGEX_CLOAK_SPAN = re.compile(r"<span[^>]*id=[\"']cloak[\w]+[\"'][^>]*>(?:(?!</span>).)*</span>\s*<script[^>]*>((?:(?!</script>).)*)</script>", re.IGNORECASE | re.DOTALL,)
_REGEX_SCRIPT_INDIVIDUAL = re.compile(r"<script[^>]*>(.*?)</script>(?:\s*<noscript[^>]*>.*?</noscript>)?", re.IGNORECASE | re.DOTALL,)


class ConvertidorHTMLaMarkdown(HTMLParser):
    """Transforma el árbol HTML de Joomla en texto Markdown (.md) con soporte para tablas y formularios."""

    def __init__(self) -> None:
        super().__init__()
        self._ignorar_nivel = 0
        self._partes: list[str] = []
        self._en_celda = False
        self._fila_actual: list[str] = []
        self._celda_actual: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _ETIQUETAS_IGNORADAS:
            self._ignorar_nivel += 1
            return
        if self._ignorar_nivel > 0:
            return

        if tag == "h1":
            self._partes.append("\n# ")
        elif tag == "h2":
            self._partes.append("\n## ")
        elif tag in ("h3", "h4", "h5"):
            self._partes.append("\n### ")
        elif tag in ("p", "div", "section", "article") and not self._en_celda:
            self._partes.append("\n")
        elif tag == "br":
            self._partes.append(" " if self._en_celda else "\n")
        elif tag == "li" and not self._en_celda:
            self._partes.append("\n- ")
        elif tag == "tr":
            self._fila_actual = []
        elif tag in ("td", "th"):
            self._en_celda = True
            self._celda_actual = []
        elif tag == "input":
            self._procesar_input(dict(attrs))

    def _procesar_input(self, attrs_dict: dict[str, str | None]) -> None:
        """Extrae información útil de cajas de texto y botones en páginas de gestión."""
        tipo = (attrs_dict.get("type") or "").lower()
        if tipo not in ("hidden", "submit", "button", "checkbox", "radio"):
            etiqueta = attrs_dict.get("placeholder") or attrs_dict.get("title") or attrs_dict.get("name") or ""
            if len(etiqueta) > 2:
                self._partes.append(f"[Campo de formulario: {etiqueta}] ")
        elif tipo in ("submit", "button") and attrs_dict.get("value"):
            self._partes.append(f"[Botón: {attrs_dict.get('value')}] ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _ETIQUETAS_IGNORADAS:
            self._ignorar_nivel = max(0, self._ignorar_nivel - 1)
            return
        if self._ignorar_nivel > 0:
            return

        if tag in ("h1", "h2", "h3", "h4", "h5"):
            self._partes.append("\n")
        elif tag in ("td", "th"):
            self._en_celda = False
            celda_limpia = re.sub(r"\s+", " ", " ".join(self._celda_actual)).strip()
            self._fila_actual.append(celda_limpia)
        elif tag == "tr":
            if any(self._fila_actual):
                celdas = " | ".join(c if c else "-" for c in self._fila_actual)
                self._partes.append(f"\n| {celdas} |\n")
            self._fila_actual = []

    def handle_data(self, data: str) -> None:
        if self._ignorar_nivel > 0:
            return
        texto = data.strip()
        if not texto:
            return
        if self._en_celda:
            self._celda_actual.append(texto)
        else:
            self._partes.append(f"{texto} ")

    def obtener_markdown(self) -> str:
        bruto = "".join(self._partes).replace("\u200b", "")
        bruto = re.sub(r"[ \t]+", " ", bruto)

        lineas: list[str] = []
        for linea in bruto.splitlines():
            l_strip = linea.strip()
            if not l_strip or re.match(r"^[\|\-\s]+$", l_strip):
                continue
            if lineas and lineas[-1].lstrip("# ").strip() == l_strip.lstrip("# ").strip():
                continue
            lineas.append(l_strip)

        return "\n".join(lineas)


def _extraer_email_joomla(script_js: str) -> str:
    """Reconstruye el correo real a partir de la variable JS `addy...` generada por Joomla."""
    js = html.unescape(script_js)
    m_var = re.search(r"\bvar\s+(addy[a-zA-Z0-9]+)\s*=", js)
    if not m_var:
        return ""
    nombre_var = m_var.group(1)
    partes: list[str] = []
    for m_asig in re.finditer(
        rf"(?:^|[;\n\r]|<!--)\s*(?:var\s+)?{re.escape(nombre_var)}\s*\+?=([^;]+)",
        js,
    ):
        partes.extend(re.findall(r"['\"]([^'\"]*)['\"]", m_asig.group(1)))
    email = "".join(partes).replace("\\/", "/").strip()
    return f" {email} " if "@" in email else ""


def _decodificar_correos_joomla(html_raw: str) -> str:
    """Sustituye los bloques anti-spam de Joomla por el correo real sin tocar otros scripts."""
    html_limpio = _REGEX_CLOAK_SPAN.sub(
        lambda m: _extraer_email_joomla(m.group(1)) or m.group(0),
        html_raw,
    )

    def _reemplazar_script(match: re.Match) -> str:
        script_js = match.group(1)
        if "addy" not in script_js:
            return match.group(0)
        return _extraer_email_joomla(script_js) or match.group(0)

    return _REGEX_SCRIPT_INDIVIDUAL.sub(_reemplazar_script, html_limpio)


def html_a_markdown(html_raw: str) -> str:
    """Convierte el HTML bruto de una página de Logroño Deporte en Markdown limpio."""
    html_decodificado = _decodificar_correos_joomla(html_raw)

    parser = ConvertidorHTMLaMarkdown()
    parser.feed(html_decodificado)
    md = parser.obtener_markdown()

    md = _REGEX_CABECERA_BUSQUEDA.sub("", md, count=1)

    for marcador in _MARCADORES_FIN_ARTICULO:
        idx = md.find(marcador)
        if idx > 80:
            md = md[:idx]
            break

    md = _REGEX_ANTISPAM_EMAIL.sub("", md)
    md = _REGEX_CARACTERES_CONTROL.sub(" ", md)
    return md.strip()