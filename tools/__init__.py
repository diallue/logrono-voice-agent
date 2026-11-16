from tools.tool_instalaciones import ToolInstalaciones
from tools.tool_abonados_dni import ToolAbonadosDNI
from tools.tool_valoraciones import ToolValoraciones
from tools.tool_conocimiento_web import ToolConocimientoWeb


class LogronoDeporteTools(
    ToolInstalaciones,
    ToolAbonadosDNI,
    ToolValoraciones,
    ToolConocimientoWeb,
):
    """Agrupa las 4 herramientas modulares del agente de voz de Logroño Deporte."""
    pass


__all__ = ["LogronoDeporteTools"]