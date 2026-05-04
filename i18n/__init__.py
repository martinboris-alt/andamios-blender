"""Sistema de internacionalización del addon Andamios.

El addon registra un diccionario de traducciones con
``bpy.app.translations.register``. Los msgid son los strings españoles
que aparecen en el código fuente (name=, description=, bl_label, items=,
text=, etc.); el español es por tanto el idioma "fuente". El único
idioma traducido es ``en_US``.

Para usuarios cuyo Blender está en español (o sin idioma instalado), el
fallback es el msgid → ven el texto original. Para usuarios con Blender
en inglés, Blender busca la entrada ``(None, msgid)`` en el dict
``en_US`` y, si existe, la sustituye automáticamente en cualquier
``layout.label``, ``bl_label``, ``description``, etc.

Uso desde otros módulos del addon:

    from i18n import pgettext_iface as iface_  # alias corto

    # En f-strings o textos dinámicos no constantes hay que envolver
    # explícitamente la parte traducible:
    text = f"{iface_('Solo entran')} {n} {iface_('bandejas')}"

Para strings literales constantes en ``layout.label(text='...')``,
``bl_label = '...'``, ``name='...'``, etc. NO hace falta envoltorio:
Blender los traduce automáticamente cuando el msgid existe en el dict.
"""

import bpy
from bpy.app.translations import (
    pgettext_iface,
    pgettext_data,
    pgettext_tip,
)

from .translations import TRANSLATIONS

ADDON_NAME = "andamios"


def register() -> None:
    """Registra el dict de traducciones en Blender. Idempotente."""
    try:
        bpy.app.translations.unregister(ADDON_NAME)
    except Exception:
        pass
    bpy.app.translations.register(ADDON_NAME, TRANSLATIONS)


def unregister() -> None:
    """Desregistra el dict. Tolera ya-no-registrado."""
    try:
        bpy.app.translations.unregister(ADDON_NAME)
    except Exception:
        pass


__all__ = [
    "register",
    "unregister",
    "pgettext_iface",
    "pgettext_data",
    "pgettext_tip",
    "TRANSLATIONS",
]
