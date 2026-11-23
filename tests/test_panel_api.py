from fastapi.testclient import TestClient
import panel_administracion.app as panel_app

client = TestClient(panel_app.app)

_SESIONES_MOCK = [
    {
        "session_id": "ses_01",
        "fecha_inicio": "2026-11-20T10:00:00",
        "duracion_seg": 40.0,
        "herramientas_usadas": ["consultar_web_logrono_deporte"],
        "analitica_ia": {
            "procesado": True,
            "categoria_principal": "Tarifas y Abonos",
            "intencion": "Consulta de cuota familiar",
            "resuelta": True,
            "friccion_detectada": False,
        },
    },
    {
        "session_id": "ses_02",
        "fecha_inicio": "2026-11-20T11:00:00",
        "duracion_seg": 60.0,
        "herramientas_usadas": ["consultar_cursos_abonado"],
        "analitica_ia": {
            "procesado": True,
            "categoria_principal": "Cursos por DNI y Valoraciones",
            "intencion": "Consulta de cursos con error al dictar DNI",
            "resuelta": False,
            "friccion_detectada": True,
        },
    },
    {
        "session_id": "ses_03",
        "fecha_inicio": "2026-11-20T12:00:00",
        "duracion_seg": 5.0,
        "herramientas_usadas": [],
        "analitica_ia": {
            "procesado": True,
            "categoria_principal": "Llamada sin consulta",
            "intencion": "Abandono en saludo",
            "resuelta": False,
            "friccion_detectada": False,
        },
    },
]

_VALORACIONES_MOCK = [
    {
        "valoracion_id": "val_01",
        "fecha": "2026-11-20T10:05:00",
        "puntuacion": 5,
        "instalacion": "C.D.M. La Ribera",
        "actividad": "Ciclo Indoor",
        "comentario": "Excelente",
        "abonado_hash": "abo_1234567890",
        "enviada_api_oficial": True,
    },
    {
        "valoracion_id": "val_02",
        "fecha": "2026-11-20T11:05:00",
        "puntuacion": 3,
        "instalacion": "C.D.M. La Ribera",
        "actividad": "General",
        "comentario": "Vestuario mejorable",
        "abonado_hash": "anonimo",
        "enviada_api_oficial": False,
    },
]


def test_dashboard_html_carga():
    r = client.get("/")
    assert r.status_code == 200
    assert "Logroño Deporte" in r.text


def test_api_resumen_calculo_kpis(monkeypatch):
    monkeypatch.setattr(panel_app, "obtener_sesiones_guardadas", lambda: list(_SESIONES_MOCK))
    monkeypatch.setattr(panel_app, "obtener_valoraciones_guardadas", lambda: list(_VALORACIONES_MOCK))

    r = client.get("/api/resumen")
    assert r.status_code == 200
    kpis = r.json()["kpis"]

    assert kpis["total_llamadas"] == 3
    assert kpis["llamadas_con_consulta"] == 2
    assert kpis["abandonos_iniciales"] == 1
    assert kpis["tasa_resolucion"] == 50.0 
    assert kpis["duracion_media_seg"] == 35.0
    assert kpis["llamadas_con_friccion"] == 1
    assert kpis["nota_media"] == 4.0
    assert kpis["total_valoraciones"] == 2


def test_api_sesiones_filtros(monkeypatch):
    monkeypatch.setattr(panel_app, "obtener_sesiones_guardadas", lambda: list(_SESIONES_MOCK))

    r_fric = client.get("/api/sesiones?solo_friccion=true")
    assert r_fric.status_code == 200
    datos = r_fric.json()
    assert len(datos) == 1
    assert datos[0]["session_id"] == "ses_02"

    r_cat = client.get("/api/sesiones?categoria=Tarifas+y+Abonos")
    assert len(r_cat.json()) == 1
    assert r_cat.json()[0]["session_id"] == "ses_01"


def test_api_conocimiento_lista_archivos():
    r = client.get("/api/conocimiento")
    assert r.status_code == 200
    nombres = [a["nombre"] for a in r.json()]
    assert "01_tarifas_y_abonos.md" in nombres
    assert "05_tramites_oficinas_y_faqs.md" in nombres


def test_api_conocimiento_bloquea_path_traversal():
    for ataque in ("..%5C..%5C.env", "..%2F.env", "prompts.py", "inexistente.md"):
        r = client.get(f"/api/conocimiento/{ataque}")
        assert r.status_code in (400, 404)