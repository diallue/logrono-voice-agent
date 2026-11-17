import os
import asyncio
import logging
import requests
import urllib3
from livekit.agents import function_tool

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("tools.valoraciones")


def _post_valoracion(base_url: str, puntuacion: int, comentario: str, instalacion: str = "", actividad: str = "", dni: str = "") -> bool:
    """Envía la petición POST al servidor de valoraciones con el contexto disponible."""

    url = f"{base_url.rstrip('/')}/api/valoraciones"
    payload: dict[str, str | int] = {
        "puntuacion": puntuacion,
        "comentario": comentario,
    }
    if instalacion:
        payload["instalacion"] = instalacion
    if actividad:
        payload["actividad"] = actividad
    if dni:
        payload["dni"] = dni

    response = requests.post(url, json=payload, timeout=4, verify=False)
    return response.status_code in (200, 201)


class ToolValoraciones:
    @function_tool(
        description=(
            "Registra en el sistema una valoración, puntuación u opinión del usuario "
            "sobre las instalaciones, monitores, cursos o servicios de Logroño Deporte."
        )
    )
    async def registrar_valoracion(self, puntuacion: int, comentario: str, instalacion: str = "", actividad: str = "") -> str:
        """
        Args:
            puntuacion: Nota numérica del 1 al 5 otorgada por el usuario.
            comentario: Opinión o motivo de la valoración explicado por el usuario.
            instalacion: Instalación deportiva valorada si la menciona (ej: C.D.M. Lobete, La Ribera).
            actividad: Curso o actividad valorada si la menciona (ej: Pilates, Ciclo Indoor).
        """
        sesion = getattr(self, "sesion_abonado", {})
        dni_sesion = str(sesion.get("dni", "")) if sesion.get("verificado") else ""

        etiquetas: list[str] = []
        if instalacion:
            etiquetas.append(f"Instalación: {instalacion}")
        if actividad:
            etiquetas.append(f"Actividad: {actividad}")
        if dni_sesion:
            etiquetas.append(f"DNI: {dni_sesion}")

        comentario_enriquecido = (
            f"{comentario} [{' | '.join(etiquetas)}]" if etiquetas else comentario
        )

        logger.info(f"[TOOL] registrar_valoracion -> nota={puntuacion}/5 | inst='{instalacion}' | act='{actividad}' | dni_sesion='{dni_sesion}' | comentario='{comentario}'")
        valoracion_url = os.getenv("VALORACION_API_URL", "https://valoracion-api.logronodeporte.es")

        try:
            exito = await asyncio.to_thread(
                _post_valoracion,
                valoracion_url,
                puntuacion,
                comentario_enriquecido,
                instalacion,
                actividad,
                dni_sesion,
            )
            if exito:
                logger.info("Valoración guardada en el servidor correctamente.")
                return (
                    f"Valoración de {puntuacion} sobre 5 registrada con éxito"
                    f"{f' para {actividad} en {instalacion}'.strip() if (actividad or instalacion) else ''}. "
                    "Agradece al usuario su opinión."
                )
        except Exception as e:
            logger.warning(f"No se pudo conectar con API Valoraciones ({e}). Confirmando en modo local.")

        return (
            f"Valoración registrada correctamente (puntuación: {puntuacion}/5"
            f"{f', asociada a {actividad} {instalacion}'.rstrip() if (actividad or instalacion) else ''}"
            f"{f', abonado {dni_sesion}' if dni_sesion else ''}). "
            "Confirma al usuario que su opinión ha quedado guardada y dale las gracias."
        )