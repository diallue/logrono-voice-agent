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
except ImportError:
    AsyncIOMotorClient = None

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

logger = logging.getLogger("analitica_y_datos.database")

RUTA_DATOS_LOCALES = Path(__file__).resolve().parent / "data"
ARCHIVO_SESIONES = RUTA_DATOS_LOCALES / "sesiones.json"
ARCHIVO_VALORACIONES = RUTA_DATOS_LOCALES / "valoraciones.json"

_CLIENTE_MONGO = None

def _leer_json_local(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    try:
        texto = ruta.read_text(encoding="utf-8")
        return json.loads(texto)
    except Exception as e:
        logger.error(f"Error al leer el archivo JSON {ruta}: {e}")
        return []

def _guardar_en_json_local(ruta: Path, documento: dict) -> None:
    RUTA_DATOS_LOCALES.mkdir(parents=True, exist_ok=True)

    registros = _leer_json_local(ruta)

    doc_copia = {clave: valor for clave, valor in documento.items() if clave != "_id"}

    registros.append(doc_copia)
    texto_json = json.dumps(registros, ensure_ascii=False, indent=2)
    ruta.write_text(texto_json, encoding="utf-8")

def _obtener_coleccion_mongo(nombre_coleccion: str):
    global _CLIENTE_MONGO

    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri or " .xxxxx. "in uri or AsyncIOMotorClient is None:
        logger.warning("No se ha configurado una URI válida de MongoDB. Se usarán archivos JSON locales.")
        return None

    try:
        if _CLIENTE_MONGO is None:
            _CLIENTE_MONGO = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=2500)

        return _CLIENTE_MONGO["logrono_deporte_db"][nombre_coleccion]
    except Exception as e:
        logger.error(f"Error al conectar con MongoDB: {e}")
        return None

async def guardar_valoracion_db(puntuacion: int, comentario: str, instalacion: str = "", actividad: str = "", dni: str = "", enviada_api_oficial: bool = False,) -> dict:
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

    col = _obtener_coleccion_mongo("valoraciones")
    if col is not None:
        try:
            await col.insert_one(dict(documento))
        except Exception as e:
            logger.debug(f"Aviso MongoDB en valoración: {e}")

    return documento

async def guardar_sesion_llamada_db(sala: str, inicio_iso: str, duracion_seg: float, turnos_dialogo: list[dict], herramientas_usadas: list[str], dni_verificado: str = "",) -> dict:
    """
    Anonimiza todos los mensajes de la llamada y guarda la sesión en MongoDB y en local.
    """
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

    col = _obtener_coleccion_mongo("sessions")
    if col is not None:
        try:
            await col.insert_one(dict(documento))
            logger.info(f"[DB] Sesión {documento['session_id']} guardada en MongoDB.")
        except Exception as e:
            logger.debug(f"Aviso MongoDB en sesión: {e}")

    logger.info(
        f"[DB] Sesión guardada ({documento['session_id']}) -> {documento['num_turnos']} turnos, "
        f"{documento['duracion_seg']}s, herramientas={documento['herramientas_usadas']}."
    )
    return documento


def obtener_sesiones_guardadas() -> list[dict]:
    """Devuelve todas las sesiones almacenadas para el proceso nocturno y el panel web."""
    return _leer_json_local(ARCHIVO_SESIONES)


def obtener_valoraciones_guardadas() -> list[dict]:
    """Devuelve todas las valoraciones almacenadas para el panel web."""
    return _leer_json_local(ARCHIVO_VALORACIONES)