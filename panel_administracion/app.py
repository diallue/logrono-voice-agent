import sys
import asyncio
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

RUTA_RAIZ = Path(__file__).resolve().parent.parent
if str(RUTA_RAIZ) not in sys.path:
    sys.path.insert(0, str(RUTA_RAIZ))

from analitica_y_datos.database import (
    obtener_sesiones_guardadas,
    obtener_valoraciones_guardadas,
)
from analitica_y_datos.batch_analitico import ejecutar_batch_nocturno
from datos_web.sincronizar_web import RUTA_CONOCIMIENTO, sincronizar_conocimiento

RUTA_TEMPLATES = Path(__file__).resolve().parent / "templates"

app = FastAPI(
    title="Panel de Administración — Agente de Voz Logroño Deporte",
    version="1.0.0",
)


class ContenidoMarkdown(BaseModel):
    contenido: str


def _resolver_archivo_md(nombre_archivo: str) -> Path:
    """Valida que el archivo sea un .md dentro de datos_web/conocimiento/ (evita path traversal)."""
    if "/" in nombre_archivo or "\\" in nombre_archivo or not nombre_archivo.endswith(".md"):
        raise HTTPException(status_code=400, detail="Nombre de archivo Markdown no válido.")

    ruta = (RUTA_CONOCIMIENTO / nombre_archivo).resolve()
    if ruta.parent != RUTA_CONOCIMIENTO.resolve() or not ruta.exists():
        raise HTTPException(status_code=404, detail=f"Archivo '{nombre_archivo}' no encontrado.")
    return ruta


@app.get("/", response_class=HTMLResponse)
async def servir_dashboard():
    index_html = RUTA_TEMPLATES / "index.html"
    if index_html.exists():
        return FileResponse(index_html)
    return HTMLResponse(
        "<h2>Backend del Panel de Administración activo</h2>"
        "<p>La vista <code>templates/index.html</code> aún no está creada. "
        "Puedes probar toda la API desde <a href='/docs'>/docs</a>.</p>"
    )


@app.get("/api/resumen")
async def obtener_resumen():
    sesiones = obtener_sesiones_guardadas()
    valoraciones = obtener_valoraciones_guardadas()

    total_llamadas = len(sesiones)
    duraciones = [float(s.get("duracion_seg", 0)) for s in sesiones]
    duracion_media = round(sum(duraciones) / total_llamadas, 1) if total_llamadas else 0.0

    pendientes = 0
    con_friccion = 0
    abandonos_iniciales = 0
    analizadas_con_consulta = 0
    resueltas_con_consulta = 0

    contador_categorias: Counter = Counter()
    contador_herramientas: Counter = Counter()

    for s in sesiones:
        analitica = s.get("analitica_ia", {})
        categoria = analitica.get("categoria_principal", "Pendiente de análisis nocturno")
        procesado = bool(analitica.get("procesado", False))

        contador_categorias[categoria] += 1

        if not procesado:
            pendientes += 1
        elif categoria == "Llamada sin consulta":
            abandonos_iniciales += 1
        else:
            analizadas_con_consulta += 1
            if analitica.get("resuelta", False):
                resueltas_con_consulta += 1

        if analitica.get("friccion_detectada", False):
            con_friccion += 1

        for herramienta in s.get("herramientas_usadas", []):
            contador_herramientas[herramienta] += 1

    tasa_resolucion = (
        round((resueltas_con_consulta / analizadas_con_consulta) * 100, 1)
        if analizadas_con_consulta
        else 0.0
    )

    total_valoraciones = len(valoraciones)
    notas = [int(v.get("puntuacion", 0)) for v in valoraciones if v.get("puntuacion")]
    nota_media = round(sum(notas) / len(notas), 2) if notas else 0.0

    notas_por_instalacion: dict[str, list[int]] = defaultdict(list)
    for v in valoraciones:
        inst = v.get("instalacion") or "General"
        if v.get("puntuacion"):
            notas_por_instalacion[inst].append(int(v["puntuacion"]))

    satisfaccion_instalaciones = sorted(
        [
            {
                "instalacion": inst,
                "media": round(sum(lista) / len(lista), 2),
                "total": len(lista),
            }
            for inst, lista in notas_por_instalacion.items()
        ],
        key=lambda x: x["total"],
        reverse=True,
    )

    return {
        "kpis": {
            "total_llamadas": total_llamadas,
            "llamadas_con_consulta": analizadas_con_consulta,
            "abandonos_iniciales": abandonos_iniciales,
            "tasa_resolucion": tasa_resolucion,
            "duracion_media_seg": duracion_media,
            "llamadas_con_friccion": con_friccion,
            "pendientes_analisis": pendientes,
            "nota_media": nota_media,
            "total_valoraciones": total_valoraciones,
        },
        "por_categoria": [
            {"categoria": cat, "total": cnt}
            for cat, cnt in contador_categorias.most_common()
        ],
        "herramientas_mas_usadas": [
            {"herramienta": h, "usos": cnt}
            for h, cnt in contador_herramientas.most_common()
        ],
        "satisfaccion_instalaciones": satisfaccion_instalaciones,
    }


@app.get("/api/sesiones")
async def listar_sesiones(
    categoria: str | None = Query(default=None),
    solo_friccion: bool = Query(default=False),
    solo_no_resueltas: bool = Query(default=False),
):
    sesiones = obtener_sesiones_guardadas()
    resultado = []

    for s in sesiones:
        analitica = s.get("analitica_ia", {})
        if categoria and analitica.get("categoria_principal") != categoria:
            continue
        if solo_friccion and not analitica.get("friccion_detectada", False):
            continue
        if solo_no_resueltas and analitica.get("resuelta", True):
            continue
        resultado.append(s)

    resultado.sort(key=lambda x: x.get("fecha_inicio", ""), reverse=True)
    return resultado


@app.get("/api/valoraciones")
async def listar_valoraciones():
    valoraciones = obtener_valoraciones_guardadas()
    valoraciones.sort(key=lambda x: x.get("fecha", ""), reverse=True)
    return valoraciones


@app.post("/api/analitica/ejecutar")
async def lanzar_batch_analitico(forzar: bool = Query(default=False)):
    procesadas = await asyncio.to_thread(ejecutar_batch_nocturno, forzar)
    return {
        "ok": True,
        "procesadas": procesadas,
        "mensaje": f"Análisis completado: {procesadas} sesiones procesadas.",
    }


@app.get("/api/conocimiento")
async def listar_archivos_conocimiento():
    if not RUTA_CONOCIMIENTO.exists():
        return []

    archivos = []
    for ruta in sorted(RUTA_CONOCIMIENTO.glob("*.md")):
        stat = ruta.stat()
        archivos.append({
            "nombre": ruta.name,
            "tamano_kb": round(stat.st_size / 1024, 1),
            "ultima_modificacion": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    return archivos


@app.get("/api/conocimiento/{nombre_archivo}")
async def leer_archivo_conocimiento(nombre_archivo: str):
    ruta = _resolver_archivo_md(nombre_archivo)
    return {
        "nombre": ruta.name,
        "contenido": ruta.read_text(encoding="utf-8"),
    }


@app.put("/api/conocimiento/{nombre_archivo}")
async def guardar_archivo_conocimiento(nombre_archivo: str, body: ContenidoMarkdown):
    ruta = _resolver_archivo_md(nombre_archivo)
    await asyncio.to_thread(ruta.write_text, body.contenido, "utf-8")
    return {
        "ok": True,
        "nombre": ruta.name,
        "tamano_kb": round(ruta.stat().st_size / 1024, 1),
        "mensaje": f"Archivo '{ruta.name}' guardado correctamente.",
    }


@app.post("/api/conocimiento/sincronizar")
async def lanzar_sincronizacion_web():
    await asyncio.to_thread(sincronizar_conocimiento)
    total_md = len(list(RUTA_CONOCIMIENTO.glob("*.md")))
    return {
        "ok": True,
        "archivos_generados": total_md,
        "mensaje": f"Sincronización completada ({total_md} archivos Markdown actualizados).",
    }