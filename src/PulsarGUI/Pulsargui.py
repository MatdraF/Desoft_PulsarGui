from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import threading
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
from astropy import units as u
from astropy.io import fits
from astropy.table import Table, vstack
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

PHOTON_REQUIRED_COLUMNS = {"TIME", "RA", "DEC", "ENERGY"}
GTI_REQUIRED_COLUMNS = {"START", "STOP"}
FT2_REQUIRED_COLUMNS = {"START", "STOP", "SC_POSITION"}
TIME_HEADER_KEYS = ("TIMESYS", "TIMEREF", "TIMEUNIT")
EXTERNAL_PROCESS_TIMEOUT_S = 15 * 60

# ---------------------------------------------------------------------------
# Validación de archivos
# ---------------------------------------------------------------------------


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

    return True, "Archivo PAR válido."

def _get_hdu1_columns(path: str | Path) -> tuple[bool, set[str] | None, str]:
    file_path = Path(path)

    if not file_path.exists() or not file_path.is_file():
        return False, None, "El archivo FITS no existe."
    if file_path.suffix.lower() not in {".fits", ".fit"}:
        return False, None, "El archivo seleccionado no tiene extensión FITS."

    try:
        with fits.open(file_path, memmap=False) as hdul:
            if len(hdul) < 2:
                return False, None, "El FITS no contiene una HDU 1 tabular."
            columns = getattr(hdul[1], "columns", None)
            if columns is None or columns.names is None:
                return False, None, "La HDU 1 no contiene columnas tabulares."
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
        return False, "Faltan columnas de eventos: " + ", ".join(missing)

    try:
        with fits.open(path, memmap=False) as hdul:
            gti_index = _find_hdu_index(hdul, "GTI")
            if gti_index is None:
                return False, "El FITS no contiene una extensión GTI."

            gti_columns = getattr(hdul[gti_index], "columns", None)
            if gti_columns is None or gti_columns.names is None:
                return False, "La extensión GTI no contiene una tabla válida."

            gti_names = {str(name).upper() for name in gti_columns.names}
            missing_gti = sorted(GTI_REQUIRED_COLUMNS - gti_names)
            if missing_gti:
                return False, "La GTI no contiene: " + ", ".join(missing_gti)

    except Exception as exc:
        return False, f"No se pudo validar la GTI: {exc}"

    return True, "FITS de eventos y GTI válido."


def validate_spacecraft_fits(path: str | Path) -> tuple[bool, str]:
    """Valida la estructura mínima de un FT2 de Fermi."""
    ok, columns, message = _get_hdu1_columns(path)
    if not ok or columns is None:
        return False, message
    
    missing = sorted(FT2_REQUIRED_COLUMNS - columns)
    if missing:
        return False, "El FITS de nave no parece un FT2 de Fermi. Faltan: " + ", ".join(missing)

    warning = ""
    if "SC_VELOCITY" not in columns:
        warning = " SC_VELOCITY no está presente; PINT puede depender de la versión/formato del FT2."

    return True, "FT2 de Fermi válido estructuralmente." + warning


# ---------------------------------------------------------------------------
# Tiempo y compatibilidad
# ---------------------------------------------------------------------------
def _time_metadata(header: fits.Header) -> dict[str, str]:
    return {
        key: str(header[key]).strip()
        for key in TIME_HEADER_KEYS
        if key in header and str(header[key]).strip()
    }
    
def _assert_time_metadata_compatible(paths: list[Path]) -> None:
    reference: dict[str, str] | None = None
    reference_name = ""

    for path in paths:
        with fits.open(path, memmap=False) as hdul:
            current = _time_metadata(hdul[1].header)

        if reference is None:
            reference = current
            reference_name = path.name
            continue

        for key in TIME_HEADER_KEYS:
            left = reference.get(key)
            right = current.get(key)
            if left is not None and right is not None and left.upper() != right.upper():
                raise ValueError(
                    f"Metadatos temporales incompatibles: {key}={left!r} en "
                    f"{reference_name} y {key}={right!r} en {path.name}."
                )
                
def _mjd_reference(header: fits.Header) -> float:
    if "MJDREF" in header:
        return float(header["MJDREF"])

    if "MJDREFI" in header or "MJDREFF" in header:
        return float(header.get("MJDREFI", 0.0)) + float(header.get("MJDREFF", 0.0))

    raise ValueError("El FITS no contiene MJDREF ni MJDREFI/MJDREFF.")

def event_times_to_mjd(times: np.ndarray, header: fits.Header) -> np.ndarray:
    """Convierte TIME a MJD solo para presentación/validación, sin modificar el FITS."""
    mjdref = _mjd_reference(header)
    timezero = float(header.get("TIMEZERO", 0.0))
    unit_name = str(header.get("TIMEUNIT", "s")).strip() or "s"

    try:
        factor_days = (1.0 * u.Unit(unit_name)).to_value(u.day)
    except Exception as exc:
        raise ValueError(f"TIMEUNIT={unit_name!r} no se pudo interpretar: {exc}") from exc

    return mjdref + (np.asarray(times, dtype=float) + timezero) * factor_days

# ---------------------------------------------------------------------------
# Unificación EVENTS + GTI
# ---------------------------------------------------------------------------

def merge_event_fits(
    paths: Iterable[str | Path],
    output_path: str | Path | None = None,
) -> Path:
    """Fusiona EVENTS y GTI, ordena eventos y normaliza GTI solapadas."""
    file_paths = [Path(p) for p in paths]
    if not file_paths:
        raise ValueError("Se requiere al menos un FITS de eventos.")

    for path in file_paths:
        ok, message = validate_photon_fits(path)
        if not ok:
            raise ValueError(f"{path.name}: {message}")

    _assert_time_metadata_compatible(file_paths)

    event_tables: list[Table] = []
    gti_tables: list[Table] = []

    event_header: fits.Header | None = None
    gti_header: fits.Header | None = None
    event_name = "EVENTS"
    gti_name = "GTI"

    for index, path in enumerate(file_paths):
        (
            events,
            gti,
            current_event_header,
            current_gti_header,
            current_event_name,
            current_gti_name,
        ) = _read_events_and_gti(path)

        event_tables.append(events)
        gti_tables.append(gti)

        if index == 0:
            event_header = current_event_header
            gti_header = current_gti_header
            event_name = current_event_name
            gti_name = current_gti_name

    combined_events = vstack(event_tables, join_type="exact", metadata_conflicts="silent")
    combined_gti_raw = vstack(gti_tables, join_type="exact", metadata_conflicts="silent")

    combined_events.sort("TIME")
    combined_gti = merge_overlapping_gti(combined_gti_raw)

    tstart = float(np.min(np.asarray(combined_gti["START"], dtype=float)))
    tstop = float(np.max(np.asarray(combined_gti["STOP"], dtype=float)))

    if output_path is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="pulsargui_sprint3_"))
        output = temp_dir / "eventos_y_gti_unificados.fits"
    else:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

    with fits.open(file_paths[0], memmap=False) as first_hdul:
        primary_hdu = first_hdul[0].copy()

        extra_hdus = []
        for index, hdu in enumerate(first_hdul[1:], start=1):
            name = str(getattr(hdu, "name", "")).upper()
            if index == 1 or name == "GTI":
                continue
            extra_hdus.append(hdu.copy())

    assert event_header is not None
    assert gti_header is not None

    # Actualizar únicamente metadatos cuya interpretación es inequívoca.
    event_header["TSTART"] = tstart
    event_header["TSTOP"] = tstop
    gti_header["TSTART"] = tstart
    gti_header["TSTOP"] = tstop

    if "TSTART" in primary_hdu.header:
        primary_hdu.header["TSTART"] = tstart
    if "TSTOP" in primary_hdu.header:
        primary_hdu.header["TSTOP"] = tstop

    event_hdu = fits.BinTableHDU(
        data=combined_events.as_array(),
        header=event_header,
        name=event_name,
    )
    gti_hdu = fits.BinTableHDU(
        data=combined_gti.as_array(),
        header=gti_header,
        name=gti_name,
    )

    fits.HDUList([primary_hdu, event_hdu, gti_hdu, *extra_hdus]).writeto(
        output,
        overwrite=True,
        checksum=True,
    )

    return output
# ---------------------------------------------------------------------------
# PINT / fermiphase
# ---------------------------------------------------------------------------

def build_fermiphase_command(
    fits_path: str | Path,
    par_path: str | Path,
    ft2_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> list[str]:
    command = [
        find_fermiphase_executable(),
        str(fits_path),
        str(par_path),
        "CALC",
    ]

    if ft2_path is not None:
        command.extend(["--ft2", str(ft2_path)])

    if output_path is not None:
        command.extend(["--outfile", str(output_path)])
    else:
        command.append("--addphase")

    return command

def has_column(path: str | Path, column_name: str) -> bool:
    """Indica si la HDU 1 contiene una columna dada."""
    ok, columns, _ = _get_hdu1_columns(path)
    return bool(ok and columns and column_name.upper() in columns)


class ExternalCommandWorker(QThread):
    completed = pyqtSignal(str, bool, str)

    def __init__(
        self,
        operation: str,
        command: list[str],
        timeout_s: int = EXTERNAL_PROCESS_TIMEOUT_S,
    ):
        super().__init__()
        self.operation = operation
        self.command = command
        self.timeout_s = timeout_s
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    def cancel(self) -> None:
        self.requestInterruption()

        with self._process_lock:
            process = self._process

        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    def run(self) -> None:
        if self.isInterruptionRequested():
            self.completed.emit(self.operation, False, "Operación cancelada antes de comenzar.")
            return

        try:
            process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            with self._process_lock:
                self._process = process

            try:
                stdout, stderr = process.communicate(timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                self.completed.emit(
                    self.operation,
                    False,
                    f"La operación superó {self.timeout_s} s y fue detenida.",
                )
                return

            if self.isInterruptionRequested():
                self.completed.emit(self.operation, False, "Operación cancelada.")
                return

            if process.returncode != 0:
                detail = (stderr or stdout or "Sin detalle adicional").strip()
                self.completed.emit(
                    self.operation,
                    False,
                    f"El proceso terminó con código {process.returncode}:\n{detail}",
                )
                return

            detail = (stdout or stderr or "Proceso completado correctamente.").strip()
            self.completed.emit(self.operation, True, detail)

        except FileNotFoundError:
            executable = self.command[0] if self.command else "comando externo"
            self.completed.emit(
                self.operation,
                False,
                f"No se encontró '{executable}' en el entorno actual.",
            )
        except Exception as exc:
            self.completed.emit(self.operation, False, f"Error inesperado: {exc}")
        finally:
            with self._process_lock:
                self._process = None
# ---------------------------------------------------------------------------
# GUI principal: procesamiento/visualización solamente
# ---------------------------------------------------------------------------

class PulsarGUISprint2(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PulsarGUI - Sprint 2")
        self.resize(680, 650)

        self.files = {
            "par": None,
            "spacecraft": None,
            "photons": [],
        }
        self.processing_fits: str | None = None
        self.worker: PhaseWorker | None = None

        self.build_ui()
        self.update_button_states()

    def build_ui(self):
        self.setStyleSheet(
            """
            QWidget { background-color: #1a1a2e; color: #e2f3f5; font-family: Arial; }
            QPushButton {
                background-color: #4cc9f0; color: #16213e;
                padding: 10px; font-weight: bold; border-radius: 5px;
            }
            QPushButton:hover { background-color: #6bd6ff; }
            QPushButton:disabled { background-color: #666666; color: #cccccc; }
            QListWidget {
                background-color: rgba(22, 33, 62, 0.7);
                border: 2px solid #4cc9f0;
            }
            """
        )

        layout = QVBoxLayout()

        title = QLabel("PulsarGUI — Implementación parcial Sprint 2")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel(
            "Carga y validación de archivos, unificación preliminar de eventos, "
            "histograma RA–DEC e integración inicial con PINT/fermiphase."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        # ---------------------------------------------------------------
        # 1. Archivos de entrada
        # ---------------------------------------------------------------
        file_buttons = QHBoxLayout()

        self.par_button = QPushButton("📄 Cargar PAR")
        self.par_button.clicked.connect(self.load_par)
        file_buttons.addWidget(self.par_button)

        self.spacecraft_button = QPushButton("🛰️ FITS Nave (opcional)")
        self.spacecraft_button.clicked.connect(self.load_spacecraft)
        file_buttons.addWidget(self.spacecraft_button)

        self.photons_button = QPushButton("✨ Cargar FITS Fotones")
        self.photons_button.clicked.connect(self.load_photons)
        file_buttons.addWidget(self.photons_button)

        layout.addLayout(file_buttons)

        self.file_list = QListWidget()
        layout.addWidget(self.file_list)
        # ---------------------------------------------------------------
        # 2. Preparación de datos
        # ---------------------------------------------------------------
        self.merge_button = QPushButton("🚀 Unificar Fotones")
        self.merge_button.setStyleSheet("background-color: #f72585; color: white;")
        self.merge_button.clicked.connect(self.process_photons)
        layout.addWidget(self.merge_button)
        # ---------------------------------------------------------------
        # 3. Análisis
        # ---------------------------------------------------------------
        self.histogram_button = QPushButton("🌌 Generar Histograma 2D RA–DEC")
        self.histogram_button.setStyleSheet("background-color: #2ecc71; color: white;")
        self.histogram_button.clicked.connect(self.plot_histogram)
        layout.addWidget(self.histogram_button)

        self.phase_button = QPushButton("⏱️ Calcular fases con PINT")
        self.phase_button.setStyleSheet("background-color: #f39c12; color: white;")
        self.phase_button.clicked.connect(self.start_phase_calculation)
        layout.addWidget(self.phase_button)
        # ---------------------------------------------------------------
        # Estado
        # ---------------------------------------------------------------
        limitation = QLabel(
            "Nota Sprint 2: la unificación combina la tabla de eventos y conserva las "
            "extensiones del primer FITS, pero no fusiona GTI de archivos adicionales. "
            "El faseograma y el perfil de pulso completos quedan para Sprint 3."
        )
        limitation.setWordWrap(True)
        layout.addWidget(limitation)

        self.setLayout(layout)

    def show_message(self, title: str, text: str, error: bool = False):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Critical if error else QMessageBox.Icon.Information)
        box.exec()

    def refresh_file_list(self):
        self.file_list.clear()

        if self.files["par"]:
            self.file_list.addItem("📄 PAR: " + os.path.basename(self.files["par"]))
        if self.files["spacecraft"]:
            self.file_list.addItem(
                "🛰️ SC FITS (opcional): " + os.path.basename(self.files["spacecraft"])
            )
        for path in self.files["photons"]:
            self.file_list.addItem("✨ PH FITS: " + os.path.basename(path))
        if self.processing_fits:
            self.file_list.addItem(
                "✅ FITS de procesamiento: " + os.path.basename(self.processing_fits)
            )

    def update_button_states(self):
        has_photons = len(self.files["photons"]) > 0
        has_processing_file = self.processing_fits is not None
        has_par = self.files["par"] is not None

        self.merge_button.setEnabled(has_photons)
        self.histogram_button.setEnabled(has_processing_file)
        self.phase_button.setEnabled(has_processing_file and has_par)

    def load_par(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar archivo PAR", "", "PAR files (*.par)"
        )
        if not path:
            return

        ok, message = validate_par_file(path)
        if not ok:
            self.show_message("PAR inválido", message, error=True)
            return

        self.files["par"] = path
        self.refresh_file_list()
        self.update_button_states()

    def load_spacecraft(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar FITS de nave",
            "",
            "FITS files (*.fits *.fit)",
        )
        if not path:
            return

        ok, message = validate_spacecraft_fits(path)
        if not ok:
            self.show_message("FITS de nave inválido", message, error=True)
            return

        self.files["spacecraft"] = path
        self.refresh_file_list()
        self.update_button_states()

    def load_photons(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar FITS de fotones",
            "",
            "FITS files (*.fits *.fit)",
        )

        errors = []
        added = 0

        for path in paths:
            ok, message = validate_photon_fits(path)
            if not ok:
                errors.append(f"{os.path.basename(path)}: {message}")
                continue
            if path not in self.files["photons"]:
                self.files["photons"].append(path)
                added += 1

        # Cualquier cambio en las entradas invalida el resultado unificado previo.
        if added:
            self.processing_fits = None

        self.refresh_file_list()
        self.update_button_states()

        if errors:
            self.show_message(
                "Algunos FITS fueron rechazados",
                "\n".join(errors),
                error=True,
            )

    def process_photons(self):
        if not self.files["photons"]:
            self.show_message("Aviso", "No hay FITS de fotones cargados.")
            return

        try:
            output = merge_event_fits(self.files["photons"])
        except Exception as exc:
            self.show_message(
                "Error de unificación",
                f"No fue posible unificar los eventos:\n{exc}",
                error=True,
            )
            return

        self.processing_fits = str(output)
        self.refresh_file_list()
        self.update_button_states()
        self.show_message(
            "Unificación completada",
            "Se creó un FITS de procesamiento preliminar en:\n"
            f"{self.processing_fits}\n\n"
            "Importante: las GTI de archivos adicionales no se fusionan en esta versión.",
        )

    def plot_histogram(self):
        if not self.processing_fits:
            return

        try:
            with fits.open(self.processing_fits, memmap=False) as hdul:
                data = Table.read(hdul[1])

            fig = plt.figure(figsize=(7, 7))
            ax = fig.add_subplot(111)
            ax.set_title("Histograma 2D Espacial (RA–DEC)", fontsize=14)
            ax.set_xlabel("Ascensión Recta (RA)")
            ax.set_ylabel("Declinación (DEC)")
            image = ax.hist2d(
                data["RA"],
                data["DEC"],
                bins=(200, 200),
                cmin=1,
                cmap="viridis",
            )
            fig.colorbar(image[3], ax=ax, label="Número de eventos")
            plt.show()
        except Exception as exc:
            self.show_message(
                "Error de visualización",
                f"No fue posible generar el histograma:\n{exc}",
                error=True,
            )

    def start_phase_calculation(self):
        if not self.processing_fits or not self.files["par"]:
            return

        self.phase_button.setEnabled(False)
        self.phase_button.setText("Calculando fases con PINT... ⏳")

        self.worker = PhaseWorker(self.files["par"], self.processing_fits)
        self.worker.finished_with_status.connect(self.finish_phase_calculation)
        self.worker.start()

    def finish_phase_calculation(self, success: bool, message: str):
        self.phase_button.setText("⏱️ Calcular fases con PINT")
        self.update_button_states()
        self.show_message(
            "PINT / fermiphase" if success else "Error PINT / fermiphase",
            message,
            error=not success,
        )



def graphical_interface():
    app = QApplication(sys.argv)
    window = PulsarGUISprint2()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    graphical_interface()


