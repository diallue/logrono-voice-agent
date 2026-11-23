import asyncio
import pytest

from tools.utils import (
    normalizar_texto,
    limpiar_dni,
    es_dni_valido,
    formatear_dni_voz,
    obtener_raiz,
)
from tools import LogronoDeporteTools
import tools.tool_abonados_dni as mod_dni


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("  Natación Lobete  ", "NATACION LOBETE"),
        ("Pingüino y árboles", "PINGUINO Y ARBOLES"),
        ("", ""),
    ],
)
def test_normalizar_texto(entrada, esperado):
    assert normalizar_texto(entrada) == esperado


@pytest.mark.parametrize(
    "dictado_voz, esperado",
    [
        ("16607764Q", "16607764Q"),
        ("mi dni es 16 60 77 64 Q de queso", "16607764Q"),
        ("16523736 con F de Francia", "16523736F"),
        ("mi nie es X 9719674 letra N de Navarra", "X9719674N"),
        ("12345678-A", "12345678A"),
    ],
)
def test_limpiar_dni_fonetico(dictado_voz, esperado):
    assert limpiar_dni(dictado_voz) == esperado


@pytest.mark.parametrize(
    "dni, valido",
    [
        ("16607764Q", True),
        ("X9719674N", True),
        ("Y1234567Z", True),
        ("1660776Q", False),     
        ("16607764", False),    
        ("A1234567B", False),
    ],
)
def test_es_dni_valido(dni, valido):
    assert es_dni_valido(dni) is valido


def test_formatear_dni_voz():
    assert formatear_dni_voz("16607764Q") == "1, 6, 6, 0, 7, 7, 6, 4, letra Q"
    assert formatear_dni_voz("") == "ningún carácter válido"


def test_obtener_raiz():
    assert obtener_raiz("inscribirme") == "inscri".upper()
    assert obtener_raiz("anulaciones") == "anul".upper()
    assert obtener_raiz("pista") == "pista".upper()


def test_consultar_cursos_abonado_valido_y_memoria(monkeypatch):
    monkeypatch.setattr(mod_dni, "_buscar_cursos_gateway", lambda *_: None)
    monkeypatch.setattr(mod_dni, "_buscar_cursos_valoracion_api", lambda *_: None)

    herramientas = LogronoDeporteTools()
    resp = asyncio.run(herramientas.consultar_cursos_abonado("16607764 Q de queso"))

    assert "DNI verificado" in resp
    assert "Ciclo Indoor" in resp
    assert herramientas.sesion_abonado["verificado"] is True
    assert herramientas.sesion_abonado["dni"] == "16607764Q"


def test_consultar_cursos_abonado_incompleto():
    herramientas = LogronoDeporteTools()
    resp = asyncio.run(herramientas.consultar_cursos_abonado("1660776Q"))

    assert "FORMATO DE DNI INCOMPLETO O INCORRECTO" in resp
    assert herramientas.sesion_abonado["verificado"] is False