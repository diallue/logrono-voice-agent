import os
import re
import asyncio
import logging
import requests
import urllib3
from livekit.agents import function_tool

from tools.utils import normalizar_texto, obtener_raiz
from datos_web.buscador_local import buscar_en_md_locales
from datos_web.conversor_md import html_a_markdown
from datos_web.ubicaciones import buscar_ubicacion, formatear_ubicacion_voz

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("tools.instalaciones")

URL_OCUPACION_GIMNASIOS = "https://www.logronodeporte.es/instalaciones/salas-de-musculacion"

_DIAS_SEMANA = [
    ("lunes", "Lunes"), ("martes", "Martes"), ("miercoles", "Miércoles"),
    ("jueves", "Jueves"), ("viernes", "Viernes"), ("sabado", "Sábado"), ("domingo", "Domingo")
]

_HORARIO_APERTURA_DEFECTO = "lunes a viernes de 08:00 a 22:00 y fines de semana de 09:00 a 21:00"

_REGEX_AFORO_SALA = re.compile(
    r"Sala de musculaci[oó]n\s*-\s*([^\n]+)\n([^\n]+)\n(\d{1,2}:\d{2})\s+(\d+)\s+plazas ocupadas de\s+(\d+)\s+totales",
    re.IGNORECASE,
)


def _formatear_cursillo(curso: dict, incluir_centro: bool = False) -> str:
    """Convierte un JSON de cursillo del Gateway en un texto legible con centro, días y horas."""
    nombre = (curso.get("descripcion_actividad") or curso.get("descripcion_curso") or "").strip()
    centro = (curso.get("descripcion_instalacion") or curso.get("instalacion") or "").strip()
    dias = [etiqueta for campo, etiqueta in _DIAS_SEMANA if curso.get(campo) is True]
    hora_ini = curso.get("hora_inicio") or curso.get("hora_ini") or ""
    hora_fin = curso.get("hora_fin") or ""

    encabezado = f"{nombre} en {centro}" if (incluir_centro and centro) else nombre
    partes = [encabezado]
    if dias:
        partes.append(f"Días: {', '.join(dias)}")
    if hora_ini:
        partes.append(f"({hora_ini} a {hora_fin})")
    return " - ".join(partes)


def _consultar_instalacion_gateway(base_url: str, nombre_buscado: str) -> str | None:
    """Busca la instalación en el Gateway y devuelve sus actividades activas y dirección oficial."""
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

    ubi = buscar_ubicacion(nom_inst, codigo_gateway=cod_inst)
    texto_ubi = f" Dirección oficial: {ubi['direccion']}." if ubi and ubi.get("direccion") else ""

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
            f"Instalación oficial: {nom_inst} (código {cod_inst}).{texto_ubi} "
            f"Actividades y cursos disponibles en este centro: {'; '.join(actividades_unicas)}. "
            f"Horario general de apertura del centro: {_HORARIO_APERTURA_DEFECTO}."
        )

    return (
        f"Instalación oficial: {nom_inst} (código {cod_inst}).{texto_ubi} "
        f"Horario general de apertura: {_HORARIO_APERTURA_DEFECTO}."
    )


def _buscar_actividad_en_centros(base_url: str, nombre_actividad: str) -> str:
    """Busca en qué instalaciones se imparte un deporte concreto mostrando variedad de centros."""
    url_base = base_url.rstrip("/")
    busqueda = normalizar_texto(nombre_actividad)
    palabras = [p for p in busqueda.split() if len(p) > 2] or [busqueda]
    raices = [obtener_raiz(p) for p in palabras if len(p) >= 4]

    resultados_gateway: list[str] = []
    vistos: set[str] = set()
    conteo_por_centro: dict[str, int] = {}

    try:
        r_inst = requests.get(f"{url_base}/instalacion/search", timeout=3.5, verify=False)
        instalaciones = r_inst.json() if r_inst.status_code == 200 else []

        r_cur = requests.get(f"{url_base}/cursillo/search", timeout=4, verify=False)
        lista_cursos = r_cur.json() if (r_cur.status_code == 200 and r_cur.text.strip()) else []

        if not isinstance(lista_cursos, list) or not lista_cursos:
            lista_cursos = []
            for inst in instalaciones[:8]:
                cod = inst.get("codigo")
                nom_centro = inst.get("nombre", "")
                r_c = requests.get(
                    f"{url_base}/cursillo/search",
                    params={"codigo_instalacion": cod},
                    timeout=2.0,
                    verify=False,
                )
                if r_c.status_code == 200 and r_c.text.strip():
                    datos_c = r_c.json()
                    if isinstance(datos_c, list):
                        for item in datos_c:
                            item.setdefault("descripcion_instalacion", nom_centro)
                            lista_cursos.append(item)

        for c in lista_cursos:
            nom_act = normalizar_texto(c.get("descripcion_actividad") or c.get("descripcion_curso") or "")
            if not nom_act:
                continue
            if any(p in nom_act for p in palabras) or any(r in nom_act for r in raices):
                centro = (c.get("descripcion_instalacion") or c.get("instalacion") or "Centro").strip()
                if conteo_por_centro.get(centro, 0) >= 3:
                    continue

                resumen_c = _formatear_cursillo(c, incluir_centro=True)
                if resumen_c not in vistos:
                    vistos.add(resumen_c)
                    conteo_por_centro[centro] = conteo_por_centro.get(centro, 0) + 1
                    resultados_gateway.append(resumen_c)
                    if len(resultados_gateway) >= 12:
                        break
    except Exception as e:
        logger.debug(f"Aviso buscando actividad '{nombre_actividad}' en Gateway: {e}")

    _, bloques_md = buscar_en_md_locales(palabras, raices)

    partes_respuesta: list[str] = []
    if resultados_gateway:
        partes_respuesta.append(
            f"Cursos activos de '{nombre_actividad}' encontrados en instalaciones de Logroño Deporte: "
            + "; ".join(resultados_gateway) + "."
        )
    if bloques_md:
        partes_respuesta.append(f"Información adicional en normativa/web:\n{bloques_md[0][:1500]}")

    if partes_respuesta:
        return "\n\n".join(partes_respuesta)

    return (
        f"No se han encontrado cursos activos con el nombre exacto '{nombre_actividad}'. "
        "Indica al usuario que puede consultar el listado completo en logronodeporte.es o llamando al 941 27 70 55."
    )


def _obtener_ocupacion_gimnasios_vivo(instalacion: str = "") -> str:
    """Consulta en directo el contador de ocupación actual de las salas de musculación."""
    try:
        resp = requests.get(URL_OCUPACION_GIMNASIOS, timeout=5, verify=False)
        if resp.status_code != 200:
            raise ConnectionError(f"HTTP {resp.status_code}")

        md = html_a_markdown(resp.text)
        coincidencias = _REGEX_AFORO_SALA.findall(md)

        if coincidencias:
            filtro = normalizar_texto(instalacion)
            salas_info: list[str] = []

            for nombre_sala, dia_texto, hora, ocupadas_str, totales_str in coincidencias:
                if filtro and filtro not in normalizar_texto(nombre_sala):
                    continue
                ocupadas = int(ocupadas_str)
                totales = int(totales_str)
                libres = max(0, totales - ocupadas)
                salas_info.append(
                    f"C.D.M. {nombre_sala.strip()}: {ocupadas} plazas ocupadas de {totales} "
                    f"({libres} plazas libres a las {hora})"
                )

            if salas_info:
                return (
                    "Ocupación en tiempo real de las salas de musculación: "
                    + "; ".join(salas_info)
                    + ". El acceso es directo con carnet de abonado o código QR sin reserva previa mientras haya plazas libres."
                )
    except Exception as e:
        logger.warning(f"No se pudo obtener ocupación en vivo ({e}). Mostrando aforos oficiales.")

    return (
        "En este instante no está disponible el contador en vivo, pero los aforos máximos oficiales son: "
        "C.D.M. La Ribera 65 plazas, C.D.M. Lobete 50 plazas y C.D.M. Las Gaunas 40 plazas "
        "(acceso directo sin reserva previa de lunes a viernes de 07:00 a 22:30 y sábados de 08:00 a 22:30)."
    )


class ToolInstalaciones:
    @function_tool(
        description=(
            "Obtiene información real, dirección, actividades deportivas, cursos y horarios de cualquier "
            "instalación o polideportivo concreto de Logroño Deporte (ej: Lobete, La Ribera, Las Gaunas, Las Norias)."
        )
    )
    async def obtener_info_instalacion(self, nombre_instalacion: str) -> str:
        """
        Args: nombre_instalacion: Nombre de la instalación o centro deportivo que consulta el usuario.
        """
        logger.info(f"[TOOL] obtener_info_instalacion -> '{nombre_instalacion}'")
        gateway_url = os.getenv("LDP_GATEWAY_URL", "https://ldp-gateway.jig.es")

        try:
            resultado = await asyncio.to_thread(_consultar_instalacion_gateway, gateway_url, nombre_instalacion)
            if resultado:
                return resultado
        except Exception as e:
            logger.warning(f"Error consultando Gateway para '{nombre_instalacion}': {e}")

        ubi = buscar_ubicacion(nombre_instalacion)
        texto_ubi = f" Dirección oficial: {ubi['direccion']}." if ubi and ubi.get("direccion") else ""
        return f"Información de {nombre_instalacion}.{texto_ubi} Horario habitual de {_HORARIO_APERTURA_DEFECTO}."

    @function_tool(
        description=(
            "Devuelve la dirección oficial exacta, referencias cercanas, paradas y líneas de autobús urbano "
            "con minutos andando hasta la entrada y teléfono de cualquiera de las 35 instalaciones deportivas "
            "municipales de Logroño Deporte. Úsala SIEMPRE que el usuario pregunte dónde está una instalación "
            "deportiva o cómo llegar a ella. Para la dirección u horario de las oficinas centrales, usa "
            "consultar_web_logrono_deporte."
        )
    )
    async def obtener_ubicacion_instalacion(self, nombre_instalacion: str) -> str:
        """
        Args: nombre_instalacion: Nombre del centro deportivo, polideportivo, campo, piscina o frontón por el que pregunta el usuario.
        """
        logger.info(f"[TOOL] obtener_ubicacion_instalacion -> '{nombre_instalacion}'")
        ubi = buscar_ubicacion(nombre_instalacion)
        if ubi and ubi.get("direccion"):
            return formatear_ubicacion_voz(ubi)
        return (
            f"No figura ninguna instalación municipal de Logroño Deporte llamada '{nombre_instalacion}' "
            "en el catálogo oficial de ubicaciones. No inventes la dirección: indícalo con claridad "
            "y remite al usuario a logronodeporte.es o al teléfono 941 27 70 55."
        )

    @function_tool(
        description=(
            "Busca en qué instalaciones o polideportivos de Logroño Deporte se imparte un deporte "
            "o actividad concreta (ej: Pilates, Zumba, Natación, Boxeo, Pádel, Ciclo Indoor, Yoga) "
            "y devuelve sus días, horarios y detalles."
        )
    )
    async def buscar_actividad_deportiva(self, nombre_actividad: str) -> str:
        """
        Args: nombre_actividad: Nombre del deporte, curso o actividad por la que pregunta el usuario.
        """
        logger.info(f"[TOOL] buscar_actividad_deportiva -> '{nombre_actividad}'")
        gateway_url = os.getenv("LDP_GATEWAY_URL", "https://ldp-gateway.jig.es")

        try:
            return await asyncio.to_thread(_buscar_actividad_en_centros, gateway_url, nombre_actividad)
        except Exception as e:
            logger.error(f"Error en buscar_actividad_deportiva para '{nombre_actividad}': {e}")
            return f"No ha sido posible consultar los centros donde se imparte {nombre_actividad} en este momento."

    @function_tool(
        description=(
            "Consulta en tiempo real cuánta gente hay ahora mismo (ocupación actual, aforo y plazas libres) "
            "en los gimnasios y salas de musculación de Logroño Deporte (Lobete, La Ribera y Las Gaunas)."
        )
    )
    async def consultar_ocupacion_gimnasios(self, instalacion: str = "") -> str:
        """
        Args: instalacion: Nombre del gimnasio si el usuario pregunta por uno concreto (ej: 'Lobete', 'La Ribera', 'Las Gaunas') o vacío para ver los tres.
        """
        logger.info(f"[TOOL] consultar_ocupacion_gimnasios -> '{instalacion}'")
        return await asyncio.to_thread(_obtener_ocupacion_gimnasios_vivo, instalacion)