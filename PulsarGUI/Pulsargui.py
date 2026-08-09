from __future__ import annotations

from pathlib import Path
from typing import Iterable
import tempfile

import sys
import os
from astropy.io import fits
from astropy.table import Table, vstack

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



import matplotlib.pyplot as plt
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



  

