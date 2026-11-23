import asyncio
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

import tools.tool_instalaciones as mod_inst
import tools.tool_abonados_dni as mod_dni
import tools as mod_tools_init
import panel_administracion.app as panel_app
from tools import LogronoDeporteTools

client = TestClient(panel_app.app)


def test_obtener_info_instalacion_gateway_y_no_encontrada(monkeypatch):
    instalaciones_mock = [
        {"codigo": 10, "nombre": "C.D.M. Lobete"},
        {"codigo": 20, "nombre": "C.D.M. La Ribera"},
    ]
    cursillos_mock = [
        {
            "descripcion_actividad": "Pilates",
            "descripcion_instalacion": "C.D.M. Lobete",
            "martes": True,
            "jueves": True,
            "hora_inicio": "09:15",
            "hora_fin": "10:15",
        }
    ]

    def fake_get(url, params=None, **kwargs):
        if url.endswith("/instalacion/search"):
            return MagicMock(status_code=200, text="ok", json=lambda: instalaciones_mock)
        return MagicMock(status_code=200, text="ok", json=lambda: cursillos_mock)

    monkeypatch.setattr(mod_inst.requests, "get", fake_get)
    herramientas = LogronoDeporteTools()

    res_ok = asyncio.run(herramientas.obtener_info_instalacion("Lobete"))
    assert "C.D.M. Lobete" in res_ok
    assert "Pilates" in res_ok
    assert "Martes, Jueves" in res_ok

    res_no = asyncio.run(herramientas.obtener_info_instalacion("Estadio Inventado"))
    assert "No se encontró ninguna instalación" in res_no


def test_buscar_actividad_deportiva_por_centros(monkeypatch):
    cursos = [
        {
            "descripcion_actividad": "Zumba Fitness",
            "descripcion_instalacion": "C.D.M. La Ribera",
            "lunes": True,
            "hora_inicio": "18:00",
            "hora_fin": "19:00",
        },
        {
            "descripcion_actividad": "Natación Adultos",
            "descripcion_instalacion": "C.D.M. Lobete",
            "martes": True,
            "hora_inicio": "10:00",
            "hora_fin": "11:00",
        },
    ]

    def fake_get(url, params=None, **kwargs):
        if url.endswith("/instalacion/search"):
            return MagicMock(status_code=200, text="ok", json=lambda: [])
        return MagicMock(status_code=200, text="ok", json=lambda: cursos)

    monkeypatch.setattr(mod_inst.requests, "get", fake_get)
    herramientas = LogronoDeporteTools()

    res = asyncio.run(herramientas.buscar_actividad_deportiva("Zumba"))
    assert "Zumba Fitness en C.D.M. La Ribera" in res
    assert "Natación Adultos" not in res


def test_dni_via_gateway_y_via_valoracion_api(monkeypatch):
    def fake_get_gw(url, params=None, **kwargs):
        if "find_by_dni" in url:
            return MagicMock(status_code=200, text="ok", json=lambda: [{"codigo_abonado": 999}])
        if "search_cursillo" in url:
            return MagicMock(
                status_code=200,
                text="ok",
                json=lambda: [{"descripcion_cursillo": "Natación", "descripcion_instalacion": "C.D.M. Las Gaunas"}],
            )
        return MagicMock(status_code=404, text="")

    monkeypatch.setattr(mod_dni.requests, "get", fake_get_gw)
    cursos_gw = mod_dni._buscar_cursos_gateway("https://gw.test", "16607764Q")
    assert "Natación en C.D.M. Las Gaunas" in cursos_gw

    def fake_get_val(url, **kwargs):
        return MagicMock(
            status_code=200,
            text="ok",
            json=lambda: {
                "data": [
                    {
                        "nombre_curso": "Yoga",
                        "instalacion": "C.D.M. Lobete",
                        "dias": "Lunes y Miércoles",
                        "horario": "19:00",
                        "teacher_name": "Laura",
                    }
                ]
            },
        )

    monkeypatch.setattr(mod_dni.requests, "get", fake_get_val)
    cursos_val = mod_dni._buscar_cursos_valoracion_api("https://val.test", "16607764Q")
    assert "Yoga en C.D.M. Lobete" in cursos_val
    assert "con Laura" in cursos_val


def test_finalizar_llamada_cierra_sesion(monkeypatch):
    herramientas = LogronoDeporteTools()
    fake_session = MagicMock()
    herramientas.session = fake_session

    async def fake_sleep(_):
        return None

    monkeypatch.setattr(mod_tools_init.asyncio, "sleep", fake_sleep)

    async def _ejecutar():
        msg = await herramientas.finalizar_llamada()
        await asyncio.sleep(0)
        return msg

    respuesta = asyncio.run(_ejecutar())
    assert "Llamada programada para finalizar" in respuesta
    fake_session.shutdown.assert_called_once_with(drain=True)


def test_panel_api_valoraciones_batch_sync_y_edicion_md(monkeypatch, tmp_path):
    monkeypatch.setattr(
        panel_app,
        "obtener_valoraciones_guardadas",
        lambda: [
            {"valoracion_id": "v1", "fecha": "2026-11-01T10:00:00", "puntuacion": 4},
            {"valoracion_id": "v2", "fecha": "2026-11-23T10:00:00", "puntuacion": 5},
        ],
    )
    r_val = client.get("/api/valoraciones")
    assert r_val.status_code == 200
    assert r_val.json()[0]["valoracion_id"] == "v2"

    monkeypatch.setattr(panel_app, "ejecutar_batch_nocturno", lambda forzar: 4)
    r_batch = client.post("/api/analitica/ejecutar?forzar=true")
    assert r_batch.status_code == 200
    assert r_batch.json()["procesadas"] == 4

    archivo_tmp = tmp_path / "01_prueba.md"
    archivo_tmp.write_text("# Título inicial", encoding="utf-8")
    monkeypatch.setattr(panel_app, "RUTA_CONOCIMIENTO", tmp_path)
    monkeypatch.setattr(panel_app, "sincronizar_conocimiento", lambda: None)

    r_get = client.get("/api/conocimiento/01_prueba.md")
    assert r_get.status_code == 200
    assert r_get.json()["contenido"] == "# Título inicial"

    r_put = client.put("/api/conocimiento/01_prueba.md", json={"contenido": "# Actualizado"})
    assert r_put.status_code == 200
    assert archivo_tmp.read_text(encoding="utf-8") == "# Actualizado"

    r_sync = client.post("/api/conocimiento/sincronizar")
    assert r_sync.status_code == 200
    assert r_sync.json()["archivos_generados"] == 1