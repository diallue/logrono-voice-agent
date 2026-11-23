import asyncio
import json
from types import SimpleNamespace
import pytest

import analitica_y_datos.database as db
import analitica_y_datos.batch_analitico as batch


class _FakeAsyncCollection:
    def __init__(self, fallar: bool = False):
        self.docs = []
        self.fallar = fallar

    async def insert_one(self, doc: dict):
        if self.fallar:
            raise ConnectionError("MongoDB async caído")
        self.docs.append(doc)


class _FakeSyncCollection:
    def __init__(self, docs_iniciales=None, fallar: bool = False):
        self.docs = list(docs_iniciales or [])
        self.fallar = fallar

    def find(self, filtro, proyeccion):
        if self.fallar:
            raise ConnectionError("MongoDB sync caído")
        return list(self.docs)

    def update_one(self, filtro, update, upsert=False):
        if self.fallar:
            raise ConnectionError("MongoDB update caído")
        clave, valor = next(iter(filtro.items()))
        for doc in self.docs:
            if doc.get(clave) == valor:
                if "$set" in update:
                    doc.update(update["$set"])
                return SimpleNamespace(upserted_id=None)
        if upsert and "$setOnInsert" in update:
            self.docs.append(dict(update["$setOnInsert"]))
            return SimpleNamespace(upserted_id=valor)
        return SimpleNamespace(upserted_id=None)


def _aislar_rutas_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "RUTA_DATOS_LOCALES", tmp_path)
    monkeypatch.setattr(db, "ARCHIVO_SESIONES", tmp_path / "sesiones.json")
    monkeypatch.setattr(db, "ARCHIVO_VALORACIONES", tmp_path / "valoraciones.json")


def test_guardar_y_leer_sesion_con_anonimizacion_y_mongo(monkeypatch, tmp_path):
    _aislar_rutas_db(monkeypatch, tmp_path)
    col_async = _FakeAsyncCollection()
    col_sync = _FakeSyncCollection()

    monkeypatch.setattr(db, "_obtener_coleccion_mongo_async", lambda _: col_async)
    monkeypatch.setattr(db, "_obtener_coleccion_mongo_sync", lambda _: col_sync)

    doc = asyncio.run(
        db.guardar_sesion_llamada_db(
            sala="RM_test_01",
            inicio_iso="2026-11-23T10:00:00",
            duracion_seg=42.34,
            turnos_dialogo=[
                {"rol": "usuario", "texto": "Mi DNI es 16607764Q y mi móvil 611223344"},
                {"rol": "agente", "texto": "Perfecto, te ayudo."},
                {"rol": "usuario", "texto": "   "},
            ],
            herramientas_usadas=["consultar_cursos_abonado"],
            dni_verificado="16607764Q",
        )
    )

    assert doc["num_turnos"] == 2
    assert "[DNI_PROTEGIDO]" in doc["dialogo"][0]["texto"]
    assert "[TELEFONO_PROTEGIDO]" in doc["dialogo"][0]["texto"]
    assert doc["abonado_hash"].startswith("abo_")
    assert len(col_async.docs) == 1
    assert (tmp_path / "sesiones.json").exists()

    col_sync.docs.append(dict(doc))
    nueva_analitica = {
        "procesado": True,
        "categoria_principal": "Cursos por DNI y Valoraciones",
        "intencion": "Consultar cursos personales",
        "resuelta": True,
        "friccion_detectada": False,
        "tags": ["dni", "cursos"],
    }
    db.actualizar_analitica_sesion_db(doc["session_id"], nueva_analitica)

    sesiones_mongo = db.obtener_sesiones_guardadas()
    assert sesiones_mongo[0]["analitica_ia"]["procesado"] is True

    sesiones_disco = json.loads((tmp_path / "sesiones.json").read_text(encoding="utf-8"))
    assert sesiones_disco[0]["analitica_ia"]["categoria_principal"] == "Cursos por DNI y Valoraciones"


def test_guardar_valoracion_y_fallback_local_si_mongo_falla(monkeypatch, tmp_path):
    _aislar_rutas_db(monkeypatch, tmp_path)
    monkeypatch.setattr(db, "_obtener_coleccion_mongo_async", lambda _: _FakeAsyncCollection(fallar=True))
    monkeypatch.setattr(db, "_obtener_coleccion_mongo_sync", lambda _: _FakeSyncCollection(fallar=True))

    val = asyncio.run(
        db.guardar_valoracion_db(
            puntuacion=5,
            comentario="Genial, mi correo es privado@gmail.com",
            instalacion="C.D.M. Lobete",
            actividad="Pilates",
            dni="16607764Q",
            enviada_api_oficial=False,
        )
    )

    assert "[EMAIL_PROTEGIDO]" in val["comentario"]
    recuperadas = db.obtener_valoraciones_guardadas()
    assert len(recuperadas) == 1
    assert recuperadas[0]["instalacion"] == "C.D.M. Lobete"


def test_migrar_json_local_a_mongo_sin_duplicados(monkeypatch, tmp_path):
    _aislar_rutas_db(monkeypatch, tmp_path)
    (tmp_path / "sesiones.json").write_text(
        json.dumps([{"session_id": "ses_1", "sala": "console"}]), encoding="utf-8"
    )
    (tmp_path / "valoraciones.json").write_text(
        json.dumps([{"valoracion_id": "val_1", "puntuacion": 5}]), encoding="utf-8"
    )

    cols = {"sessions": _FakeSyncCollection(), "valoraciones": _FakeSyncCollection()}
    monkeypatch.setattr(db, "_obtener_coleccion_mongo_sync", lambda nombre: cols[nombre])

    r1 = db.migrar_json_local_a_mongo()
    r2 = db.migrar_json_local_a_mongo()

    assert r1 == {"sesiones_migradas": 1, "valoraciones_migradas": 1}
    assert r2 == {"sesiones_migradas": 0, "valoraciones_migradas": 0}


def test_batch_nocturno_con_gemini_y_reintento_503(monkeypatch):
    sesiones = [
        {
            "session_id": "ses_pendiente",
            "dialogo": [
                {"rol": "usuario", "texto": "¿Cuánto cuesta el abono familiar?"},
                {"rol": "agente", "texto": "El abono familiar cuesta 241,00 euros."},
            ],
            "herramientas_usadas": ["consultar_web_logrono_deporte"],
            "analitica_ia": {"procesado": False},
        },
        {
            "session_id": "ses_ya_procesada",
            "dialogo": [{"rol": "usuario", "texto": "Hola"}],
            "herramientas_usadas": [],
            "analitica_ia": {"procesado": True},
        },
    ]
    actualizaciones = {}

    class _FakeModels:
        def __init__(self):
            self.intentos = 0

        def generate_content(self, **kwargs):
            self.intentos += 1
            if self.intentos == 1:
                raise RuntimeError("503 Service Unavailable")
            return SimpleNamespace(
                text=json.dumps({
                    "categoria_principal": "Tarifas y Abonos",
                    "intencion": "Consultar precio del abono familiar",
                    "resuelta": True,
                    "friccion_detectada": False,
                    "tags": ["abono", "familiar"],
                })
            )

    fake_client = SimpleNamespace(models=_FakeModels())
    monkeypatch.setattr(batch, "obtener_sesiones_guardadas", lambda: sesiones)
    monkeypatch.setattr(
        batch,
        "actualizar_analitica_sesion_db",
        lambda sid, res: actualizaciones.__setitem__(sid, res),
    )
    monkeypatch.setattr(batch.time, "sleep", lambda _: None)
    monkeypatch.setattr(batch.genai, "Client", lambda api_key: fake_client)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")

    total = batch.ejecutar_batch_nocturno(forzar_reprocesado=False)

    assert total == 1
    assert "ses_pendiente" in actualizaciones
    assert "ses_ya_procesada" not in actualizaciones
    assert actualizaciones["ses_pendiente"]["categoria_principal"] == "Tarifas y Abonos"
    assert fake_client.models.intentos == 2