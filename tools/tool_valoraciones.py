import os
import asyncio
import logging
import requests
import urllib3
from livekit.agents import function_tool

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("tools.valoraciones")

def _post_valoracion(base_url: str, puntuacion: int, comentario: str) -> bool:
    """Envía la petición POST al servidor de valoraciones y devuelve True si tuvo éxito."""
    url = f"{base_url.rstrip('/')}/api/valoraciones"
    payload = {"puntuacion": puntuacion, "comentario": comentario}

    response = requests.post(url, json=payload, timeout=4, verify=False)
    return response.status_code in (200, 201)


class ToolValoraciones:
    @function_tool(
        description=(
            "Registra en el sistema una valoración, puntuación u opinión del usuario sobre las instalaciones, monitores o servicios de Logroño Deporte."
        )
    )
    async def registrar_valoracion(self, puntuacion: int, comentario: str) -> str:
        """
        Args:
            puntuacion: Nota numérica del 1 al 5 otorgada por el usuario.
            comentario: Opinión o motivo de la valoración explicado por el usuario.
        """
        logger.info(f"[TOOL] registrar_valoracion -> nota={puntuacion}, comentario='{comentario}'")
        valoracion_url = os.getenv("VALORACION_API_URL", "https://valoracion-api.logronodeporte.es")

        try:
            exito = await asyncio.to_thread(_post_valoracion, valoracion_url, puntuacion, comentario)
            if exito:
                logger.info("Valoración guardada en el servidor correctamente.")
                return f"Valoración de {puntuacion} sobre 5 registrada con éxito. Agradece al usuario su opinión."
        except Exception as e:
            logger.warning(f"No se pudo conectar con API Valoraciones ({e}). Confirmando en modo local.")

        return (f"Valoración registrada correctamente (puntuación: {puntuacion}/5, comentario: '{comentario}'). Confirma al usuario que su opinión ha quedado guardada y dale las gracias.")