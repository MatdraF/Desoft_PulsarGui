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

def merge_event_fits(
    paths: Iterable[str | Path],
    output_path: str | Path | None = None,
) -> Path:
    """Une de forma preliminar las tablas de eventos (HDU 1) de varios FITS.

    Se preservan la HDU primaria, la cabecera de la HDU de eventos y las
    extensiones posteriores del primer archivo. Las GTI de archivos adicionales
    NO se fusionan: esta es una limitación explícita del Sprint 2.
    """
    file_paths = [Path(p) for p in paths]
    if not file_paths:
        raise ValueError("Se requiere al menos un archivo FITS de eventos.")

    for path in file_paths:
        ok, message = validate_photon_fits(path)
        if not ok:
            raise ValueError(f"{path.name}: {message}")

    tables = [Table.read(path, hdu=1) for path in file_paths]
    combined = vstack(tables, join_type="exact", metadata_conflicts="silent")

    if output_path is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="pulsar_sprint2_"))
        output = temp_dir / "eventos_unificados.fits"
    else:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

    with fits.open(file_paths[0], memmap=False) as first_hdul:
        primary_hdu = first_hdul[0].copy()
        event_header = first_hdul[1].header.copy()
        event_name = first_hdul[1].name
        extra_hdus = [hdu.copy() for hdu in first_hdul[2:]]

    event_hdu = fits.BinTableHDU(
        data=combined.as_array(),
        header=event_header,
        name=event_name,
    )
    fits.HDUList([primary_hdu, event_hdu, *extra_hdus]).writeto(
        output, overwrite=True
    )

    return output

def build_fermiphase_command(fits_path: str | Path, par_path: str | Path) -> list[str]:
    """Construye el comando utilizado para calcular/agregar PULSE_PHASE con PINT."""
    return [
        "fermiphase",
        "--addphase",
        str(fits_path),
        str(par_path),
        "CALC",
    ]


def has_column(path: str | Path, column_name: str) -> bool:
    """Indica si la HDU 1 contiene una columna dada."""
    ok, columns, _ = _get_hdu1_columns(path)
    return bool(ok and columns and column_name.upper() in columns)


#////////////////////////////////////////////

