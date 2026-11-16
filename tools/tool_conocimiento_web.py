import re
import asyncio
import logging
from livekit.agents import function_tool

from tools.utils import normalizar_texto, obtener_raiz
from datos_web.buscador_local import buscar_en_md_locales
from datos_web.buscador_web import cargar_catalogo_urls, buscar_en_web_en_vivo

logger = logging.getLogger("tools.conocimiento_web")

_STOPWORDS_CONSULTA = {
    "PARA", "COMO", "CUAL", "CUALES", "DONDE", "CUANDO", "TIENE", "TIENEN",
    "LOGRONO", "DEPORTE", "SOBRE", "QUIERO", "SABER", "PUEDO", "PUEDE",
    "HACER", "TENGO", "HAY", "QUE", "UNA", "UNO", "LOS", "LAS", "CON",
    "POR", "SIN", "MIS", "SUS", "ESTA", "ESTE"
}


def _resolver_consulta(consulta: str) -> str:
    """
    1. Busca primero en los 5 archivos .md locales (instantáneo).
    2. Si la pregunta no está cubierta ahí, consulta logronodeporte.es en vivo.
    """
    consulta_norm = normalizar_texto(consulta)
    palabras = [
        p for p in re.findall(r"[A-Z0-9]+", consulta_norm)
        if len(p) > 2 and p not in _STOPWORDS_CONSULTA
    ]
    raices = [obtener_raiz(p) for p in palabras if len(p) >= 4]

    max_pts, bloques_locales = buscar_en_md_locales(palabras, raices)

    catalogo_especifico = cargar_catalogo_urls()
    pide_url_especifica = any(p in catalogo_especifico for p in palabras)

    if max_pts >= 12 and not pide_url_especifica:
        return "\n\n---\n\n".join(bloques_locales)

    logger.info(f"Buscando en vivo en logronodeporte.es para: '{consulta}' (pts locales={max_pts})")
    bloques_web = buscar_en_web_en_vivo(consulta, palabras)

    combinados = bloques_web + bloques_locales[:2]
    if combinados:
        return "\n\n---\n\n".join(combinados[:3])

    return (
        "AVISO OFICIAL: No se ha encontrado ese dato específico en la documentación de Logroño Deporte. "
        "NO INVENTES LA RESPUESTA: indícale al usuario con transparencia que no dispones de ese detalle exacto "
        "y facilítale el teléfono de las oficinas de Logroño Deporte (941 27 70 55, en Plaza de las Chiribitas 1) "
        "o el teléfono de atención ciudadana 010."
    )


class ToolConocimientoWeb:
    @function_tool(
        description=(
            "Consulta la base de conocimiento oficial y la web en vivo de Logroño Deporte (logronodeporte.es) "
            "para responder cualquier duda del usuario sobre precios, tarifas 2026, abonos, inscripciones, reservas, "
            "anulaciones, códigos localizadores, trámites, cambio de cuenta bancaria, normativa, edades, "
            "instalaciones, Espacio Hidrotermal, Pista de Hielo, salas de musculación, actividades a la carta, "
            "horarios de oficina, preguntas frecuentes o información corporativa. "
            "Úsala SIEMPRE que el usuario plantee una duda cuya respuesta deba basarse en la información oficial."
        )
    )
    async def consultar_web_logrono_deporte(self, consulta: str) -> str:
        """
        Args:
            consulta: Duda del usuario o palabras clave del tema que necesita resolver.
        """
        logger.info(f"[TOOL] consultar_web_logrono_deporte -> '{consulta}'")
        try:
            return await asyncio.to_thread(_resolver_consulta, consulta)
        except Exception as e:
            logger.error(f"Error en consultar_web_logrono_deporte: {e}")
            return "No ha sido posible consultar la información oficial de Logroño Deporte en este instante."