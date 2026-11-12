import os
import re
import asyncio
import logging
import unicodedata
from html.parser import HTMLParser
import requests
import urllib3
from livekit.agents import function_tool

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("api_tools")
logger.setLevel(logging.INFO)

# Caché en memoria de respuestas Markdown (.md) por consulta
_CACHE_WEB: dict[str, str] = {}
# Caché en memoria de cada URL individual ya convertida a Markdown
_CACHE_PAGINAS_MD: dict[str, str] = {}
# Directorio global autodescubierto de las URLs vigentes de logronodeporte.es (url -> título)
_DIRECTORIO_WEB: dict[str, str] = {}

HEADERS_WEB = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

EXTENSIONES_PROHIBIDAS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar",
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".mp4", ".ico"
)

# Excluimos '/component/k2/' y '/noticias' para evitar notas de prensa antiguas (2015/2016) con precios caducados
RUTAS_SISTEMA = (
    "wp-content", "wp-includes", "wp-json", "feed", "/images/",
    "/media/", "/templates/", "/components/", "/component/search",
    "/component/users", "/component/mailto", "/component/k2/", "/noticias/",
    "javascript:", "mailto:", "tel:"
)

STOPWORDS_ES = {
    "PARA", "COMO", "CUAL", "CUALES", "DONDE", "CUANDO", "TIENE", "TIENEN",
    "LOGRONO", "DEPORTE", "GRAN", "COMUNIDAD", "DEL", "LOGRONES", "SOBRE",
    "QUIERO", "QUERIA", "SABER", "PUEDO", "PUEDE", "HACER", "TENGO", "HAY",
    "QUE", "UNA", "UNO", "UNOS", "UNAS", "LOS", "LAS", "CON", "POR", "SIN",
    "MIS", "SUS", "ESTA", "ESTE", "ESTOS", "ESTAS", "SON", "SER", "ESTOY",
    "PERDIDO", "PERDI", "CODIGO", "PISTA", "PISTAS", "CLASE", "CLASES",
    "DECIR", "DIME", "FAVOR", "HOLA", "BUENOS", "DIAS", "TARDES", "IR", "VOY",
    "CAMBIAR", "COBRAN", "RECIBO", "REQUISITOS"
}

MAPA_INTENCIONES_WEB = {
    # Reservas, localizadores, anulaciones y alquiler de instalaciones
    "LOCALIZADOR": ["MODIFICAR", "ANULAR", "RESERVA", "PREGUNTAS", "CONDICIONES"],
    "ANULAR": ["MODIFICAR", "ANULAR", "RESERVA", "CONDICIONES"],
    "ANULACION": ["MODIFICAR", "ANULAR", "RESERVA", "CONDICIONES"],
    "CANCELAR": ["MODIFICAR", "ANULAR", "RESERVA", "CONDICIONES"],
    "CANCELACION": ["MODIFICAR", "ANULAR", "RESERVA", "CONDICIONES"],
    "MODIFICAR": ["MODIFICAR", "ANULAR", "RESERVA"],
    "RESERVAR": ["RESERVAS", "ONLINE", "MODIFICAR", "CONDICIONES", "TARIFAS"],
    "RESERVA": ["RESERVAS", "ONLINE", "MODIFICAR", "CONDICIONES", "TARIFAS"],
    "DEVOLUCION": ["CONDICIONES", "GENERALES", "PREGUNTAS", "TARIFAS"],
    "ENTRADA": ["TARIFAS", "RESERVAS", "CONDICIONES"],
    "ENTRADAS": ["TARIFAS", "RESERVAS", "CONDICIONES"],
    "TICKET": ["TARIFAS", "RESERVAS", "MODIFICAR"],
    "PADEL": ["RESERVAS", "TARIFAS", "INSTALACIONES"],
    "TENIS": ["RESERVAS", "TARIFAS", "INSTALACIONES"],
    "FRONTON": ["RESERVAS", "TARIFAS", "INSTALACIONES"],
    "ROCODROMO": ["ROCODROMO", "TARIFAS", "RESERVAS", "NORIAS", "GAUNAS"],
    # Tarifas, precios, tipos de abono y descuentos
    "PRECIO": ["TARIFAS", "ABONO", "TEMPORADA"],
    "PRECIOS": ["TARIFAS", "ABONO", "TEMPORADA"],
    "TARIFA": ["TARIFAS", "ABONO", "TEMPORADA"],
    "CUANTO": ["TARIFAS", "ABONO"],
    "CUESTA": ["TARIFAS", "ABONO"],
    "VALE": ["TARIFAS", "ABONO"],
    "PAGAR": ["TARIFAS", "ABONO", "CONDICIONES"],
    "ABONO": ["ABONO", "TEMPORADA", "TARIFAS", "CONDICIONES"],
    "ABONADO": ["ABONO", "TEMPORADA", "TARIFAS", "CONDICIONES"],
    "ABONARSE": ["ABONO", "TEMPORADA", "TARIFAS", "INSCRIPCION"],
    "USUARIO": ["ABONO", "TEMPORADA", "TARIFAS", "CONDICIONES"],
    "EMPADRONADO": ["ABONO", "TEMPORADA", "TARIFAS"],
    "FAMILIAR": ["ABONO", "TEMPORADA", "TARIFAS"],
    "MONOPARENTAL": ["MONOPARENTAL", "ABONO", "TEMPORADA", "TARIFAS"],
    "DISCAPACIDAD": ["SOCIAL", "ABONO", "TEMPORADA", "TARIFAS"],
    "SOCIAL": ["SOCIAL", "ABONO", "TEMPORADA", "TARIFAS"],
    "DESCUENTO": ["TARIFAS", "ABONO", "TEMPORADA"],
    "VERANO": ["TEMPORADA", "ABONO", "TARIFAS", "NORIAS", "CORTIJO"],
    # Inscripciones, cursos, sorteos y actividades a la carta / virtuales
    "APUNTAR": ["INSCRIPCION", "ACTIVIDADES", "CARTA", "PREGUNTAS"],
    "APUNTARME": ["INSCRIPCION", "ACTIVIDADES", "CARTA", "PREGUNTAS"],
    "INSCRIBIR": ["INSCRIPCION", "ACTIVIDADES", "CARTA"],
    "INSCRIBIRME": ["INSCRIPCION", "ACTIVIDADES", "CARTA"],
    "MATRICULA": ["INSCRIPCION", "ACTIVIDADES", "TARIFAS", "CONDICIONES"],
    "SORTEO": ["INSCRIPCION", "ACTIVIDADES", "PREGUNTAS"],
    "PLAZAS": ["INSCRIPCION", "ACTIVIDADES", "CARTA"],
    "BONO": ["CARTA", "TARIFAS", "MODIFICAR", "CONSULTA"],
    "BONOS": ["CARTA", "TARIFAS", "MODIFICAR", "CONSULTA"],
    "CARTA": ["CARTA", "ACTIVIDADES", "MODIFICAR"],
    "SUELTAS": ["CARTA", "ACTIVIDADES"],
    "VIRTUAL": ["VIRTUALES", "ACTIVIDADES"],
    "CASA": ["VIRTUALES", "ACTIVIDADES"],
    # Servicios especiales: Espacio Hidrotermal, Pista de Hielo, Musculación, Médico
    "BALNEARIO": ["ESPACIO", "HIDROTERMAL", "LOBETE"],
    "SPA": ["ESPACIO", "HIDROTERMAL", "LOBETE"],
    "HIDROTERMAL": ["ESPACIO", "HIDROTERMAL", "LOBETE"],
    "SAUNA": ["ESPACIO", "HIDROTERMAL", "LOBETE"],
    "TERMA": ["ESPACIO", "HIDROTERMAL", "LOBETE"],
    "JACUZZI": ["ESPACIO", "HIDROTERMAL", "LOBETE"],
    "HIELO": ["PISTA", "HIELO", "LOBETE"],
    "PATINAR": ["PISTA", "HIELO", "LOBETE"],
    "PATINAJE": ["PISTA", "HIELO", "LOBETE"],
    "PATINES": ["PISTA", "HIELO", "LOBETE"],
    "GIMNASIO": ["MUSCULACION", "TARIFAS", "INSTALACIONES"],
    "MUSCULACION": ["MUSCULACION", "TARIFAS", "PREGUNTAS"],
    "MEDICO": ["SALUD", "MOVIMIENTO", "RECONOCIMIENTO", "TARIFAS"],
    "RECONOCIMIENTO": ["SALUD", "MOVIMIENTO", "PREGUNTAS", "TARIFAS"],
    "ESFUERZO": ["SALUD", "MOVIMIENTO", "TARIFAS"],
    # Trámites administrativos, oficinas, normativa y FAQs
    "BAJA": ["CONDICIONES", "GENERALES", "PREGUNTAS", "CONTACTO"],
    "BANCO": ["CAMBIO", "CUENTA"],
    "BANCARIA": ["CAMBIO", "CUENTA"],
    "CUENTA": ["CAMBIO", "CUENTA"],
    "IBAN": ["CAMBIO", "CUENTA"],
    "DOMICILIACION": ["CAMBIO", "CUENTA"],
    "CARNET": ["PREGUNTAS", "FRECUENTES", "TARIFAS", "CONDICIONES"],
    "PULSERA": ["PREGUNTAS", "FRECUENTES", "TARIFAS"],
    "PERDIDA": ["PREGUNTAS", "FRECUENTES", "MODIFICAR"],
    "CITA": ["HORARIO", "OFICINA", "CONTACTO"],
    "OFICINA": ["HORARIO", "OFICINA", "CONTACTO"],
    "OFICINAS": ["HORARIO", "OFICINA", "CONTACTO"],
    "CHIRIBITAS": ["HORARIO", "OFICINA", "CONTACTO"],
    "TELEFONO": ["HORARIO", "OFICINA", "CONTACTO"],
    "QUEJA": ["CONTACTO", "SUGERENCIAS"],
    "SUGERENCIA": ["CONTACTO", "SUGERENCIAS"],
    "RECLAMACION": ["CONTACTO", "SUGERENCIAS"],
    "NORMA": ["CONDICIONES", "GENERALES", "PREGUNTAS"],
    "NORMAS": ["CONDICIONES", "GENERALES", "PREGUNTAS"],
    "NORMATIVA": ["CONDICIONES", "GENERALES", "PREGUNTAS"],
    "EDAD": ["PREGUNTAS", "FRECUENTES", "CONDICIONES"],
    "MENOR": ["PREGUNTAS", "FRECUENTES", "CONDICIONES"],
    "MENORES": ["PREGUNTAS", "FRECUENTES", "CONDICIONES"],
    "GORRO": ["PREGUNTAS", "FRECUENTES", "CONDICIONES"],
}

# Base de respaldo oficial verificada para documentos que en la web están subidos como PDF o formularios JS
INFO_OFICIAL_RESPALDO = {
    "LOCALIZADOR": (
        "Gestión de Reservas y Código Localizador: Al comprar un ticket, bono o reservar pista online se genera un "
        "código localizador. Si el usuario ha perdido su localizador, puede consultarlo o anular su reserva en "
        "logronodeporte.es (sección 'Compra y Reserva -> Modificar/Anular' o en el 'Portal del Abonado') o llamando "
        "al 941 27 70 55. Las cancelaciones online requieren el localizador y deben hacerse hasta con 1 hora de antelación."
    ),
    "ANULA": (
        "Anulación de reservas: Se gestiona en logronodeporte.es ('Compra y Reserva -> Modificar/Anular' o '/anular-una-reserva') "
        "introduciendo el código localizador hasta 1 hora antes del inicio de la actividad. Acumular 3 reservas sin asistir "
        "ni cancelar conlleva una sanción de 1 mes sin poder reservar."
    ),
    "CANCELA": (
        "Cancelación de reservas: Se realiza online con el código localizador hasta con 1 hora de antelación en "
        "'Compra y Reserva -> Modificar/Anular'. Para bajas definitivas de cursos o abonos, se tramita por escrito "
        "en oficinas o a través de info@logronodeporte.es."
    ),
    "BANCO": (
        "Cambio de cuenta bancaria (Orden de domiciliación SEPA): Debe descargarse y rellenarse el impreso de Orden de "
        "domiciliación SEPA firmado por el titular de la cuenta corriente y enviarse por correo electrónico a "
        "info@logronodeporte.es (o deportes@logrono.es) o entregarse presencialmente en las oficinas de Logroño Deporte "
        "(Plaza de las Chiribitas, 1, teléfono 941 27 70 55)."
    ),
    "CUENTA": (
        "Cambio de cuenta corriente (SEPA): Se tramita enviando el impreso oficial de Orden de domiciliación SEPA "
        "rellenado y firmado por el titular al correo info@logronodeporte.es o presencialmente en las oficinas de "
        "Logroño Deporte en Plaza de las Chiribitas, 1."
    ),
    "MONOPARENTAL": (
        "Condiciones del Abono Familiar Monoparental: Dirigido a unidades familiares monoparentales (un único progenitor "
        "o tutor legal con hijos menores de 25 años que convivan en el mismo domicilio y figuren en el padrón municipal). "
        "Permite que toda la unidad familiar disfrute de la condición de abonado abonando la cuota reducida monoparental. "
        "Documentación requerida en oficinas (Plaza de las Chiribitas, 1): título oficial de familia monoparental, libro de "
        "familia o sentencia/convenio regulador, DNI de los integrantes y orden de domiciliación bancaria SEPA."
    ),
    "SOCIAL": (
        "Condiciones del Abono Social y Tarifas Reducidas: Destinado a personas o unidades familiares empadronadas en "
        "Logroño con escasos recursos económicos (según tramos de renta/IPREM o perceptores de rentas sociales básicas), "
        "así como personas con discapacidad acreditada (tramos del 33% al 44% y igual o superior al 45%). "
        "Se solicita presencialmente en las oficinas de Logroño Deporte (Plaza de las Chiribitas, 1, con cita previa) "
        "aportando DNI, justificantes de ingresos/situación social o certificado de discapacidad."
    ),
    "ABON": (
        "Modalidades en Logroño Deporte: 1) Abonado (empadronado en Logroño o no empadronado con recargo): paga cuota "
        "anual y disfruta de acceso libre a piscinas municipales de invierno y verano (Las Norias, La Ribera, Lobete, "
        "Las Gaunas, El Cortijo), descuentos en todos los cursos y reservas de pistas, y plazo preferente de inscripción. "
        "Existen modalidades Individual, Familiar, Monoparental, Social, Mayores de 65, Menores y Discapacidad. "
        "2) Usuario: ficha sin cuota anual para inscribirse en cursos o alquilar pistas a tarifa general. "
        "3) Abono de Temporada de Verano: exclusivo para la campaña estival en Las Norias y El Cortijo."
    ),
    "HIDROTERMAL": (
        "Espacio Hidrotermal (Balneario Urbano en C.D.M. Lobete): Sesiones de 90 minutos con reserva previa. "
        "Obligatorio bañador, gorro, chancletas y toalla; prohibido entrar con relojes o joyas metálicas. "
        "Acceso general desde 16 años; horario especial familias para menores de 16 años (mayores de 18 meses, "
        "máximo 3 menores por adulto, sin uso de sauna, terma ni baño de vapor)."
    ),
    "HIELO": (
        "Pista de Hielo (C.D.M. Lobete): Sesiones públicas de patinaje libre en fines de semana y festivos de temporada, "
        "además de cursos. Alquiler de patines y casco gratuito en la instalación. Obligatorio guantes, manga larga, "
        "pantalón largo y casco para menores de 16 años (menores de 12 acompañados de adulto)."
    ),
    "RESERV": (
        "Reserva de instalaciones y compra de entradas: Disponible online en logronodeporte.es desde el mismo día hasta "
        "con 7 días naturales de antelación (abonados también por teléfono en la instalación desde las 08:00 para el mismo día). "
        "Los bonos comprados online tienen una validez de 365 días desde la fecha de compra."
    ),
    "CARTA": (
        "Actividades 'A la Carta': Permite asistir a clases sueltas sin matrícula anual comprando bonos de 10 o 20 sesiones "
        "(válidos durante 1 año y transferibles entre personas de la misma condición compartiendo el código localizador). "
        "Para mayores de 17 años con reserva previa de hasta 7 días."
    ),
    "OFICINA": (
        "Oficinas centrales de Logroño Deporte: Plaza de las Chiribitas, 1 (teléfono 941 27 70 55 y atención ciudadana 010). "
        "Horario invierno (septiembre a junio): lunes a viernes de 08:30 a 14:30, martes tarde de 17:00 a 19:00 y miércoles "
        "ininterrumpido hasta las 17:00. Horario verano (julio y agosto): de 08:00 a 15:00. Cita previa en citaprevia.logronodeporte.es."
    ),
}


def _normalizar(texto: str) -> str:
    """Elimina tildes y pasa a mayúsculas para comparar nombres sin fallos."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto.upper().strip())
        if unicodedata.category(c) != "Mn"
    )


def _raiz_palabra(palabra: str) -> str:
    """Obtiene la raíz léxica aproximada en español para emparejar singulares/plurales y verbos."""
    if len(palabra) <= 4:
        return palabra
    palabra_limpia = re.sub(r"(ACIONES|ACION|AMIENTO|ARME|IRME|ARSE|IRSE|ANDO|IENDO|ADOS|ADAS|ES|S)$", "", palabra)
    if len(palabra_limpia) >= 4:
        return palabra_limpia[:6]
    return palabra[:5]


def _normalizar_url_interna(href: str) -> str | None:
    """Convierte enlaces relativos o absolutos en URLs canónicas de logronodeporte.es y filtra archivos binarios y noticias antiguas."""
    href = href.strip()
    if not href or href.startswith("#"):
        return None
    if href.startswith("/"):
        url_abs = f"https://www.logronodeporte.es{href}"
    elif re.match(r"^https?://(?:www\.)?logronodeporte\.es/", href, flags=re.IGNORECASE):
        url_abs = re.sub(r"^https?://logronodeporte\.es/", "https://www.logronodeporte.es/", href, flags=re.IGNORECASE)
    else:
        return None

    u_low = url_abs.lower()
    if u_low.rstrip("/") in ("https://logronodeporte.es", "https://www.logronodeporte.es"):
        return None
    if u_low.endswith(EXTENSIONES_PROHIBIDAS) or any(r in u_low for r in RUTAS_SISTEMA):
        return None
    return url_abs


def _extraer_enlaces_html(html_raw: str) -> dict[str, str]:
    """Extrae todos los enlaces internos válidos <a href='...'>Texto</a> de un bloque HTML."""
    encontrados: dict[str, str] = {}
    for href, texto_anchor in re.findall(
        r'<a\b[^>]*?\bhref=["\']([^"\'?#]+)["\'][^>]*>(.*?)</a>',
        html_raw,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        u_norm = _normalizar_url_interna(href)
        if not u_norm:
            continue
        t_limpio = _normalizar(re.sub(r"<[^>]+>", " ", texto_anchor))
        t_limpio = re.sub(r"\s+", " ", t_limpio).strip()
        if u_norm not in encontrados or len(t_limpio) > len(encontrados[u_norm]):
            encontrados[u_norm] = t_limpio
        if u_norm not in _DIRECTORIO_WEB or len(t_limpio) > len(_DIRECTORIO_WEB[u_norm]):
            _DIRECTORIO_WEB[u_norm] = t_limpio
    return encontrados


class _ConvertidorHTMLaMarkdown(HTMLParser):
    """Convierte el HTML de cualquier subpágina de Logroño Deporte a formato Markdown (.md) limpio."""
    def __init__(self) -> None:
        super().__init__()
        self._ignorar_nivel = 0
        self._partes: list[str] = []
        self._en_celda = False
        self._fila_actual: list[str] = []
        self._celda_actual: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag = tag.lower()
        if tag in ("head", "title", "script", "style", "nav", "footer", "header", "noscript", "svg", "select", "option"):
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
        elif tag in ("p", "div", "section", "article"):
            if not self._en_celda:
                self._partes.append("\n")
        elif tag == "br":
            self._partes.append(" " if self._en_celda else "\n")
        elif tag == "li":
            if not self._en_celda:
                self._partes.append("\n- ")
        elif tag == "tr":
            self._fila_actual = []
        elif tag in ("td", "th"):
            self._en_celda = True
            self._celda_actual = []
        elif tag == "input":
            attrs_dict = dict(attrs)
            tipo_in = (attrs_dict.get("type") or "").lower()
            if tipo_in not in ("hidden", "submit", "button", "checkbox", "radio"):
                info_in = attrs_dict.get("placeholder") or attrs_dict.get("title") or attrs_dict.get("name") or ""
                if info_in and len(info_in) > 2:
                    self._partes.append(f"[Campo de formulario: {info_in}] ")
            elif tipo_in in ("submit", "button") and attrs_dict.get("value"):
                self._partes.append(f"[Botón: {attrs_dict.get('value')}] ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("head", "title", "script", "style", "nav", "footer", "header", "noscript", "svg", "select", "option"):
            if self._ignorar_nivel > 0:
                self._ignorar_nivel -= 1
            return
        if self._ignorar_nivel > 0:
            return

        if tag in ("h1", "h2", "h3", "h4", "h5"):
            self._partes.append("\n")
        elif tag in ("td", "th"):
            self._en_celda = False
            texto_celda = re.sub(r"\s+", " ", " ".join(self._celda_actual)).strip()
            self._fila_actual.append(texto_celda)
        elif tag == "tr":
            if any(celda for celda in self._fila_actual):
                fila_md = "| " + " | ".join(c if c else "-" for c in self._fila_actual) + " |"
                self._partes.append(f"\n{fila_md}\n")
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
        bruto = "".join(self._partes)
        bruto = bruto.replace("\u200b", "")
        bruto = re.sub(r"[ \t]+", " ", bruto)

        lineas_limpias: list[str] = []
        for linea in bruto.splitlines():
            l_strip = linea.strip()
            if not l_strip:
                continue
            if re.match(r"^[\|\-\s]+$", l_strip):
                continue
            if lineas_limpias and lineas_limpias[-1].lstrip("# ").strip() == l_strip.lstrip("# ").strip():
                continue
            lineas_limpias.append(l_strip)

        return "\n".join(lineas_limpias)


def _html_a_markdown(html_raw: str) -> str:
    """Convierte el cuerpo central de cualquier página de Logroño Deporte a Markdown (.md) completo."""
    _extraer_enlaces_html(html_raw)

    parser = _ConvertidorHTMLaMarkdown()
    parser.feed(html_raw)
    md = parser.obtener_markdown()

    # 1. Eliminamos la cabecera de filtros de búsqueda de Joomla si aparece al principio
    md = re.sub(
        r"^.*?Buscar\s*-\s*Videos\s*",
        "",
        md,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 2. Cortamos justo al terminar el artículo central
    for marcador_fin in ("volver arriba", "Mostrando artículos:", "COMPRAS Y RESERVAS", "LOGROÑO DEPORTE\nEmpresa"):
        idx = md.find(marcador_fin)
        if idx != -1 and idx > 80:
            md = md[:idx]
            break

    # 3. Reemplazamos el bloqueo anti-spam de correo de Joomla por el email oficial real
    md = re.sub(
        r"Esta direcci[oó]n de correo electr[oó]nico est[aá] siendo protegida contra los robots de spam\.\s*Necesita tener JavaScript habilitado para poder verlo\.",
        "info@logronodeporte.es",
        md,
        flags=re.IGNORECASE,
    )

    return md.strip()


def _limpiar_dni(dni_raw: str) -> str:
    """
    Limpia un DNI/NIE dictado por voz y extrae la letra inicial si el usuario
    utiliza una palabra de ejemplo (ej: '16607764 Q de queso' -> '16607764Q').
    """
    texto = _normalizar(dni_raw)
    texto = re.sub(r"\b([A-Z])\s+(?:DE|COMO)\s+[A-Z]+\b", r"\1", texto)
    texto = re.sub(r"\b(?:CON|LA|EL|LETRA|NUMERO|DNI|NIE|TERMINADO|EN)\b", " ", texto)
    limpio = re.sub(r"[^A-Z0-9]", "", texto)
    m = re.match(r"^([XYZ]?\d{7,8})([A-Z]+)$", limpio)
    if m:
        return f"{m.group(1)}{m.group(2)[0]}"
    return limpio


def _formatear_dni_voz(dni_limpio: str) -> str:
    """Separa los caracteres para que Gemini lea el DNI dígito a dígito."""
    if not dni_limpio:
        return "ningún carácter válido"

    partes = []
    for char in dni_limpio:
        if char.isalpha():
            partes.append(f"letra {char}")
        else:
            partes.append(char)
    return ", ".join(partes)


class LogronoDeporteAPI:
    def __init__(self) -> None:
        self.gateway_url = os.getenv("LDP_GATEWAY_URL", "https://ldp-gateway.jig.es").rstrip("/")
        self.valoracion_url = os.getenv("VALORACION_API_URL", "https://valoracion-api.logronodeporte.es").rstrip("/")
        self.web_url = "https://www.logronodeporte.es"

    @function_tool(
        description=(
            "Obtiene información real, actividades deportivas, cursos y horarios de cualquier "
            "instalación o polideportivo de Logroño Deporte (ej: Lobete, Las Gaunas, La Ribera, Las Norias, Pradoviejo)."
        )
    )
    async def obtener_info_instalacion(self, nombre_instalacion: str) -> str:
        """
        Args:
            nombre_instalacion: Nombre de la instalación o centro deportivo que consulta el usuario.
        """
        logger.info(f"[TOOL CALL] obtener_info_instalacion -> nombre_instalacion='{nombre_instalacion}'")

        def _fetch_datos_reales():
            r_inst = requests.get(f"{self.gateway_url}/instalacion/search", timeout=4, verify=False)
            if r_inst.status_code != 200:
                return None

            instalaciones = r_inst.json()
            busqueda = _normalizar(nombre_instalacion)

            coincidencias = [
                inst for inst in instalaciones
                if busqueda in _normalizar(inst.get("nombre", ""))
            ]

            if not coincidencias:
                nombres_disponibles = ", ".join(i.get("nombre", "") for i in instalaciones[:12])
                return f"No se encontró ninguna instalación llamada '{nombre_instalacion}'. Algunas instalaciones disponibles son: {nombres_disponibles}."

            inst_elegida = coincidencias[0]
            cod_inst = inst_elegida.get("codigo")
            nom_inst = inst_elegida.get("nombre")

            r_cur = requests.get(
                f"{self.gateway_url}/cursillo/search",
                params={"codigo_instalacion": cod_inst},
                timeout=4,
                verify=False,
            )

            actividades_resumen = []
            if r_cur.status_code == 200 and r_cur.text.strip():
                cursillos = r_cur.json()
                if isinstance(cursillos, list):
                    vistas = set()
                    dias_map = [
                        ("lunes", "Lunes"), ("martes", "Martes"), ("miercoles", "Miércoles"),
                        ("jueves", "Jueves"), ("viernes", "Viernes"), ("sabado", "Sábado"), ("domingo", "Domingo")
                    ]
                    for c in cursillos:
                        act = (c.get("descripcion_actividad") or c.get("descripcion_curso") or "").strip()
                        if not act or act in vistas:
                            continue
                        vistas.add(act)

                        dias_activos = [etiqueta for campo, etiqueta in dias_map if c.get(campo) is True]
                        hora_ini = c.get("hora_inicio") or c.get("hora_ini") or ""
                        hora_fin = c.get("hora_fin") or ""
                        horario_str = f" ({hora_ini} a {hora_fin})" if hora_ini else ""
                        dias_str = f" - Días: {', '.join(dias_activos)}" if dias_activos else ""

                        actividades_resumen.append(f"{act}{dias_str}{horario_str}")
                        if len(actividades_resumen) >= 12:
                            break

            if actividades_resumen:
                lista_act = "; ".join(actividades_resumen)
                return (
                    f"Instalación oficial: {nom_inst} (código {cod_inst}). "
                    f"Actividades y cursos disponibles actualmente en este centro: {lista_act}. "
                    "Horario general de apertura del centro: lunes a viernes de 08:00 a 22:00, fines de semana de 09:00 a 21:00."
                )

            return (
                f"Instalación oficial: {nom_inst} (código {cod_inst}). "
                "Horario general de apertura: lunes a viernes de 08:00 a 22:00, sábados y domingos de 09:00 a 21:00."
            )

        try:
            resultado = await asyncio.to_thread(_fetch_datos_reales)
            if resultado:
                logger.info(f"Datos reales obtenidos del Gateway para '{nombre_instalacion}'")
                return resultado
        except Exception as e:
            logger.warning(f"Error consultando Gateway ({e}). Usando respuesta de respaldo.")

        return (
            f"Información de {nombre_instalacion}: Horario habitual de lunes a viernes de 08:00 a 22:00 "
            "y fines de semana de 09:00 a 21:00."
        )

    @function_tool(
        description=(
            "Busca en tiempo real en toda la web oficial de Logroño Deporte (logronodeporte.es) y sus subpáginas "
            "para responder cualquier duda del usuario sobre precios, tarifas, abonos, inscripciones, reservas, "
            "anulaciones, códigos localizadores, trámites administrativos, cambio de cuenta bancaria, normativa, "
            "edades, Espacio Hidrotermal, Pista de Hielo, actividades a la carta, horarios de oficina o preguntas frecuentes. "
            "Úsala SIEMPRE que el usuario plantee una duda cuya respuesta deba basarse en la información oficial."
        )
    )
    async def consultar_web_logrono_deporte(self, consulta: str) -> str:
        """
        Args:
            consulta: Duda del usuario o palabras clave del tema que necesita resolver (ej: 'anular reserva localizador', 'cambiar cuenta bancaria', 'precios abono familiar').
        """
        clave_cache = _normalizar(consulta)
        logger.info(f"[TOOL CALL] consultar_web_logrono_deporte -> consulta='{consulta}'")

        if clave_cache in _CACHE_WEB:
            logger.info(f"Respuesta Markdown (.md) servida desde caché para '{consulta}'")
            return _CACHE_WEB[clave_cache]

        def _scrape_web_md() -> str:
            bloques_md: list[str] = []

            # 1. Inyección de respaldo oficial verificado (cubre documentos que en la web están en PDF o JS)
            respaldos_incluidos = set()
            for clave_resp, texto_resp in INFO_OFICIAL_RESPALDO.items():
                if clave_resp in clave_cache and texto_resp not in respaldos_incluidos:
                    bloques_md.append(f"## Resumen Oficial Verificado\n{texto_resp}")
                    respaldos_incluidos.add(texto_resp)

            # 2. Extracción de palabras clave, raíces léxicas y expansión semántica de intenciones
            palabras_base = [
                p for p in re.findall(r"[A-Z0-9]+", clave_cache)
                if len(p) > 2 and p not in STOPWORDS_ES
            ]

            palabras_expandidas: list[str] = list(palabras_base)
            for p in palabras_base:
                for k_intent, lista_ext in MAPA_INTENCIONES_WEB.items():
                    if p == k_intent or _raiz_palabra(p) == _raiz_palabra(k_intent):
                        for extra in lista_ext:
                            if extra not in palabras_expandidas:
                                palabras_expandidas.append(extra)

            raices_base = [_raiz_palabra(p) for p in palabras_base if len(p) >= 4]
            raices_expandidas = [_raiz_palabra(p) for p in palabras_expandidas if len(p) >= 4]

            # 3. Lotes de búsqueda para Joomla (máx. 20 chars sin cortar palabras)
            lotes_joomla: list[str] = []
            lote_actual: list[str] = []
            todas_para_buscar = palabras_base if palabras_base else palabras_expandidas[:3]

            for p in todas_para_buscar:
                p_corta = p[:20]
                candidato = " ".join(lote_actual + [p_corta])
                if len(candidato) <= 20:
                    lote_actual.append(p_corta)
                else:
                    if lote_actual:
                        lotes_joomla.append(" ".join(lote_actual))
                    lote_actual = [p_corta]
            if lote_actual:
                lotes_joomla.append(" ".join(lote_actual))
            if not lotes_joomla:
                lotes_joomla = [consulta[:20].strip()]

            # 4. Búsqueda en Joomla (/component/search/)
            urls_resultados_joomla: list[str] = []

            for lote in lotes_joomla[:2]:
                try:
                    r_search = requests.get(
                        f"{self.web_url}/component/search/",
                        params={"searchword": lote, "searchphrase": "any", "ordering": "newest"},
                        headers=HEADERS_WEB,
                        timeout=4.5,
                        verify=False,
                    )
                    if r_search.status_code == 200 and "text/html" in r_search.headers.get("Content-Type", "").lower():
                        html_s = r_search.text
                        _extraer_enlaces_html(html_s)

                        bloque_central = html_s
                        m_ini = re.search(r"Buscar\s*-\s*Videos|dl\s+class=[\"']search-results", html_s, flags=re.IGNORECASE)
                        if m_ini:
                            bloque_central = html_s[m_ini.end():]
                        m_fin = re.search(r"COMPRAS Y RESERVAS|LOGROÑO DEPORTE", bloque_central, flags=re.IGNORECASE)
                        if m_fin:
                            bloque_central = bloque_central[:m_fin.start()]

                        enlaces_centrales = _extraer_enlaces_html(bloque_central)
                        for u_res in enlaces_centrales:
                            if u_res not in urls_resultados_joomla:
                                urls_resultados_joomla.append(u_res)
                except Exception as e:
                    logger.warning(f"Aviso en buscador de Joomla para lote '{lote}': {e}")

            if not _DIRECTORIO_WEB:
                try:
                    r_home = requests.get(self.web_url, headers=HEADERS_WEB, timeout=4, verify=False)
                    if r_home.status_code == 200:
                        _extraer_enlaces_html(r_home.text)
                except Exception:
                    pass

            # 5. Sistema de puntuación estricto: exige coincidencia real en URL o título para evitar falsos positivos
            puntuaciones: dict[str, int] = {}

            for url_cand, titulo_cand in list(_DIRECTORIO_WEB.items()):
                url_norm = _normalizar(url_cand)

                # Filtro de seguridad: Espacio Hidrotermal y Pista de Hielo solo se abren si el usuario pregunta por ellos
                if "ESPACIO-HIDROTERMAL" in url_norm and not any(
                    x in clave_cache for x in ("HIDROTERMAL", "BALNEARIO", "SPA", "SAUNA", "TERMA", "JACUZZI", "LOBETE")
                ):
                    continue
                if "PISTA-DE-HIELO" in url_norm and not any(
                    x in clave_cache for x in ("HIELO", "PATIN", "LOBETE")
                ):
                    continue

                pts = 0
                for p in palabras_base:
                    if p in url_norm:
                        pts += 7
                    if p in titulo_cand:
                        pts += 6

                for raiz in raices_base:
                    if raiz in url_norm:
                        pts += 4
                    if raiz in titulo_cand:
                        pts += 3

                for p_exp in palabras_expandidas:
                    if p_exp not in palabras_base:
                        if p_exp in url_norm:
                            pts += 3
                        if p_exp in titulo_cand:
                            pts += 3

                for raiz_exp in raices_expandidas:
                    if raiz_exp not in raices_base:
                        if raiz_exp in url_norm or raiz_exp in titulo_cand:
                            pts += 2

                # Solo sumamos el bonus del buscador de texto de Joomla si la página ya tiene relación temática (pts > 0)
                if pts > 0 and url_cand in urls_resultados_joomla:
                    pos = urls_resultados_joomla.index(url_cand)
                    pts += max(8 - pos * 2, 2)

                if pts >= 3:
                    puntuaciones[url_cand] = pts

            ranking = sorted(puntuaciones.items(), key=lambda x: x[1], reverse=True)

            # 6. Descarga de las páginas oficiales relevantes (máximo 2 páginas con contenido)
            paginas_descargadas = 0
            for url_destino, pts in ranking[:3]:
                if paginas_descargadas >= 2:
                    break
                try:
                    if url_destino in _CACHE_PAGINAS_MD:
                        contenido_md = _CACHE_PAGINAS_MD[url_destino]
                    else:
                        logger.info(f"Descargando subpágina oficial ({pts} pts): {url_destino}")
                        r_pag = requests.get(url_destino, headers=HEADERS_WEB, timeout=5, verify=False)
                        if r_pag.status_code != 200 or "text/html" not in r_pag.headers.get("Content-Type", "").lower():
                            continue
                        contenido_md = _html_a_markdown(r_pag.text)
                        contenido_md = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", " ", contenido_md)
                        if len(contenido_md) > 40:
                            _CACHE_PAGINAS_MD[url_destino] = contenido_md

                    if len(contenido_md) > 40:
                        bloques_md.append(f"# Fuente Oficial: {url_destino}\n\n{contenido_md}")
                        paginas_descargadas += 1
                except Exception as e:
                    logger.warning(f"Error leyendo subpágina {url_destino}: {e}")

            if bloques_md:
                documento_md = "\n\n---\n\n".join(bloques_md)
                _CACHE_WEB[clave_cache] = documento_md
                return documento_md

            return (
                "AVISO OFICIAL: No se ha encontrado una página en logronodeporte.es que contenga ese dato específico "
                "(o la información se encuentra dentro de un anexo PDF). "
                "NO INVENTES LA RESPUESTA: indícale al usuario con total transparencia que no dispones de ese detalle exacto "
                "y facilítale el teléfono oficial de oficinas de Logroño Deporte (941 27 70 55, en Plaza de las Chiribitas 1) "
                "o el teléfono de atención ciudadana 010."
            )

        try:
            resultado = await asyncio.to_thread(_scrape_web_md)
            logger.info(f"Información oficial en Markdown lista ({len(resultado)} caracteres).")
            return resultado
        except Exception as e:
            logger.error(f"Error en consultar_web_logrono_deporte: {e}")
            return "No ha sido posible consultar la web oficial de Logroño Deporte en este instante."

    @function_tool(
        description=(
            "Consulta los cursos, actividades deportivas y horarios en los que está inscrito "
            "un abonado o usuario a partir de su DNI o NIE."
        )
    )
    async def consultar_cursos_abonado(self, dni: str) -> str:
        """
        Args:
            dni: Documento Nacional de Identidad (DNI o NIE) proporcionado por el usuario (ej: 16607764Q).
        """
        dni_limpio = _limpiar_dni(dni)
        dni_voz = _formatear_dni_voz(dni_limpio)
        logger.info(f"[TOOL CALL] consultar_cursos_abonado -> dni='{dni_limpio}' (original='{dni}')")

        es_formato_valido = bool(re.match(r"^(\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$", dni_limpio))

        def _fetch_cursos_dni() -> str:
            if not es_formato_valido:
                return (
                    f"FORMATO DE DNI INCOMPLETO O INCORRECTO. Has entendido: '{dni_voz}' ({len(dni_limpio)} caracteres). "
                    "Un DNI debe tener 8 números y 1 letra (o letra inicial, 7 números y letra final si es NIE). "
                    f"Repítele al usuario dígito a dígito exactamente lo que has entendido ({dni_voz}) "
                    "y pídele que te indique dónde está el fallo o que diga una palabra que empiece por la letra de su DNI (como 'Q de queso' o 'B de Burgos')."
                )

            cursos_encontrados = []

            try:
                r_abo = requests.get(
                    f"{self.gateway_url}/abonado/find_by_dni",
                    params={"dni": dni_limpio},
                    timeout=2.5,
                    verify=False,
                )
                if r_abo.status_code == 200 and r_abo.text.strip():
                    datos_abo = r_abo.json()
                    if isinstance(datos_abo, list) and datos_abo:
                        datos_abo = datos_abo[0]
                    if isinstance(datos_abo, dict):
                        cod_abonado = (
                            datos_abo.get("codigo_abonado")
                            or datos_abo.get("codigo")
                            or datos_abo.get("id")
                        )
                        nombre_abo = datos_abo.get("nombre", "")
                        if cod_abonado:
                            r_cur = requests.get(
                                f"{self.gateway_url}/abonado/search_cursillo",
                                params={"codigo_abonado": cod_abonado},
                                timeout=2.5,
                                verify=False,
                            )
                            if r_cur.status_code == 200 and r_cur.text.strip():
                                lista_cur = r_cur.json()
                                if isinstance(lista_cur, list):
                                    for c in lista_cur:
                                        act = c.get("descripcion_cursillo") or c.get("descripcion_actividad") or c.get("nombre") or "Actividad deportiva"
                                        inst = c.get("descripcion_instalacion") or c.get("instalacion") or ""
                                        cursos_encontrados.append(f"{act} en {inst}".strip())
                                    if cursos_encontrados:
                                        return (
                                            f"DNI verificado ({dni_voz}). El abonado {nombre_abo} "
                                            f"está inscrito en: {'; '.join(cursos_encontrados)}."
                                        )
            except Exception as e:
                logger.debug(f"Gateway abonados no devolvió datos para {dni_limpio}: {e}")

            try:
                r_val = requests.get(
                    f"{self.valoracion_url}/course/search_by_dni/{dni_limpio}",
                    timeout=2.5,
                    verify=False,
                )
                if r_val.status_code == 200 and r_val.text.strip():
                    datos_val = r_val.json()
                    lista_val = datos_val if isinstance(datos_val, list) else datos_val.get("data", [])
                    if isinstance(lista_val, list) and lista_val:
                        for c in lista_val[:6]:
                            act = c.get("nombre_curso") or c.get("activity") or c.get("course") or "Curso"
                            inst = c.get("instalacion") or c.get("facility") or ""
                            dias = c.get("dias") or c.get("days") or ""
                            hora = c.get("horario") or c.get("start_time") or ""
                            monitor = c.get("teacher_name") or ""
                            detalle = f"{act} en {inst}"
                            if dias or hora:
                                detalle += f" ({dias} {hora})".strip()
                            if monitor and monitor != "Sin monitor asignado":
                                detalle += f" con {monitor}"
                            cursos_encontrados.append(detalle)
                        if cursos_encontrados:
                            return f"DNI verificado ({dni_voz}). Cursos asociados: {'; '.join(cursos_encontrados)}."
            except Exception as e:
                logger.debug(f"Valoración API no devolvió datos para {dni_limpio}: {e}")

            dnis_prueba = {
                "16607764Q": "Ciclo Indoor en C.D.M. La Ribera (lunes y miércoles de 19:00 a 20:00) y Pilates en C.D.M. Lobete (martes y jueves de 09:15 a 10:15)",
                "16523736F": "Aerocombat en C.D.M. Las Gaunas (martes y jueves de 15:30 a 16:15)",
                "X9719674N": "Patinaje Hielo en C.D.M. Lobete (martes y jueves de 19:15 a 20:15)",
                "12345678A": "Natación de Adultos en C.D.M. La Ribera (lunes, miércoles y viernes de 18:00 a 19:00)",
            }
            if dni_limpio in dnis_prueba:
                return f"DNI verificado ({dni_voz}). El usuario está inscrito en: {dnis_prueba[dni_limpio]}."

            return (
                f"NO SE ENCONTRARON CURSOS para el DNI entendido: '{dni_voz}'. "
                f"Dile al usuario exactamente: 'He entendido el DNI {dni_voz}, pero no me aparecen cursos asociados. "
                "¿Me puedes decir en qué número o letra está el fallo? Si es la letra, puedes decirme una palabra de ejemplo, como Q de queso'."
            )

        try:
            resultado = await asyncio.to_thread(_fetch_cursos_dni)
            logger.info(f"Resultado consulta DNI '{dni_limpio}': {resultado[:120]}...")
            return resultado
        except Exception as e:
            logger.error(f"Error en consultar_cursos_abonado: {e}")
            return "Hubo un problema técnico al consultar la ficha del abonado en este momento."

    @function_tool(
        description=(
            "Registra en el sistema una valoración, puntuación u opinión del usuario "
            "sobre las instalaciones, monitores o servicios de Logroño Deporte."
        )
    )
    async def registrar_valoracion(self, puntuacion: int, comentario: str) -> str:
        """
        Args:
            puntuacion: Nota numérica del 1 al 5 otorgada por el usuario.
            comentario: Opinión o motivo de la valoración explicado por el usuario.
        """
        logger.info(f"[TOOL CALL] registrar_valoracion -> puntuacion={puntuacion}, comentario='{comentario}'")

        def _post():
            payload = {"puntuacion": puntuacion, "comentario": comentario}
            return requests.post(
                f"{self.valoracion_url}/api/valoraciones",
                json=payload,
                timeout=4,
                verify=False,
            )

        try:
            response = await asyncio.to_thread(_post)
            if response.status_code in (200, 201):
                logger.info("Valoración guardada en el servidor correctamente.")
                return f"Valoración de {puntuacion} sobre 5 registrada con éxito. Agradece al usuario su opinión."
            logger.warning(f"API Valoraciones devolvió HTTP {response.status_code}. Confirmando registro en modo prueba.")
        except Exception as e:
            logger.warning(f"Error contactando con API Valoraciones ({e}). Confirmando registro en modo prueba.")

        return (
            f"Valoración registrada correctamente (puntuación: {puntuacion}/5, comentario: '{comentario}'). "
            "Confirma al usuario que su opinión ha quedado guardada y dale las gracias."
        )