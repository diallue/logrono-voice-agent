import io
import asyncio
from unittest.mock import MagicMock
from docx import Document
from openpyxl import Workbook

import datos_web.procesador_archivos as proc
import datos_web.buscador_web as bweb
import tools.tool_conocimiento_web as mod_web
from tools import LogronoDeporteTools


def test_procesador_docx_real():
    doc = Document()
    doc.add_paragraph("Normativa oficial de piscinas municipales.")
    tabla = doc.add_table(rows=2, cols=2)
    tabla.rows[0].cells[0].text = "Servicio"
    tabla.rows[0].cells[1].text = "Tarifa"
    tabla.rows[1].cells[0].text = "Entrada"
    tabla.rows[1].cells[1].text = "5,00 €"

    buf = io.BytesIO()
    doc.save(buf)

    md = proc.procesar_archivo_binario(buf.getvalue(), "https://ejemplo.es/normas.docx")
    assert "Normativa oficial de piscinas municipales." in md
    assert "| Servicio | Tarifa |" in md
    assert "| Entrada | 5,00 € |" in md


def test_procesador_excel_real():
    wb = Workbook()
    ws = wb.active
    ws.title = "Tarifas2026"
    ws.append(["Modalidad", "Abonado", "Usuario"])
    ws.append(["Bono 10", "38 €", "76 €"])

    buf = io.BytesIO()
    wb.save(buf)

    md = proc.procesar_archivo_binario(buf.getvalue(), "https://ejemplo.es/tarifas.xlsx")
    assert "### Hoja: Tarifas2026" in md
    assert "| Modalidad | Abonado | Usuario |" in md
    assert "| Bono 10 | 38 € | 76 € |" in md


def test_procesador_csv_y_limites_seguridad():
    csv_bytes = "Centro,Aforo\nLobete,50\nLa Ribera,65\n".encode("utf-8")
    md = proc.procesar_archivo_binario(csv_bytes, "https://ejemplo.es/aforos.csv")
    assert "| Centro | Aforo |" in md
    assert "| Lobete | 50 |" in md

    assert proc.procesar_archivo_binario(b"x" * 8_000_001, "https://ejemplo.es/enorme.pdf") == ""
    assert proc.extraer_markdown_de_pdf(b"%PDF-1.4", "https://ejemplo.es/logo_ayuntamiento.pdf") == ""
    assert proc.procesar_archivo_binario(b"datos", "https://ejemplo.es/imagen.jpg", "image/jpeg") == ""


def test_procesador_pdf_con_mock(monkeypatch):
    pagina_fake = MagicMock()
    pagina_fake.extract_text.return_value = (
        "Tarifas oficiales 2026 de Logroño Deporte: Abono Adulto empadronado 120,60 euros anuales."
    )
    lector_fake = MagicMock(pages=[pagina_fake])
    monkeypatch.setattr(proc, "PdfReader", lambda _: lector_fake)

    md = proc.procesar_archivo_binario(b"%PDF-fake", "https://logronodeporte.es/tarifas-2026.pdf")
    assert "### Página 1" in md
    assert "120,60 euros" in md


def test_buscador_web_en_vivo_joomla_y_catalogo(monkeypatch):
    html_buscador = """
    <html><body>
      <a href="/component/search/ignorar">Ignorar</a>
      <a href="/transparencia-prueba">Transparencia</a>
    </body></html>
    """
    html_destino = (
        "<html><body><h2>Transparencia</h2>"
        "<p>Información pública corporativa y presupuestos anuales de Logroño Deporte S.A.</p>"
        "</body></html>"
    )

    def fake_get(url, **kwargs):
        if "/component/search/" in url:
            return MagicMock(status_code=200, text=html_buscador, headers={"Content-Type": "text/html"})
        return MagicMock(status_code=200, text=html_destino, headers={"Content-Type": "text/html"})

    monkeypatch.setattr(bweb.requests, "get", fake_get)
    bloques = bweb.buscar_en_web_en_vivo("presupuestos anuales", ["PRESUPUESTOS"])

    assert len(bloques) == 1
    assert "Fuente Web en Vivo" in bloques[0]
    assert "presupuestos anuales" in bloques[0]


def test_tool_conocimiento_web_niveles_y_sin_resultados(monkeypatch):
    herramientas = LogronoDeporteTools()

    monkeypatch.setattr(mod_web, "buscar_en_md_locales", lambda *_: (20, ["# Tarifas\nAbono 120,60 €"]))
    monkeypatch.setattr(mod_web, "cargar_catalogo_urls", lambda: {})
    res_local = asyncio.run(herramientas.consultar_web_logrono_deporte("cuanto cuesta el abono"))
    assert "120,60 €" in res_local

    monkeypatch.setattr(mod_web, "buscar_en_md_locales", lambda *_: (0, []))
    monkeypatch.setattr(mod_web, "buscar_en_web_en_vivo", lambda *_: ["## Fuente Web en Vivo\nEstatutos"])
    res_vivo = asyncio.run(herramientas.consultar_web_logrono_deporte("estatutos sociedad"))
    assert "Estatutos" in res_vivo

    monkeypatch.setattr(mod_web, "buscar_en_web_en_vivo", lambda *_: [])
    res_vacio = asyncio.run(herramientas.consultar_web_logrono_deporte("dato inexistente xyz"))
    assert "AVISO OFICIAL" in res_vacio
    assert "941 27 70 55" in res_vacio