import re
import unicodedata


def normalizar_texto(texto: str) -> str:
    """
    Convierte cualquier texto a MAYÚSCULAS y elimina las tildes o diéresis.
    """

    