import asyncio
from unittest.mock import MagicMock

import tools.tool_instalaciones as mod_inst
import tools.tool_valoraciones as mod_val
from tools import LogronoDeporteTools
from prompts import obtener_instrucciones_con_fecha, GREETING_MESSAGE


def test_ocupacion_gimnasios_parseo_en_vivo(monkeypatch):
    html_simulado = """
    <html><body>
      <p>Sala de musculación - Lobete</p>
      <p>Lunes 23</p>
      <p>11:30 18 plazas ocupadas de 50 totales</p>
      <p>Sala de musculación - La Ribera</p>
      <p>Lunes 23</p>
      <p>11:30 25 plazas ocupadas de 65 totales</p>
    </body></html>
    """
    resp_fake = MagicMock(status_code=200, text=html_simulado)
    monkeypatch.setattr(mod_inst.requests, "get", lambda *a, **kw: resp_fake)

    texto_lobete = mod_inst._obtener_ocupacion_gimnasios_vivo("Lobete")
    assert "Lobete" in texto_lobete
    assert "18 plazas ocupadas de 50" in texto_lobete
    assert "32 plazas libres" in texto_lobete
    assert "La Ribera" not in texto_lobete


def test_ocupacion_gimnasios_fallback_sin_conexion(monkeypatch):
    def _error_red(*args, **kwargs):
        raise ConnectionError("Sin red")

    monkeypatch.setattr(mod_inst.requests, "get", _error_red)
    texto = mod_inst._obtener_ocupacion_gimnasios_vivo("")

    assert "La Ribera 65 plazas" in texto
    assert "Lobete 50 plazas" in texto
    assert "Las Gaunas 40 plazas" in texto


def test_registrar_valoracion_usa_sesion_y_mock_bd(monkeypatch):
    capturado = {}

    def fake_post(*args, **kwargs):
        return False

    async def fake_guardar_db(**kwargs):
        capturado.update(kwargs)
        return {"valoracion_id": "val_test"}

    monkeypatch.setattr(mod_val, "_post_valoracion", fake_post)
    monkeypatch.setattr(mod_val, "guardar_valoracion_db", fake_guardar_db)

    herramientas = LogronoDeporteTools()
    herramientas.sesion_abonado = {
        "verificado": True,
        "dni": "16607764Q",
        "dni_voz": "1, 6, 6, 0, 7, 7, 6, 4, letra Q",
        "cursos": "Pilates",
    }

    respuesta = asyncio.run(
        herramientas.registrar_valoracion(
            puntuacion=5,
            comentario="Muy buenas instalaciones",
            instalacion="C.D.M. La Ribera",
            actividad="Ciclo Indoor",
        )
    )

    assert "5" in respuesta
    assert capturado["dni"] == "16607764Q"
    assert capturado["instalacion"] == "C.D.M. La Ribera"
    assert capturado["puntuacion"] == 5


def test_prompt_incluye_contexto_temporal_y_menu():
    instrucciones = obtener_instrucciones_con_fecha()
    assert "CONTEXTO TEMPORAL ACTUAL DE LA LLAMADA:" in instrucciones
    assert "CERO ALUCINACIONES" in instrucciones
    assert "pulse o diga 1" in GREETING_MESSAGE
    assert "pulse o diga 6" in GREETING_MESSAGE