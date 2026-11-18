import re
import hashlib

_REGEX_DNI_NIE = re.compile(
    r"\b(?:[XYZ][\s\-\.]?(?:\d[\s\-\.]?){7}|(?:\d[\s\-\.]?){8})[A-Z]\b",
    re.IGNORECASE,
)

_REGEX_DNI_DELETREADO = re.compile(
    r"(?:letra\s+[XYZ],\s*)?(?:\d,\s*){7,8}letra\s+[A-Z]\b",
    re.IGNORECASE,
)

_TELEFONOS_PUBLICOS_LD = {"941277055", "941277001", "941235924", "941490385", "941246182", "941253304"}
_REGEX_TELEFONO = re.compile(r"\b([679]\d{2}[\s\-\.]?\d{2,3}[\s\-\.]?\d{2,3}(?:[\s\-\.]?\d{2})?)\b")

_REGEX_EMAIL = re.compile(r"\b([a-zA-Z0-9_.+-]+@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+))\b")


def _reemplazar_telefono(match: re.Match) -> str:
    """Oculta teléfonos personales pero mantiene visibles los teléfonos públicos de Logroño Deporte."""
    solo_digitos = re.sub(r"\D", "", match.group(1))
    if len(solo_digitos) != 9 or solo_digitos in _TELEFONOS_PUBLICOS_LD:
        return match.group(0)
    return "[TELEFONO_PROTEGIDO]"


def _reemplazar_email(match: re.Match) -> str:
    """Oculta correos personales pero mantiene visibles los correos oficiales municipales."""
    dominio = match.group(2).lower()
    if dominio in ("logronodeporte.es", "logrono.es", "segurosdkv.es"):
        return match.group(0)
    return "[EMAIL_PROTEGIDO]"


def anonimizar_texto(texto: str) -> str:
    """
    Elimina cualquier dato personal identificable (DNI, NIE, teléfono móvil/fijo personal, email) de una transcripción antes de almacenarla en la base de datos (Cumplimiento RGPD).
    """
    if not texto:
        return ""

    limpio = _REGEX_DNI_DELETREADO.sub("[DNI_PROTEGIDO]", texto)
    limpio = _REGEX_DNI_NIE.sub("[DNI_PROTEGIDO]", limpio)
    limpio = _REGEX_TELEFONO.sub(_reemplazar_telefono, limpio)
    limpio = _REGEX_EMAIL.sub(_reemplazar_email, limpio)
    return limpio


def generar_hash_abonado(dni_limpio: str) -> str:
    """
    Genera un identificador anónimo irreversible (SHA-256 truncado) a partir del DNI para estadísticas sin almacenar el documento real del ciudadano.
    """
    if not dni_limpio:
        return "anonimo"
    digest = hashlib.sha256(dni_limpio.strip().upper().encode("utf-8")).hexdigest()[:10]
    return f"abo_{digest}"