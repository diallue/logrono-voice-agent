import os
import json
import uuid
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from analitica_y_datos.anonimizador_rgpd import anonimizar_texto, generar_hash_abonado

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo import MongoClient
except ImportError:
    AsyncIOMotorClient = None
    MongoClient = None

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

logger = logging.getLogger("analitica_y_datos.database")

RUTA_DATOS_LOCALES = Path(__file__).resolve().parent / "data"
ARCHIVO_SESIONES = RUTA_DATOS_LOCALES / "sesiones.json"
ARCHIVO_VALORACIONES = RUTA_DATOS_LOCALES / "valoraciones.json"

NOMBRE_BD = "logrono_deporte"

_CLIENTE_MONGO_ASYNC = None
_CLIENTE_MONGO_SYNC = None


def _obtener_uri_mongo() -> str | None:
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri or ".xxxxx." in uri:
        return None
    return uri


def _leer_json_local(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Error al leer el archivo JSON {ruta}: {e}")
        return []


def _guardar_en_json_local(ruta: Path, documento: dict) -> None:
    RUTA_DATOS_LOCALES.mkdir(parents=True, exist_ok=True)
    registros = _leer_json_local(ruta)
    doc_copia = {k: v for k, v in documento.items() if k != "_id"}
    registros.append(doc_copia)
    ruta.write_text(json.dumps(registros, ensure_ascii=False, indent=2), encoding="utf-8")


def _obtener_coleccion_mongo_async(nombre_coleccion: str):
    global _CLIENTE_MONGO_ASYNC
    uri = _obtener_uri_mongo()
    if not uri or AsyncIOMotorClient is None:
        return None
    try:
        if _CLIENTE_MONGO_ASYNC is None:
            _CLIENTE_MONGO_ASYNC = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=2500)
        return _CLIENTE_MONGO_ASYNC[NOMBRE_BD][nombre_coleccion]
    except Exception as e:
        logger.error(f"Error al inicializar cliente MongoDB async: {e}")
        return None


def _obtener_coleccion_mongo_sync(nombre_coleccion: str):
    global _CLIENTE_MONGO_SYNC
    uri = _obtener_uri_mongo()
    if not uri or MongoClient is None:
        return None
    try:
        if _CLIENTE_MONGO_SYNC is None:
            _CLIENTE_MONGO_SYNC = MongoClient(uri, serverSelectionTimeoutMS=2500)
        return _CLIENTE_MONGO_SYNC[NOMBRE_BD][nombre_coleccion]
    except Exception as e:
        logger.error(f"Error al inicializar cliente MongoDB sync: {e}")
        return None


async def guardar_valoracion_db(
    puntuacion: int,
    comentario: str,
    instalacion: str = "",
    actividad: str = "",
    dni: str = "",
    enviada_api_oficial: bool = False,
) -> dict:
    documento = {
        "valoracion_id": f"val_{uuid.uuid4().hex[:8]}",
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "puntuacion": int(puntuacion),
        "comentario": anonimizar_texto(comentario),
        "instalacion": instalacion.strip() or "General",
        "actividad": actividad.strip() or "General",
        "abonado_hash": generar_hash_abonado(dni),
        "enviada_api_oficial": enviada_api_oficial,
    }

    await asyncio.to_thread(_guardar_en_json_local, ARCHIVO_VALORACIONES, documento)

    col = _obtener_coleccion_mongo_sync("valoraciones")
    if col is not None:
        try:
            await asyncio.to_thread(col.insert_one, dict(documento))
            logger.info(f"[DB] Valoración {documento['valoracion_id']} guardada en MongoDB Atlas.")
        except Exception as e:
            logger.warning(f"Aviso MongoDB en valoración (respaldo local guardado): {e}")

    return documento


async def guardar_sesion_llamada_db(
    sala: str,
    inicio_iso: str,
    duracion_seg: float,
    turnos_dialogo: list[dict],
    herramientas_usadas: list[str],
    dni_verificado: str = "",
) -> dict:
    """Anonimiza todos los mensajes de la llamada y guarda la sesión en MongoDB Atlas y local."""
    dialogo_anonimizado = [
        {
            "rol": t.get("rol", "usuario"),
            "texto": anonimizar_texto(str(t.get("texto", ""))),
            "hora": t.get("hora", datetime.now().strftime("%H:%M:%S")),
        }
        for t in turnos_dialogo
        if str(t.get("texto", "")).strip()
    ]

    documento = {
        "session_id": f"ses_{uuid.uuid4().hex[:10]}",
        "sala": sala,
        "fecha_inicio": inicio_iso,
        "fecha_fin": datetime.now().isoformat(timespec="seconds"),
        "duracion_seg": round(duracion_seg, 1),
        "abonado_hash": generar_hash_abonado(dni_verificado),
        "herramientas_usadas": list(herramientas_usadas),
        "num_turnos": len(dialogo_anonimizado),
        "dialogo": dialogo_anonimizado,
        "analitica_ia": {
            "procesado": False,
            "categoria_principal": "Pendiente de análisis nocturno",
            "intencion": "",
            "resuelta": True,
            "friccion_detectada": False,
            "tags": [],
        },
    }

    await asyncio.to_thread(_guardar_en_json_local, ARCHIVO_SESIONES, documento)

    col = _obtener_coleccion_mongo_sync("sessions")
    if col is not None:
        try:
            await asyncio.to_thread(col.insert_one, dict(documento))
            logger.info(f"[DB] Sesión {documento['session_id']} guardada en MongoDB Atlas.")
        except Exception as e:
            logger.warning(f"Aviso MongoDB en sesión (respaldo local guardado): {e}")

    logger.info(
        f"[DB] Sesión guardada ({documento['session_id']}) -> {documento['num_turnos']} turnos, "
        f"{documento['duracion_seg']}s, herramientas={documento['herramientas_usadas']}."
    )
    return documento


def obtener_sesiones_guardadas() -> list[dict]:
    """Lee las sesiones desde MongoDB Atlas; si no está disponible, usa el JSON local."""
    col = _obtener_coleccion_mongo_sync("sessions")
    if col is not None:
        try:
            return list(col.find({}, {"_id": 0}))
        except Exception as e:
            logger.warning(f"No se pudo leer 'sessions' de MongoDB ({e}). Usando respaldo local.")
    return _leer_json_local(ARCHIVO_SESIONES)


def obtener_valoraciones_guardadas() -> list[dict]:
    """Lee las valoraciones desde MongoDB Atlas; si no está disponible, usa el JSON local."""
    col = _obtener_coleccion_mongo_sync("valoraciones")
    if col is not None:
        try:
            return list(col.find({}, {"_id": 0}))
        except Exception as e:
            logger.warning(f"No se pudo leer 'valoraciones' de MongoDB ({e}). Usando respaldo local.")
    return _leer_json_local(ARCHIVO_VALORACIONES)


def actualizar_analitica_sesion_db(session_id: str, analitica_ia: dict) -> None:
    """Actualiza el bloque analitica_ia de una sesión en MongoDB Atlas y en el respaldo local."""
    col = _obtener_coleccion_mongo_sync("sessions")
    if col is not None:
        try:
            col.update_one(
                {"session_id": session_id},
                {"$set": {"analitica_ia": analitica_ia}},
            )
        except Exception as e:
            logger.warning(f"Error actualizando analítica en MongoDB para {session_id}: {e}")

    sesiones_locales = _leer_json_local(ARCHIVO_SESIONES)
    modificado = False
    for s in sesiones_locales:
        if s.get("session_id") == session_id:
            s["analitica_ia"] = analitica_ia
            modificado = True
            break
    if modificado:
        ARCHIVO_SESIONES.write_text(
            json.dumps(sesiones_locales, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def migrar_json_local_a_mongo() -> dict:
    """Sube los registros existentes en data/*.json a MongoDB Atlas sin duplicar documentos."""
    col_ses = _obtener_coleccion_mongo_sync("sessions")
    col_val = _obtener_coleccion_mongo_sync("valoraciones")
    if col_ses is None or col_val is None:
        raise RuntimeError("No hay una MONGODB_URI válida configurada en .env.")

    ses_insertadas = 0
    for doc in _leer_json_local(ARCHIVO_SESIONES):
        doc_limpio = {k: v for k, v in doc.items() if k != "_id"}
        res = col_ses.update_one(
            {"session_id": doc_limpio["session_id"]},
            {"$setOnInsert": doc_limpio},
            upsert=True,
        )
        if res.upserted_id is not None:
            ses_insertadas += 1

    val_insertadas = 0
    for doc in _leer_json_local(ARCHIVO_VALORACIONES):
        doc_limpio = {k: v for k, v in doc.items() if k != "_id"}
        res = col_val.update_one(
            {"valoracion_id": doc_limpio["valoracion_id"]},
            {"$setOnInsert": doc_limpio},
            upsert=True,
        )
        if res.upserted_id is not None:
            val_insertadas += 1

    return {"sesiones_migradas": ses_insertadas, "valoraciones_migradas": val_insertadas}