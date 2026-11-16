import io
import os
import csv
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from dotenv import load_dotenv
from pypdf import PdfReader
from docx import Document
from openpyxl import load_workbook
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
logger = logging.getLogger("procesador_archivos")

# Silenciamos los warnings internos de pypdf sobre fuentes CFF o punteros antiguos
logging.getLogger("pypdf").setLevel(logging.ERROR)

EXTENSIONES_DOCUMENTOS = (".pdf", ".docx", ".xlsx", ".csv")
EXTENSIONES_IMAGENES = (".jpg", ".jpeg", ".png", ".webp")

# Ponlo en True solo si deseas usar Gemini 2.5 Flash para hacer OCR de imágenes/PDFs escaneados
USAR_OCR_GEMINI = False

_PALABRAS_ARCHIVO_DESCARTABLE = (
    "logo", "icon", "banner", "boton", "button", "flecha", "arrow",
    "cabecera", "header", "footer", "fondo", "background", "avatar",
    "redes", "plano_logrono", "mapa_instalaciones"
)


def _transcribir_con_gemini(contenido_bytes: bytes, mime_type: str, origen: str) -> str:
    """Extrae texto y tablas con Gemini Flash si USAR_OCR_GEMINI está activado."""
    if not USAR_OCR_GEMINI:
        return ""

    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        return ""

    prompt = (
        "Analiza este archivo oficial de Logroño Deporte. "
        "Si es una imagen decorativa o un mapa sin tablas de datos, responde solo DECORATIVA. "
        "Si contiene precios, tarifas, horarios, normas, calendario o requisitos, "
        "transcribe todos sus datos exactamente en formato Markdown (.md)."
    )

    try:
        cliente = genai.Client(api_key=api_key)
        respuesta = cliente.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=contenido_bytes, mime_type=mime_type),
                prompt,
            ],
            config=types.GenerateContentConfig(temperature=0.0),
        )
        texto = (respuesta.text or "").strip()
        return "" if texto.upper() == "DECORATIVA" or len(texto) < 30 else texto
    except Exception as e:
        logger.warning(f"Aviso OCR en {origen}: {e}")
        return ""


def _leer_paginas_pdf(contenido_bytes: bytes) -> str:
    """Función interna que extrae el texto de hasta las primeras 25 páginas de un PDF."""
    lector = PdfReader(io.BytesIO(contenido_bytes))
    paginas_texto: list[str] = []

    for num_pag, pagina in enumerate(lector.pages[:25], start=1):
        texto_pag = (pagina.extract_text() or "").strip()
        if texto_pag:
            paginas_texto.append(f"### Página {num_pag}\n{texto_pag}")

    return "\n\n".join(paginas_texto).strip()


def extraer_markdown_de_pdf(contenido_bytes: bytes, url: str) -> str:
    """Extrae el texto de un PDF con un límite de seguridad de 6 segundos para evitar bloqueos."""
    nombre_archivo = url.split("/")[-1].lower()
    if any(p in nombre_archivo for p in _PALABRAS_ARCHIVO_DESCARTABLE):
        return ""

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            futuro = executor.submit(_leer_paginas_pdf, contenido_bytes)
            texto_completo = futuro.result(timeout=6.0)

        if len(texto_completo) >= 60:
            return texto_completo

        return _transcribir_con_gemini(contenido_bytes, "application/pdf", url)
    except FuturesTimeoutError:
        logger.warning(f"PDF omitido por exceso de tiempo de lectura (>6s): {url}")
        return ""
    except Exception as e:
        logger.warning(f"No se pudo leer el PDF {url}: {e}")
        return ""


def extraer_markdown_de_docx(contenido_bytes: bytes, url: str) -> str:
    """Extrae párrafos y tablas de un documento Word (.docx) a formato Markdown."""
    try:
        doc = Document(io.BytesIO(contenido_bytes))
        partes: list[str] = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

        for tabla in doc.tables:
            for fila in tabla.rows:
                celdas = [c.text.strip().replace("\n", " ") or "-" for c in fila.cells]
                if any(c != "-" for c in celdas):
                    partes.append("| " + " | ".join(celdas) + " |")

        return "\n".join(partes).strip()
    except Exception as e:
        logger.warning(f"Error procesando Word {url}: {e}")
        return ""


def extraer_markdown_de_excel(contenido_bytes: bytes, url: str) -> str:
    """Convierte todas las hojas y tablas de un archivo Excel (.xlsx) a tablas Markdown."""
    try:
        wb = load_workbook(io.BytesIO(contenido_bytes), data_only=True)
        partes: list[str] = []

        for nombre_hoja in wb.sheetnames:
            hoja = wb[nombre_hoja]
            filas_md: list[str] = []
            for fila in hoja.iter_rows(values_only=True):
                valores = [str(celda).strip() if celda is not None else "-" for celda in fila]
                if any(v not in ("-", "") for v in valores):
                    filas_md.append("| " + " | ".join(valores) + " |")

            if filas_md:
                partes.append(f"### Hoja: {nombre_hoja}\n" + "\n".join(filas_md))

        return "\n\n".join(partes).strip()
    except Exception as e:
        logger.warning(f"Error procesando Excel {url}: {e}")
        return ""


def extraer_markdown_de_csv(contenido_bytes: bytes, url: str) -> str:
    """Convierte un archivo CSV en una tabla Markdown."""
    try:
        texto = contenido_bytes.decode("utf-8", errors="replace")
        lector = csv.reader(io.StringIO(texto))
        filas = [
            "| " + " | ".join(celda.strip() or "-" for celda in fila) + " |"
            for fila in lector
            if any(celda.strip() for celda in fila)
        ]
        return "\n".join(filas)
    except Exception as e:
        logger.warning(f"Error procesando CSV {url}: {e}")
        return ""


def extraer_markdown_de_imagen(contenido_bytes: bytes, url: str, content_type: str) -> str:
    """Procesa carteles informativos si USAR_OCR_GEMINI está habilitado."""
    if not USAR_OCR_GEMINI or len(contenido_bytes) < 45_000:
        return ""

    nombre_archivo = url.split("/")[-1].lower()
    if any(palabra in nombre_archivo for palabra in _PALABRAS_ARCHIVO_DESCARTABLE):
        return ""

    mime = content_type if "image/" in content_type else "image/jpeg"
    return _transcribir_con_gemini(contenido_bytes, mime, url)


def procesar_archivo_binario(contenido_bytes: bytes, url: str, content_type: str = "") -> str:
    """Enrutador principal: recibe un archivo descargado y devuelve su contenido en Markdown."""
    if not contenido_bytes or len(contenido_bytes) > 8_000_000:
        return ""

    u_low = url.lower()
    ct_low = content_type.lower()

    if u_low.endswith(".pdf") or "application/pdf" in ct_low:
        return extraer_markdown_de_pdf(contenido_bytes, url)
    if u_low.endswith(".docx") or "wordprocessingml" in ct_low:
        return extraer_markdown_de_docx(contenido_bytes, url)
    if u_low.endswith(".xlsx") or "spreadsheetml" in ct_low:
        return extraer_markdown_de_excel(contenido_bytes, url)
    if u_low.endswith(".csv") or "text/csv" in ct_low:
        return extraer_markdown_de_csv(contenido_bytes, url)
    if u_low.endswith(EXTENSIONES_IMAGENES) or "image/" in ct_low:
        return extraer_markdown_de_imagen(contenido_bytes, url, ct_low)

    return ""