import os
import asyncio
import logging
import requests
import urllib3
from livekit.agents import function_tool

from tools.utils import limpiar_dni, es_dni_valido, formatear_dni_voz

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("tools.abonados_dni")

DNIS_PRUEBA = {
    "16607764Q": "Ciclo Indoor en C.D.M. La Ribera (lunes y miércoles de 19:00 a 20:00) y Pilates en C.D.M. Lobete (martes y jueves de 09:15 a 10:15)",
    "16523736F": "Aerocombat en C.D.M. Las Gaunas (martes y jueves de 15:30 a 16:15)",
    "X9719674N": "Patinaje Hielo en C.D.M. Lobete (martes y jueves de 19:15 a 20:15)",
    "12345678A": "Natación de Adultos en C.D.M. La Ribera (lunes, miércoles y viernes de 18:00 a 19:00)",
}


def _buscar_cursos_gateway(base_url: str, dni: str) -> str | None:
    """Vía 1: Busca el código de abonado por DNI en el gateway y consulta sus cursillos."""
    url_base = base_url.rstrip("/")
    r_abo = requests.get(f"{url_base}/abonado/find_by_dni", params={"dni": dni}, timeout=2.5, verify=False)
    if r_abo.status_code != 200 or not r_abo.text.strip():
        return None

    datos_abo = r_abo.json()
    if isinstance(datos_abo, list) and datos_abo:
        datos_abo = datos_abo[0]
    if not isinstance(datos_abo, dict):
        return None

    cod_abonado = datos_abo.get("codigo_abonado") or datos_abo.get("codigo") or datos_abo.get("id")
    if not cod_abonado:
        return None

    r_cur = requests.get(
        f"{url_base}/abonado/search_cursillo",
        params={"codigo_abonado": cod_abonado},
        timeout=2.5,
        verify=False,
    )
    if r_cur.status_code != 200 or not r_cur.text.strip():
        return None

    lista_cur = r_cur.json()
    if not isinstance(lista_cur, list) or not lista_cur:
        return None

    cursos = [
        f"{c.get('descripcion_cursillo') or c.get('descripcion_actividad') or c.get('nombre') or 'Actividad'} "
        f"en {c.get('descripcion_instalacion') or c.get('instalacion') or ''}".strip()
        for c in lista_cur
    ]
    return "; ".join(cursos) if cursos else None


def _buscar_cursos_valoracion_api(base_url: str, dni: str) -> str | None:
    """Vía 2: Consulta directamente los cursos del DNI en la API de Valoraciones."""
    url = f"{base_url.rstrip('/')}/course/search_by_dni/{dni}"
    r_val = requests.get(url, timeout=2.5, verify=False)
    if r_val.status_code != 200 or not r_val.text.strip():
        return None

    datos = r_val.json()
    lista = datos if isinstance(datos, list) else datos.get("data", [])
    if not isinstance(lista, list) or not lista:
        return None

    cursos = []
    for c in lista[:6]:
        act = c.get("nombre_curso") or c.get("activity") or c.get("course") or "Curso"
        inst = c.get("instalacion") or c.get("facility") or ""
        dias = c.get("dias") or c.get("days") or ""
        hora = c.get("horario") or c.get("start_time") or ""
        monitor = c.get("teacher_name") or ""

        detalle = f"{act} en {inst}".strip()
        if dias or hora:
            detalle += f" ({dias} {hora})".strip()
        if monitor and monitor != "Sin monitor asignado":
            detalle += f" con {monitor}"
        cursos.append(detalle)

    return "; ".join(cursos) if cursos else None


def _obtener_ficha_dni(gateway_url: str, valoracion_url: str, dni_limpio: str, dni_voz: str) -> str:
    """Orquesta la validación y búsqueda secuencial en las 3 fuentes."""
    if not es_dni_valido(dni_limpio):
        return (
            f"FORMATO DE DNI INCOMPLETO O INCORRECTO. Has entendido: '{dni_voz}' ({len(dni_limpio)} caracteres). Un DNI debe tener 8 números y 1 letra (o letra inicial, 7 números y letra final si es NIE). "
            f"Repítele al usuario dígito a dígito exactamente lo que has entendido ({dni_voz}) y pídele que te indique dónde está el fallo o que diga una palabra que empiece por la letra de su DNI (como 'Q de queso' o 'B de Burgos')."
        )

    try:
        cursos_gw = _buscar_cursos_gateway(gateway_url, dni_limpio)
        if cursos_gw:
            return f"DNI verificado ({dni_voz}). El abonado está inscrito en: {cursos_gw}."
    except Exception as e:
        logger.debug(f"Gateway sin datos para {dni_limpio}: {e}")

    try:
        cursos_val = _buscar_cursos_valoracion_api(valoracion_url, dni_limpio)
        if cursos_val:
            return f"DNI verificado ({dni_voz}). Cursos asociados: {cursos_val}."
    except Exception as e:
        logger.debug(f"Valoración API sin datos para {dni_limpio}: {e}")

    if dni_limpio in DNIS_PRUEBA:
        return f"DNI verificado ({dni_voz}). El usuario está inscrito en: {DNIS_PRUEBA[dni_limpio]}."

    return (
        f"NO SE ENCONTRARON CURSOS para el DNI entendido: '{dni_voz}'. "
        f"Dile al usuario exactamente: 'He entendido el DNI {dni_voz}, pero no me aparecen cursos asociados. "
        "¿Me puedes decir en qué número o letra está el fallo? Si es la letra, puedes decirme una palabra de ejemplo, como Q de queso'."
    )


class ToolAbonadosDNI:
    @function_tool(
        description=(
            "Consulta los cursos, actividades deportivas y horarios en los que está inscrito un abonado o usuario a partir de su DNI o NIE."
        )
    )
    async def consultar_cursos_abonado(self, dni: str) -> str:
        """
        Args:
            dni: DNI o NIE proporcionado por el usuario.
        """
        dni_limpio = limpiar_dni(dni)
        dni_voz = formatear_dni_voz(dni_limpio)
        logger.info(f"[TOOL] consultar_cursos_abonado -> limpio='{dni_limpio}' (original='{dni}')")

        gateway_url = os.getenv("LDP_GATEWAY_URL", "https://ldp-gateway.jig.es")
        valoracion_url = os.getenv("VALORACION_API_URL", "https://valoracion-api.logronodeporte.es")

        try:
            return await asyncio.to_thread(_obtener_ficha_dni, gateway_url, valoracion_url, dni_limpio, dni_voz)
        except Exception as e:
            logger.error(f"Error en consultar_cursos_abonado: {e}")
            return "Hubo un problema técnico al consultar la ficha del abonado en este momento."