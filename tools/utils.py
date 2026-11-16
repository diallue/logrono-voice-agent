import re

_TABLA_SIN_TILDES = str.maketrans("ÁÉÍÓÚÜ", "AEIOUU")

_STOP_WORDS_DNI = {"MI", "ES", "EL", "LA", "LOS", "CON", "DNI", "NIE", "NUMERO", "LETRA", "TERMINADO", "EN", "GUION", "PUNTO"}

_REGEX_LETRA_FONETICA = re.compile(r"\b([A-Z])\s+(?:DE|COMO)\s+[A-Z]+\b")

_REGEX_ESTRUCTURA_DNI = re.compile(r"^([XYZ]?\d{7,8})([A-Z])")

_REGEX_DNI_OFICIAL = re.compile(r"^(?:\d{8}|[XYZ]\d{7})[A-Z]$")

_SUFIJOS_ES = (
    "ACIONES", "ACION", "AMIENTO", "ARME", "IRME",
    "ARSE", "IRSE", "ANDO", "IENDO", "ADOS", "ADAS", "ES", "S"
)


def normalizar_texto(texto: str) -> str:
    """
    Pasa a mayúsculas, limpia extremos y elimina tildes/diéresis.
    """
    return texto.strip().upper().translate(_TABLA_SIN_TILDES) if texto else ""

def limpiar_dni(dni_raw: str) -> str:
    """
    Normaliza un DNI/NIE dictado por voz y resuelve apoyos fonéticos.
    """
    texto = normalizar_texto(dni_raw)
    texto = _REGEX_LETRA_FONETICA.sub(r"\1", texto)

    tokens = [t for t in re.split(r"[^A-Z0-9]+", texto) if t and t not in _STOP_WORDS_DNI]
    limpio = "".join(tokens)

    match = _REGEX_ESTRUCTURA_DNI.match(limpio)
    return f"{match.group(1)}{match.group(2)}" if match else limpio


def es_dni_valido(dni: str) -> bool:
    """Verifica si el string cumple el patrón oficial de DNI (8N+1L) o NIE (X/Y/Z+7N+1L)."""
    return bool(_REGEX_DNI_OFICIAL.fullmatch(dni))


def formatear_dni_voz(dni: str) -> str:
    """
    Formatea el DNI para lectura TTS dígito a dígito.
    """
    if not dni:
        return "ningún carácter válido"
    return ", ".join(f"letra {c}" if c.isalpha() else c for c in dni)


def obtener_raiz(palabra: str) -> str:
    """Reduce una palabra a su raíz para mejorar el cruce de búsquedas (ej: 'INSCRIBIRME' -> 'INSCRI')."""
    palabra = normalizar_texto(palabra)
    if len(palabra) <= 4:
        return palabra

    for sufijo in _SUFIJOS_ES:
        if palabra.endswith(sufijo) and len(palabra) - len(sufijo) >= 4:
            return palabra[:-len(sufijo)][:6]

    return palabra[:6]

    