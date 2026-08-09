from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
from astropy.io import fits
from astropy.table import Table, vstack
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

PHOTON_REQUIRED_COLUMNS = {"TIME", "RA", "DEC", "ENERGY"}
def validate_par_file(path: str | Path) -> tuple[bool, str]:
    """Validación básica de un archivo de parámetros .par.

    En Sprint 2 no se intenta interpretar todo el modelo de timing: se comprueba
    que exista, tenga extensión .par y no esté vacío.
    """
    file_path = Path(path)

    if not file_path.exists() or not file_path.is_file():
        return False, "El archivo PAR no existe."
    if file_path.suffix.lower() != ".par":
        return False, "El archivo seleccionado no tiene extensión .par."
    if file_path.stat().st_size == 0:
        return False, "El archivo PAR está vacío."

    return True, "Archivo PAR válido para la validación inicial del Sprint 2."

def _get_hdu1_columns(path: str | Path) -> tuple[bool, set[str] | None, str]:
    file_path = Path(path)

    if not file_path.exists() or not file_path.is_file():
        return False, None, "El archivo FITS no existe."
    if file_path.suffix.lower() not in {".fits", ".fit"}:
        return False, None, "El archivo seleccionado no tiene extensión FITS."

    try:
        with fits.open(file_path, memmap=False) as hdul:
            if len(hdul) < 2:
                return False, None, "El FITS no contiene una extensión HDU 1 con datos tabulares."
            columns = getattr(hdul[1], "columns", None)
            if columns is None or columns.names is None:
                return False, None, "La HDU 1 del FITS no contiene columnas tabulares."
            names = {str(name).upper() for name in columns.names}
            return True, names, "FITS legible."
    except Exception as exc:
        return False, None, f"No se pudo leer el FITS: {exc}"

def validate_photon_fits(path: str | Path) -> tuple[bool, str]:
    """Comprueba que un FITS de eventos tenga columnas mínimas usadas por la GUI."""
    ok, columns, message = _get_hdu1_columns(path)
    if not ok or columns is None:
        return False, message

    missing = sorted(PHOTON_REQUIRED_COLUMNS - columns)
    if missing:
        return False, "Faltan columnas requeridas para eventos: " + ", ".join(missing)

    return True, "FITS de fotones válido para el procesamiento inicial."

def validate_spacecraft_fits(path: str | Path) -> tuple[bool, str]:
    """Validación estructural básica del FITS de nave.

    En esta versión el archivo de nave se conserva como entrada opcional y no se
    utiliza todavía para baricentrado automático. Solo se comprueba que sea un
    FITS tabular legible.
    """
    ok, columns, message = _get_hdu1_columns(path)
    if not ok or columns is None:
        return False, message
    if len(columns) == 0:
        return False, "El FITS de nave no contiene columnas en la HDU 1."
    return True, "FITS de nave legible (uso opcional en Sprint 2)."


  

