import asyncio
import logging
from livekit.agents import function_tool

from tools.tool_instalaciones import ToolInstalaciones
from tools.tool_abonados_dni import ToolAbonadosDNI
from tools.tool_valoraciones import ToolValoraciones
from tools.tool_conocimiento_web import ToolConocimientoWeb

logger = logging.getLogger("tools.sesion")


async def _cerrar_tras_despedida(agente: object) -> None:
    """Espera a que el asistente termine de pronunciar la despedida y cierra la sesión de voz."""
    await asyncio.sleep(4.5)
    sesion = getattr(agente, "session", None)
    if sesion is not None:
        try:
            logger.info("[SESION] Cerrando sesión de voz tras la despedida del usuario.")
            await sesion.aclose()
        except Exception as e:
            logger.debug(f"Aviso al cerrar sesión: {e}")


class LogronoDeporteTools(
    ToolInstalaciones,
    ToolAbonadosDNI,
    ToolValoraciones,
    ToolConocimientoWeb,
):
    """Agrupa las herramientas modulares y mantiene la memoria del abonado durante la llamada."""

    def __init__(self) -> None:
        self.sesion_abonado: dict[str, str | bool] = {"verificado": False, "dni": "", "dni_voz": "", "cursos": "", }

    @function_tool(
        description=(
            "Finaliza y cuelga la llamada telefónica de forma limpia. "
            "Úsala ÚNICAMENTE cuando el usuario se despida claramente (ej: 'adiós', 'hasta luego', "
            "'nada más, muchas gracias por todo') indicando que ya ha terminado todas sus consultas."
        )
    )
    async def finalizar_llamada(self) -> str:
        """Cierra la sesión de voz tras permitir que el agente pronuncie la despedida final."""
        logger.info("[TOOL] finalizar_llamada -> Solicitud de fin de llamada recibida.")
        if getattr(self, "session", None) is not None:
            asyncio.create_task(_cerrar_tras_despedida(self))
        return ("Llamada programada para finalizar. Despídete ahora del usuario con una sola frase breve, amable y enérgica en nombre de Logroño Deporte.")


__all__ = ["LogronoDeporteTools"]