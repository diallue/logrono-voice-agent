import os
import json
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

RUTA_RAIZ = Path(__file__).resolve().parent.parent
if str(RUTA_RAIZ) not in sys.path:
    sys.path.insert(0, str(RUTA_RAIZ))

from analitica_y_datos.database import ARCHIVO_SESIONES, _leer_json_local

load_dotenv(RUTA_RAIZ / ".env", override=True)
logger = logging.getLogger("analitica_nocturna")


class ResultadoAnaliticaIA(BaseModel):
    categoria_principal: str = Field(
        description=(
            "Una de estas 6 categorías exactas: 'Tarifas y Abonos', 'Reservas y Localizador', "
            "'Actividades e Inscripciones', 'Instalaciones y Aforos', 'Trámites y Oficinas', "
            "'Cursos por DNI y Valoraciones'."
        )
    )
    intencion: str = Field(
        description="Resumen en una frase breve de qué quería consultar el usuario."
    )
    resuelta: bool = Field(
        description="True si el agente respondió con el dato concreto; False si dijo que no disponía del dato o remitió al teléfono."
    )
    friccion_detectada: bool = Field(
        description="True si hubo errores de transcripción por voz, negaciones ('no, no') o fallos al dictar el DNI."
    )
    tags: list[str] = Field(
        description="Entre 1 y 4 palabras clave en minúsculas sobre los temas tratados."
    )


def _analizar_por_reglas_locales(sesion: dict) -> dict:
    texto_completo = " ".join(t.get("texto", "").lower() for t in sesion.get("dialogo", []))
    texto_usuario = " ".join(
        t.get("texto", "").lower() for t in sesion.get("dialogo", []) if t.get("rol") == "usuario"
    )
    herramientas = sesion.get("herramientas_usadas", [])

    if "consultar_cursos_abonado" in herramientas or "registrar_valoracion" in herramientas or "dni" in texto_completo:
        categoria = "Cursos por DNI y Valoraciones"
    elif "consultar_ocupacion_gimnasios" in herramientas or "obtener_info_instalacion" in herramientas or any(
        p in texto_usuario for p in ("lobete", "ribera", "gaunas", "norias", "gimnasio", "aforo", "hielo", "hidrotermal")
    ):
        categoria = "Instalaciones y Aforos"
    elif "buscar_actividad_deportiva" in herramientas or any(
        p in texto_usuario for p in ("pilates", "zumba", "natacion", "carta", "inscri")
    ):
        categoria = "Actividades e Inscripciones"
    elif any(p in texto_usuario for p in ("localizador", "reserva", "anular", "cancelar")):
        categoria = "Reservas y Localizador"
    elif any(p in texto_usuario for p in ("oficina", "chiribitas", "cuenta", "banco", "sepa", "tramite")):
        categoria = "Trámites y Oficinas"
    else:
        categoria = "Tarifas y Abonos"

    resuelta = not any(
        frase in texto_completo
        for frase in ("no dispongo", "no se ha encontrado", "problema técnico")
    )
    friccion = any(
        frase in texto_completo
        for frase in ("no, no", "fallo", "incompleto", "no me aparecen cursos")
    )

    return {
        "procesado": True,
        "categoria_principal": categoria,
        "intencion": f"Consulta telefónica sobre {categoria.lower()}",
        "resuelta": resuelta,
        "friccion_detectada": friccion,
        "tags": [categoria.split()[0].lower()],
    }


def _analizar_con_gemini(sesion: dict) -> dict:
    turnos = sesion.get("dialogo", [])
    if len(turnos) <= 1:
        return {
            "procesado": True,
            "categoria_principal": "Llamada sin consulta",
            "intencion": "El usuario colgó durante el saludo inicial.",
            "resuelta": False,
            "friccion_detectada": False,
            "tags": ["abandono_inicial"],
        }

    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        return _analizar_por_reglas_locales(sesion)

    transcripcion = "\n".join(f"{t.get('rol', '').upper()}: {t.get('texto', '')}" for t in turnos)
    prompt = (
        "Analiza la siguiente transcripción anonimizada de una llamada a Logroño Deporte.\n"
        f"Herramientas invocadas: {sesion.get('herramientas_usadas', [])}\n\n"
        f"TRANSCRIPCIÓN:\n{transcripcion}"
    )

    try:
        cliente = genai.Client(api_key=api_key)
        respuesta = cliente.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ResultadoAnaliticaIA,
                temperature=0.0,
            ),
        )
        datos = json.loads(respuesta.text or "{}")
        datos["procesado"] = True
        return datos
    except Exception as e:
        logger.warning(f"Usando análisis por reglas locales para {sesion.get('session_id')} ({e})")
        return _analizar_por_reglas_locales(sesion)


def ejecutar_batch_nocturno(forzar_reprocesado: bool = False) -> int:
    sesiones = _leer_json_local(ARCHIVO_SESIONES)
    if not sesiones:
        logger.info("No hay sesiones registradas todavía en sesiones.json.")
        return 0

    procesadas_ahora = 0
    for sesion in sesiones:
        ya_procesada = sesion.get("analitica_ia", {}).get("procesado", False)
        if ya_procesada and not forzar_reprocesado:
            continue

        resultado = _analizar_con_gemini(sesion)
        sesion["analitica_ia"] = resultado
        procesadas_ahora += 1
        logger.info(
            f"[BATCH OK] {sesion.get('session_id')} -> Categoría: '{resultado['categoria_principal']}' | "
            f"Intención: '{resultado['intencion']}' | Resuelta: {resultado['resuelta']} | "
            f"Fricción: {resultado['friccion_detectada']}"
        )

    if procesadas_ahora > 0:
        ARCHIVO_SESIONES.write_text(
            json.dumps(sesiones, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return procesadas_ahora


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    total = ejecutar_batch_nocturno()
    print(f"\nProceso analítico nocturno completado: {total} sesiones analizadas.")