import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

RUTA_UBICACIONES = Path(__file__).resolve().parent / "ubicaciones_instalaciones.json"

_PALABRAS_RUIDO = {"CDM", "PM", "POLIDEPORTIVO", "MUNICIPAL", "MUNICIPALES", "CENTRO", "DEPORTIVO", "COMPLEJO", "INSTALACION", "INSTALACIONES", "PISCINA", "PISCINAS", "DE", "DEL", "LA", "LAS", "EL", "LOS", "EN",}


def _normalizar(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", (texto or "").upper().strip())
        if unicodedata.category(c) != "Mn"
    )


@lru_cache(maxsize=1)
def cargar_ubicaciones() -> list[dict]:
    if not RUTA_UBICACIONES.exists():
        return []
    datos = json.loads(RUTA_UBICACIONES.read_text(encoding="utf-8"))
    return datos.get("instalaciones", [])


def limpiar_cache_ubicaciones() -> None:
    cargar_ubicaciones.cache_clear()


def buscar_ubicacion(consulta: str = "", codigo_gateway: int | None = None) -> dict | None:
    """Busca una instalación por código de Gateway o por coincidencia priorizando precisión."""
    catalogo = cargar_ubicaciones()
    if codigo_gateway is not None:
        for item in catalogo:
            if item.get("codigo_gateway") == codigo_gateway:
                return item

    busqueda = _normalizar(consulta)
    if not busqueda:
        return None

    for item in catalogo:
        candidatos = [_normalizar(item.get("nombre", ""))] + [_normalizar(a) for a in item.get("alias", [])]
        if any(busqueda == c for c in candidatos if c):
            return item

    tokens = [t for t in re.findall(r"[A-Z0-9]+", busqueda) if len(t) > 2 and t not in _PALABRAS_RUIDO]
    mejor_item = None
    mejor_pts = 0

    for item in catalogo:
        candidatos = [_normalizar(item.get("nombre", ""))] + [_normalizar(a) for a in item.get("alias", [])]
        texto_item = " ".join(candidatos)
        pts = 0

        if tokens:
            coincidencias = sum(1 for t in tokens if t in texto_item)
            pts += coincidencias * 10
            if coincidencias == len(tokens):
                pts += 15

        for c in candidatos:
            if c and (busqueda in c or c in busqueda):
                pts += min(len(c), len(busqueda))
                break

        if pts > mejor_pts:
            mejor_pts = pts
            mejor_item = item

    return mejor_item if mejor_pts >= 10 else None


def formatear_ubicacion_voz(item: dict) -> str:
    """Devuelve un resumen natural orientado a voz con dirección, referencias, paradas y minutos a pie."""
    partes = [f"{item['nombre']} está en {item['direccion']}."]

    if item.get("referencia"):
        partes.append(f"Como referencia, se encuentra {item['referencia']}.")

    paradas = item.get("paradas_bus") or []
    if paradas:
        descripciones = []
        for p in paradas:
            nombre_parada = (p.get("parada") or "").strip()
            lineas = [str(l).strip() for l in p.get("lineas", []) if str(l).strip()]
            minutos = p.get("minutos_pie")
            indicacion = (p.get("indicacion_pie") or "").strip()

            tramo = ""
            if nombre_parada and lineas:
                tramo = f"parada {nombre_parada} ({', '.join(lineas)})"
            elif nombre_parada:
                tramo = f"parada {nombre_parada}"
            elif lineas:
                tramo = ", ".join(lineas)

            if tramo:
                if isinstance(minutos, int) and minutos >= 0:
                    tramo += ", a 1 minuto andando" if minutos <= 1 else f", a unos {minutos} minutos andando"
                if indicacion:
                    tramo += f" ({indicacion})"
                descripciones.append(tramo)

        if descripciones:
            partes.append(f"En autobús urbano, te dejan cerca: {'; '.join(descripciones)}.")

    if item.get("telefono"):
        partes.append(f"Teléfono del centro: {item['telefono']}.")

    return " ".join(partes)