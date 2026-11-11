import os
import requests
from livekit.agents import llm
import logging
from livekit.agents import function_tool

logger = logging.getLogger("api_tools")

class LogronoDeporteAPI:
    def __init__(self):
        super().__init__()
        self.gateway_url = os.getenv("LDP_GATEWAY_URL")
        self.valoracion_url = os.getenv("VALORACION_API_URL")

    @function_tool(description="Obtiene información general o de instalaciones de Logroño Deporte")
    async def obtener_info_instalacion(self, nombre_instalacion: str):
        try:
            response = requests.get(f"{self.gateway_url}/api/instalaciones", params={"nombre": nombre_instalacion})
            if response.status_code == 200:
                return f"Datos de la instalación: {response.json()}"
            return "No pude encontrar información sobre esa instalación en este momento."
        except Exception as e:
            logger.error(f"Error consultando gateway: {e}")
            return "Hubo un error de conexión con el sistema central."

    @function_tool(description="Registra una valoración del usuario sobre el servicio")
    async def registrar_valoracion(self, puntuacion: int, comentario: str):
        try:
            payload = {"puntuacion": puntuacion, "comentario": comentario}
            response = requests.post(f"{self.valoracion_url}/api/valoraciones", json=payload)
            if response.status_code in [200, 201]:
                return "Valoración registrada con éxito. Agradece al usuario."
            return "No se pudo registrar la valoración."
        except Exception as e:
            logger.error(f"Error registrando valoración: {e}")
            return "Hubo un problema al guardar la valoración."