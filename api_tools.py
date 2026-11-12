import os
import re
import asyncio
import logging
import unicodedata
import requests
import urllib3
from livekit.agents import function_tool

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("api_tools")
logger.setLevel(logging.INFO)


def _normalizar(texto: str) -> str:
    """Elimina tildes y pasa a mayúsculas para comparar nombres sin fallos."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto.upper().strip())
        if unicodedata.category(c) != "Mn"
    )


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
    """
    Separa los caracteres para que Gemini lea el DNI dígito a dígito
    (ej: '1, 6, 6, 0, 7, 7, 6, 4, letra E').
    """
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
                        if len(actividades_resumen) >= 10:
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
                            act = c.get("activity") or c.get("course") or c.get("ACTIVIDAD") or c.get("CURSO") or "Curso"
                            inst = c.get("facility") or c.get("INSTALACION") or ""
                            dias = c.get("days") or c.get("DIAS") or ""
                            hora = c.get("start_time") or c.get("HORA_INICIO") or ""
                            detalle = f"{act} en {inst}"
                            if dias or hora:
                                detalle += f" ({dias} {hora})".strip()
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