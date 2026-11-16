import re
from pathlib import Path
from tools.utils import normalizar_texto
from datos_web.sincronizar_web import RUTA_CONOCIMIENTO, sincronizar_conocimiento


def _dividir_en_fragmentos(contenido_md: str) -> list[str]:
    """Divide cada archivo .md por fuentes ('---') y, si es un PDF largo, por '### Página '."""
    fragmentos: list[str] = []
    for fuente in contenido_md.split("\n---\n"):
        fuente = fuente.strip()
        if len(fuente) <= 30 or (fuente.startswith("# ") and "\n" not in fuente):
            continue

        if "### Página " in fuente and len(fuente) > 2500:
            partes = fuente.split("### Página ")
            cabecera = partes[0].strip()
            for pag in partes[1:]:
                fragmentos.append(f"{cabecera}\n### Página {pag.strip()}")
        else:
            fragmentos.append(fuente)
    return fragmentos


def buscar_en_md_locales(palabras: list[str], raices: list[str]) -> tuple[int, list[str]]:
    """
    Lee los 5 archivos .md de datos_web/conocimiento/, puntúa sus bloques
    y devuelve (puntuación_máxima, lista_de_mejores_fragmentos).
    """
    archivos_md = sorted(RUTA_CONOCIMIENTO.glob("*.md"))
    if not archivos_md:
        sincronizar_conocimiento()
        archivos_md = sorted(RUTA_CONOCIMIENTO.glob("*.md"))

    bloques_puntuados: list[tuple[int, str]] = []

    for ruta in archivos_md:
        contenido = ruta.read_text(encoding="utf-8").strip()
        if not contenido:
            continue

        for frag in _dividir_en_fragmentos(contenido):
            lineas = frag.splitlines()
            encabezado_norm = normalizar_texto(" ".join(lineas[:2])) if lineas else ""
            cuerpo_norm = normalizar_texto(frag)

            puntos = 4 if "RESUMEN OFICIAL VERIFICADO" in encabezado_norm else 0

            for p in palabras:
                if p in encabezado_norm:
                    puntos += 10
                if p in cuerpo_norm:
                    puntos += 5

            for r in raices:
                if r in encabezado_norm:
                    puntos += 5
                elif r in cuerpo_norm:
                    puntos += 2

            if puntos >= 6:
                bloques_puntuados.append((puntos, frag[:3500]))

    bloques_puntuados.sort(key=lambda x: x[0], reverse=True)
    if not bloques_puntuados:
        return 0, []

    max_pts = bloques_puntuados[0][0]
    mejores = [texto for _, texto in bloques_puntuados[:3]]
    return max_pts, mejores