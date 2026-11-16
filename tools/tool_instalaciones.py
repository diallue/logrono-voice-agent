import os
import asyncio
import logging
import requests
import urllib3
from livekit.agents import function_tool

from tools.utils import normalizar_texto

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("tools.instalaciones")

_DIAS_SEMANA = [("lunes", "Lunes"), ("martes", "Martes"), ("miercoles", "Miércoles"), ("jueves", "Jueves"), ("viernes", "Viernes"), ("sabado", "Sábado"), ("domingo", "Domingo")]

_HORARIO_APERTURA_DEFECTO = ("lunes a viernes de 08:00 a 22:00 y fines de semana de 09:00 a 21:00")


def _formatear_cursillo(curso: dict) -> str:
    """Convierte un JSON de cursillo del Gateway en un texto legible con días y horas."""
    nombre = (curso.get("descripcion_actividad") or curso.get("descripcion_curso") or "").strip()
    dias = [etiqueta for campo, etiqueta in _DIAS_SEMANA if curso.get(campo) is True]
    hora_ini = curso.get("hora_inicio") or curso.get("hora_ini") or ""
    hora_fin = curso.get("hora_fin") or ""

    partes = [nombre]
    if dias:
        partes.append(f"Días: {', '.join(dias)}")
    if hora_ini:
        partes.append(f"({hora_ini} a {hora_fin})")
    return " - ".join(partes)


def _consultar_instalacion_gateway(base_url: str, nombre_buscado: str) -> str | None:
    """Busca la instalación en el Gateway y devuelve sus actividades activas."""
    url_base = base_url.rstrip("/")
    r_inst = requests.get(f"{url_base}/instalacion/search", timeout=4, verify=False)
    if r_inst.status_code != 200:
        return None

    instalaciones = r_inst.json()
    busqueda = normalizar_texto(nombre_buscado)
    coincidencias = [i for i in instalaciones if busqueda in normalizar_texto(i.get("nombre", ""))]

    if not coincidencias:
        disponibles = ", ".join(i.get("nombre", "") for i in instalaciones[:12])
        return (
            f"No se encontró ninguna instalación llamada '{nombre_buscado}'. "
            f"Algunas instalaciones disponibles son: {disponibles}."
        )

    instalacion = coincidencias[0]
    cod_inst = instalacion.get("codigo")
    nom_inst = instalacion.get("nombre")

    r_cur = requests.get(
        f"{url_base}/cursillo/search",
        params={"codigo_instalacion": cod_inst},
        timeout=4,
        verify=False,
    )

    actividades_unicas: list[str] = []
    vistas: set[str] = set()

    if r_cur.status_code == 200 and r_cur.text.strip():
        cursillos = r_cur.json()
        if isinstance(cursillos, list):
            for c in cursillos:
                nombre_act = (c.get("descripcion_actividad") or c.get("descripcion_curso") or "").strip()
                if not nombre_act or nombre_act in vistas:
                    continue
                vistas.add(nombre_act)
                actividades_unicas.append(_formatear_cursillo(c))
                if len(actividades_unicas) >= 12:
                    break

    if actividades_unicas:
        return (
            f"Instalación oficial: {nom_inst} (código {cod_inst}). "
            f"Actividades y cursos disponibles en este centro: {'; '.join(actividades_unicas)}. "
            f"Horario general de apertura del centro: {_HORARIO_APERTURA_DEFECTO}."
        )

    return (
        f"Instalación oficial: {nom_inst} (código {cod_inst}). "
        f"Horario general de apertura: {_HORARIO_APERTURA_DEFECTO}."
    )


class ToolInstalaciones:
    @function_tool(
        description=(
            "Obtiene información real, actividades deportivas, cursos y horarios de cualquier instalación o polideportivo de Logroño Deporte."
        )
    )
    async def obtener_info_instalacion(self, nombre_instalacion: str) -> str:
        """
        Args:
            nombre_instalacion: Nombre de la instalación o centro deportivo que consulta el usuario.
        """
        logger.info(f"[TOOL] obtener_info_instalacion -> '{nombre_instalacion}'")
        gateway_url = os.getenv("LDP_GATEWAY_URL", "https://ldp-gateway.jig.es")

        try:
            resultado = await asyncio.to_thread(_consultar_instalacion_gateway, gateway_url, nombre_instalacion)
            if resultado:
                return resultado
        except Exception as e:
            logger.warning(f"Error consultando Gateway para '{nombre_instalacion}': {e}")

        return f"Información de {nombre_instalacion}: Horario habitual de {_HORARIO_APERTURA_DEFECTO}."