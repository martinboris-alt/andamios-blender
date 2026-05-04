"""
Empaqueta el addon Andamios en un .zip listo para instalar en Blender.

Uso:
    python build_release.py

Genera: andamios.zip

Estructura del zip:
    andamios/
    ├── __init__.py   (copia de andamios_addon.py)
    └── calc/
        ├── __init__.py
        ├── model.py
        └── ...

Instalación en Blender:
    Edit → Preferences → Add-ons → Install… → selecciona andamios.zip
"""
import os
import shutil
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(ROOT, "_build")
ADDON_DIR = os.path.join(BUILD_DIR, "andamios")
ZIP_OUT = os.path.join(ROOT, "andamios.zip")

CALC_EXCLUDES = {"__pycache__", "tests"}


def clean():
    if os.path.isdir(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    if os.path.isfile(ZIP_OUT):
        os.remove(ZIP_OUT)


def copy_calc(src, dst):
    os.makedirs(dst, exist_ok=True)
    for entry in os.scandir(src):
        if entry.name in CALC_EXCLUDES:
            continue
        if entry.is_dir():
            copy_calc(entry.path, os.path.join(dst, entry.name))
        elif entry.name.endswith(".py"):
            shutil.copy2(entry.path, os.path.join(dst, entry.name))


def build():
    clean()
    os.makedirs(ADDON_DIR)

    # andamios_addon.py → andamios/__init__.py
    shutil.copy2(
        os.path.join(ROOT, "andamios_addon.py"),
        os.path.join(ADDON_DIR, "__init__.py"),
    )

    # calc/ → andamios/calc/
    copy_calc(
        os.path.join(ROOT, "calc"),
        os.path.join(ADDON_DIR, "calc"),
    )

    # Crear el zip: los paths dentro deben empezar con "andamios/"
    with zipfile.ZipFile(ZIP_OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ADDON_DIR):
            # Excluir __pycache__ dentro del zip también
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fname in filenames:
                abs_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(abs_path, BUILD_DIR)
                zf.write(abs_path, rel_path)

    shutil.rmtree(BUILD_DIR)
    print(f"[build] Listo: {ZIP_OUT}")
    print("[build] Instala en Blender: Edit > Preferences > Add-ons > Install... > andamios.zip")


if __name__ == "__main__":
    build()
