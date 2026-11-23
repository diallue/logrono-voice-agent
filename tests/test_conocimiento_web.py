import time
from datos_web.conversor_md import html_a_markdown
from datos_web.buscador_local import buscar_en_md_locales
from tools.utils import normalizar_texto, obtener_raiz


def test_conversor_decodifica_joomla_tablas_y_recorta_pie():
    html_muestra = """
    <html>
      <head><title>Cambio de cuenta</title><script>var otro = 1;</script></head>
      <body>
        <h2>Cambio de cuenta corriente</h2>
        <p>Remitir el impreso a:
          <span id="cloak123">Esta dirección de correo electrónico está siendo protegida contra los robots de spam. Necesita tener JavaScript habilitado para poder verlo.</span>
          <script type="text/javascript">
            var addy123 = 'tr&#97;m&#105;t&#101;s' + '&#64;';
            addy123 = addy123 + 'logronodeporte' + '&#46;' + 'com';
          </script>
        </p>
        <table>
          <tr><th>Modalidad</th><th>Cuota</th></tr>
          <tr><td>Adulto</td><td>120,60 €</td></tr>
        </table>
        <input type="text" placeholder="Código localizador" />
        <div>volver arriba</div>
        <p>Texto basura del pie que no debe aparecer</p>
      </body>
    </html>
    """
    md = html_a_markdown(html_muestra)

    assert "tramites@logronodeporte.com" in md
    assert "robots de spam" not in md
    assert "| Modalidad | Cuota |" in md
    assert "| Adulto | 120,60 € |" in md
    assert "[Campo de formulario: Código localizador]" in md
    assert "Texto basura del pie" not in md


def test_buscador_local_tarifas_y_baja_latencia():
    consulta = normalizar_texto("cuanto cuesta el abono familiar tarifas 2026")
    palabras = [p for p in consulta.split() if len(p) > 2]
    raices = [obtener_raiz(p) for p in palabras if len(p) >= 4]

    t0 = time.perf_counter()
    max_pts, bloques = buscar_en_md_locales(palabras, raices)
    latencia_ms = (time.perf_counter() - t0) * 1000

    assert max_pts >= 12
    assert len(bloques) >= 1
    assert any("241,00" in b or "Abono" in b for b in bloques)
    assert latencia_ms < 100.0 


def test_buscador_local_distingue_correos_tramites():
    palabras = ["CUENTA", "BANCARIA", "SEPA", "BAJA"]
    raices = [obtener_raiz(p) for p in palabras]

    max_pts, bloques = buscar_en_md_locales(palabras, raices)
    texto_combinado = "\n".join(bloques)

    assert max_pts >= 12
    assert "tramites@logronodeporte.com" in texto_combinado
    assert "deportes@logrono.es" in texto_combinado