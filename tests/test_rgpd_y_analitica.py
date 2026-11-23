from analitica_y_datos.anonimizador_rgpd import anonimizar_texto, generar_hash_abonado
from analitica_y_datos.batch_analitico import _analizar_por_reglas_locales, _analizar_con_gemini


def test_anonimizar_datos_personales():
    texto = (
        "Hola, mi DNI es 16607764Q (1, 6, 6, 0, 7, 7, 6, 4, letra Q), "
        "mi NIE X9719674N, mi móvil 654 32 10 98 y mi correo usuario.prueba@gmail.com."
    )
    resultado = anonimizar_texto(texto)

    assert "16607764Q" not in resultado
    assert "X9719674N" not in resultado
    assert "654 32 10 98" not in resultado
    assert "usuario.prueba@gmail.com" not in resultado
    assert resultado.count("[DNI_PROTEGIDO]") == 3
    assert "[TELEFONO_PROTEGIDO]" in resultado
    assert "[EMAIL_PROTEGIDO]" in resultado


def test_anonimizar_respeta_contactos_oficiales():
    texto = (
        "Llama al 941 27 70 55, escribe a deportes@logrono.es "
        "o manda el SEPA a tramites@logronodeporte.com."
    )
    resultado = anonimizar_texto(texto)

    assert "941 27 70 55" in resultado
    assert "deportes@logrono.es" in resultado
    assert "tramites@logronodeporte.com" in resultado


def test_hash_abonado_determinista_e_irreversible():
    h1 = generar_hash_abonado("16607764q")
    h2 = generar_hash_abonado(" 16607764Q ")

    assert h1 == h2
    assert h1.startswith("abo_")
    assert len(h1) == 14
    assert "16607764" not in h1
    assert generar_hash_abonado("") == "anonimo"


def test_batch_abandono_en_saludo():
    sesion = {
        "session_id": "ses_test_01",
        "dialogo": [{"rol": "agente", "texto": "¡Hola! Bienvenido a Logroño Deporte."}],
        "herramientas_usadas": [],
    }
    res = _analizar_con_gemini(sesion, cliente=None)
    assert res["categoria_principal"] == "Llamada sin consulta"
    assert res["resuelta"] is False


def test_batch_reglas_locales_categorias_y_friccion():
    sesion_sepa = {
        "dialogo": [
            {"rol": "usuario", "texto": "Quiero cambiar la cuenta bancaria SEPA en oficinas"},
            {"rol": "agente", "texto": "Envía el impreso firmado a tramites@logronodeporte.com."},
        ],
        "herramientas_usadas": ["consultar_web_logrono_deporte"],
    }
    res_sepa = _analizar_por_reglas_locales(sesion_sepa)
    assert res_sepa["categoria_principal"] == "Trámites y Oficinas"
    assert res_sepa["resuelta"] is True
    assert res_sepa["friccion_detectada"] is False

    sesion_friccion = {
        "dialogo": [
            {"rol": "usuario", "texto": "No, no, te he dicho mal el DNI"},
            {"rol": "agente", "texto": "No me aparecen cursos asociados, dime el fallo."},
        ],
        "herramientas_usadas": ["consultar_cursos_abonado"],
    }
    res_fric = _analizar_por_reglas_locales(sesion_friccion)
    assert res_fric["categoria_principal"] == "Cursos por DNI y Valoraciones"
    assert res_fric["friccion_detectada"] is True