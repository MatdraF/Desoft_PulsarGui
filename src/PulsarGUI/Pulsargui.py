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


def _find_hdu_index(hdul: fits.HDUList, name: str) -> int | None:
    target = name.upper()
    for index, hdu in enumerate(hdul):
        if str(getattr(hdu, "name", "")).upper() == target:
            return index
    return None


def validate_photon_fits(path: str | Path) -> tuple[bool, str]:
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


def detect_fermi_time_reference(path: str | Path) -> str:
    """Clasifica el sistema temporal del FT1 según TIMESYS/TIMEREF."""
    with fits.open(path, memmap=False) as hdul:
        header = hdul[1].header
        timesys = str(header.get("TIMESYS", "")).strip().upper()
        timeref = str(header.get("TIMEREF", "")).strip().upper()

    if timesys == "TT" and timeref == "LOCAL":
        return "raw"
    if timesys == "TT" and timeref == "GEOCENTER":
        return "geocentric"
    if timesys == "TDB" and timeref == "SOLARSYSTEM":
        return "barycentric"

    raise ValueError(
        "No se reconoce la referencia temporal del FITS: "
        f"TIMESYS={timesys!r}, TIMEREF={timeref!r}."
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


def _read_par_parameter(path: str | Path, key: str) -> str | None:
    target = key.upper()

    with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("C "):
                continue

            parts = line.split()
            if len(parts) >= 2 and parts[0].upper() == target:
                return parts[1]

    return None


def par_fits_coverage_status(
    par_path: str | Path,
    fits_path: str | Path,
) -> tuple[str, str]:
    """Comprueba START/FINISH del PAR cuando están disponibles.

    Retorna: "ok", "partial", "none" o "unknown".
    """
    start_text = _read_par_parameter(par_path, "START")
    finish_text = _read_par_parameter(par_path, "FINISH")

    if start_text is None or finish_text is None:
        return "unknown", "El PAR no declara START/FINISH; no se pudo verificar su cobertura temporal."

    try:
        par_start = float(start_text)
        par_finish = float(finish_text)

        with fits.open(fits_path, memmap=False) as hdul:
            data = hdul[1].data
            if data is None or "TIME" not in data.names:
                return "unknown", "El FITS no contiene TIME para verificar la cobertura."
            times = np.asarray(data["TIME"], dtype=float)
            finite = times[np.isfinite(times)]
            if finite.size == 0:
                return "unknown", "El FITS no contiene tiempos finitos."
            mjd = event_times_to_mjd(finite, hdul[1].header)

        event_start = float(np.min(mjd))
        event_finish = float(np.max(mjd))

    except Exception as exc:
        return "unknown", f"No se pudo comparar PAR y FITS: {exc}"

    if event_finish < par_start or event_start > par_finish:
        return (
            "none",
            f"La efeméride no cubre los eventos: PAR {par_start:.5f}–{par_finish:.5f} MJD, "
            f"FITS {event_start:.5f}–{event_finish:.5f} MJD.",
        )

    if event_start < par_start or event_finish > par_finish:
        return (
            "partial",
            f"La cobertura es parcial: PAR {par_start:.5f}–{par_finish:.5f} MJD, "
            f"FITS {event_start:.5f}–{event_finish:.5f} MJD.",
        )

    return (
        "ok",
        f"PAR y FITS son temporalmente compatibles: {event_start:.5f}–{event_finish:.5f} MJD.",
    )


def validate_ft2_temporal_coverage(
    event_path: str | Path,
    ft2_path: str | Path,
) -> tuple[bool, str]:
    """Exige que FT2 cubra todos los TIME del FT1 crudo."""
    try:
        with fits.open(event_path, memmap=False) as hdul:
            event_times = np.asarray(hdul[1].data["TIME"], dtype=float)

        with fits.open(ft2_path, memmap=False) as hdul:
            start = np.asarray(hdul[1].data["START"], dtype=float)
            stop = np.asarray(hdul[1].data["STOP"], dtype=float)

        event_times = event_times[np.isfinite(event_times)]
        start = start[np.isfinite(start)]
        stop = stop[np.isfinite(stop)]

        if event_times.size == 0 or start.size == 0 or stop.size == 0:
            return False, "No hay suficientes tiempos válidos para verificar la cobertura FT2."

        event_min = float(event_times.min())
        event_max = float(event_times.max())
        ft2_min = float(start.min())
        ft2_max = float(stop.max())

        if ft2_min > event_min or ft2_max < event_max:
            return (
                False,
                "El FT2 no cubre todo el intervalo del FT1: "
                f"FT2={ft2_min:.3f}–{ft2_max:.3f}, FT1={event_min:.3f}–{event_max:.3f} MET.",
            )

        return True, "El FT2 cubre temporalmente todos los eventos del FT1."

    except Exception as exc:
        return False, f"No se pudo verificar la cobertura FT2: {exc}"


# ---------------------------------------------------------------------------
# Unificación EVENTS + GTI
# ---------------------------------------------------------------------------

def _read_events_and_gti(
    path: Path,
) -> tuple[Table, Table, fits.Header, fits.Header, str, str]:
    with fits.open(path, memmap=False) as hdul:
        gti_index = _find_hdu_index(hdul, "GTI")
        if gti_index is None:
            raise ValueError(f"{path.name}: no contiene extensión GTI.")

        return (
            Table(hdul[1].data),
            Table(hdul[gti_index].data),
            hdul[1].header.copy(),
            hdul[gti_index].header.copy(),
            hdul[1].name or "EVENTS",
            hdul[gti_index].name or "GTI",
        )


def merge_overlapping_gti(gti_table: Table) -> Table:
    """Normaliza GTI solapadas o contiguas a una lista START/STOP no solapada."""
    starts = np.asarray(gti_table["START"], dtype=float)
    stops = np.asarray(gti_table["STOP"], dtype=float)

    mask = np.isfinite(starts) & np.isfinite(stops) & (stops >= starts)
    starts = starts[mask]
    stops = stops[mask]

    if starts.size == 0:
        raise ValueError("No hay intervalos GTI válidos.")

    order = np.argsort(starts)
    starts = starts[order]
    stops = stops[order]

    merged_starts = [float(starts[0])]
    merged_stops = [float(stops[0])]

    for start, stop in zip(starts[1:], stops[1:]):
        start = float(start)
        stop = float(stop)

        if start <= merged_stops[-1]:
            merged_stops[-1] = max(merged_stops[-1], stop)
        else:
            merged_starts.append(start)
            merged_stops.append(stop)

    result = Table()
    result["START"] = np.asarray(merged_starts, dtype=float)
    result["STOP"] = np.asarray(merged_stops, dtype=float)

    # Preservar unidades cuando existan.
    if getattr(gti_table["START"], "unit", None) is not None:
        result["START"].unit = gti_table["START"].unit
    if getattr(gti_table["STOP"], "unit", None) is not None:
        result["STOP"].unit = gti_table["STOP"].unit

    return result


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

def find_fermiphase_executable() -> str:
    executable = shutil.which("fermiphase")
    if executable:
        return executable

    scripts_dir = Path(sysconfig.get_path("scripts"))
    for candidate in (scripts_dir / "fermiphase.exe", scripts_dir / "fermiphase"):
        if candidate.exists() and candidate.is_file():
            return str(candidate)

    raise FileNotFoundError(
        "No se encontró fermiphase. "
        f"También se buscó en la carpeta Scripts de Python: {scripts_dir}"
    )


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

class PulsarGUISprint3(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("PulsarGUI")
        self.resize(820, 820)

        self.files: dict[str, str | list[str] | None] = {
            "par": None,
            "spacecraft": None,
            "photons": [],
        }

        self.processing_fits: str | None = None
        self.phase_fits: str | None = None

        self.worker: ExternalCommandWorker | None = None
        self.pending_external_output: Path | None = None

        # Solo se eliminan carpetas temporales creadas por esta ejecución.
        self._temp_dirs: set[Path] = set()

        self.build_ui()
        self.update_button_states()

    def build_ui(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background-color: #1a1a2e;
                color: #e2f3f5;
                font-family: Arial;
            }
            QLabel#sectionTitle {
                font-size: 13px;
                font-weight: bold;
                padding-top: 8px;
            }
            QPushButton {
                background-color: #4cc9f0;
                color: #16213e;
                padding: 10px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #6bd6ff; }
            QPushButton:disabled {
                background-color: #666666;
                color: #cccccc;
            }
            QListWidget {
                background-color: rgba(22, 33, 62, 0.7);
                border: 2px solid #4cc9f0;
                border-radius: 4px;
                padding: 4px;
            }
            """
        )

        layout = QVBoxLayout()

        title = QLabel("PulsarGUI")
        title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel(
            "Procesamiento y análisis temporal de datos de púlsares"
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # ---------------------------------------------------------------
        # 1. Archivos de entrada
        # ---------------------------------------------------------------
        section_files = QLabel("1. Archivos de entrada")
        section_files.setObjectName("sectionTitle")
        layout.addWidget(section_files)

        file_buttons = QHBoxLayout()

        self.par_button = QPushButton("📄 Cargar PAR")
        self.par_button.clicked.connect(self.load_par)
        file_buttons.addWidget(self.par_button)

        self.spacecraft_button = QPushButton("🛰️ Cargar FT2")
        self.spacecraft_button.clicked.connect(self.load_spacecraft)
        file_buttons.addWidget(self.spacecraft_button)

        self.photons_button = QPushButton("✨ Cargar FITS de fotones")
        self.photons_button.clicked.connect(self.load_photons)
        file_buttons.addWidget(self.photons_button)

        layout.addLayout(file_buttons)

        self.file_list = QListWidget()
        self.file_list.currentItemChanged.connect(
            lambda _current, _previous: self.update_button_states()
        )
        layout.addWidget(self.file_list)

        file_management = QHBoxLayout()

        self.remove_file_button = QPushButton("🗑️ Quitar seleccionado")
        self.remove_file_button.clicked.connect(self.remove_selected_file)
        file_management.addWidget(self.remove_file_button)

        self.clear_files_button = QPushButton("🧹 Limpiar sesión")
        self.clear_files_button.clicked.connect(self.clear_loaded_files)
        file_management.addWidget(self.clear_files_button)

        layout.addLayout(file_management)

        # ---------------------------------------------------------------
        # 2. Preparación de datos
        # ---------------------------------------------------------------
        section_prepare = QLabel("2. Preparación de datos")
        section_prepare.setObjectName("sectionTitle")
        layout.addWidget(section_prepare)

        self.merge_button = QPushButton("🚀 Unificar EVENTS + GTI")
        self.merge_button.clicked.connect(self.process_photons)
        layout.addWidget(self.merge_button)

        # ---------------------------------------------------------------
        # 3. Análisis
        # ---------------------------------------------------------------
        section_analysis = QLabel("3. Análisis")
        section_analysis.setObjectName("sectionTitle")
        layout.addWidget(section_analysis)

        self.histogram_button = QPushButton("🌌 Distribución espacial RA–DEC")
        self.histogram_button.clicked.connect(self.plot_histogram)
        layout.addWidget(self.histogram_button)

        self.phase_button = QPushButton("⏱️ Calcular fases con PINT")
        self.phase_button.clicked.connect(self.start_phase_calculation)
        layout.addWidget(self.phase_button)

        self.profile_button = QPushButton("📊 Faseograma + Perfil de Pulso")
        self.profile_button.clicked.connect(self.plot_phaseogram_and_profile)
        layout.addWidget(self.profile_button)

        # ---------------------------------------------------------------
        # Estado
        # ---------------------------------------------------------------
        section_status = QLabel("Estado de procesamiento")
        section_status.setObjectName("sectionTitle")
        layout.addWidget(section_status)

        self.status_label = QLabel("Estado: esperando archivos.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.cancel_button = QPushButton("⛔ Cancelar proceso")
        self.cancel_button.clicked.connect(self.cancel_external_process)
        layout.addWidget(self.cancel_button)

        note = QLabel(
            "PulsarGUI conserva los tiempos científicos del FITS durante el cálculo. "
            "PINT utiliza FT2 cuando los eventos Fermi son TT/LOCAL; la conversión "
            "a MJD se realiza únicamente para el eje temporal del faseograma. "
            "El faseograma y el perfil se muestran en dos ciclos consecutivos."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.setLayout(layout)

    def show_message(self, title: str, text: str, error: bool = False) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(
            QMessageBox.Icon.Critical if error else QMessageBox.Icon.Information
        )
        box.exec()

    def refresh_file_list(self) -> None:
        """Reconstruye la lista y asocia metadatos a cada elemento.

        Los metadatos permiten retirar de forma segura PAR, FT2, FITS de fotones
        y también descartar resultados derivados sin depender de la posición
        visual de cada fila.
        """
        self.file_list.clear()

        par = self.files["par"]
        spacecraft = self.files["spacecraft"]
        photons = self.files["photons"]

        def add_entry(text: str, kind: str, path: str | None = None) -> None:
            item = QListWidgetItem(text)
            item.setData(
                Qt.ItemDataRole.UserRole,
                {"kind": kind, "path": path},
            )
            self.file_list.addItem(item)

        if isinstance(par, str):
            add_entry(
                "📄 PAR: " + os.path.basename(par),
                "par",
                par,
            )

        if isinstance(spacecraft, str):
            add_entry(
                "🛰️ FT2: " + os.path.basename(spacecraft),
                "spacecraft",
                spacecraft,
            )

        if isinstance(photons, list):
            for path in photons:
                add_entry(
                    "✨ PH FITS: " + os.path.basename(path),
                    "photon",
                    path,
                )

        if self.processing_fits:
            add_entry(
                "✅ Dataset preparado: " + os.path.basename(self.processing_fits),
                "processing",
                self.processing_fits,
            )

        if self.phase_fits:
            add_entry(
                "📈 Resultado con fases: " + os.path.basename(self.phase_fits),
                "phase",
                self.phase_fits,
            )

    def process_running(self) -> bool:
        return bool(self.worker is not None and self.worker.isRunning())

    def update_button_states(self) -> None:
        photons = self.files["photons"]

        has_photons = isinstance(photons, list) and bool(photons)
        has_processing = self.processing_fits is not None
        has_par = isinstance(self.files["par"], str)
        has_any_files = (
            isinstance(self.files["par"], str)
            or isinstance(self.files["spacecraft"], str)
            or has_photons
            or self.processing_fits is not None
            or self.phase_fits is not None
        )
        has_selection = self.file_list.currentItem() is not None
        running = self.process_running()

        self.par_button.setEnabled(not running)
        self.spacecraft_button.setEnabled(not running)
        self.photons_button.setEnabled(not running)

        self.remove_file_button.setEnabled(has_selection and not running)
        self.clear_files_button.setEnabled(has_any_files and not running)

        self.merge_button.setEnabled(has_photons and not running)
        self.histogram_button.setEnabled(has_processing and not running)
        self.phase_button.setEnabled(has_processing and has_par and not running)
        self.profile_button.setEnabled(self.phase_fits is not None and not running)
        self.cancel_button.setEnabled(running)

    def invalidate_derived_outputs(self) -> None:
        self.processing_fits = None
        self.phase_fits = None
        self.pending_external_output = None

    def _register_temp_file(self, path: str | Path) -> None:
        parent = Path(path).resolve().parent
        temp_root = Path(tempfile.gettempdir()).resolve()

        try:
            parent.relative_to(temp_root)
        except ValueError:
            return

        if parent.name.startswith(("pulsargui_sprint3_", "pulsargui_phase_")):
            self._temp_dirs.add(parent)

    def remove_selected_file(self) -> None:
        """Quita de la sesión el elemento seleccionado sin borrar el archivo original."""
        item = self.file_list.currentItem()

        if item is None:
            return

        metadata = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(metadata, dict):
            return

        kind = metadata.get("kind")
        path = metadata.get("path")

        if kind == "par":
            self.files["par"] = None
            # Las fases dependen del modelo temporal.
            self.phase_fits = None
            self.status_label.setText("Estado: archivo PAR retirado de la sesión.")

        elif kind == "spacecraft":
            self.files["spacecraft"] = None
            # Si las fases fueron obtenidas desde un FT1 crudo, dependían del FT2.
            self.phase_fits = None
            self.status_label.setText("Estado: archivo FT2 retirado de la sesión.")

        elif kind == "photon":
            photons = self.files["photons"]
            assert isinstance(photons, list)

            if isinstance(path, str) and path in photons:
                photons.remove(path)

            # El dataset consolidado ya no representa las entradas actuales.
            self.invalidate_derived_outputs()
            self.status_label.setText("Estado: FITS de fotones retirado de la sesión.")

        elif kind == "processing":
            self.processing_fits = None
            self.phase_fits = None
            self.status_label.setText("Estado: dataset preparado descartado.")

        elif kind == "phase":
            self.phase_fits = None
            self.status_label.setText("Estado: resultado de fases descartado.")

        self.refresh_file_list()
        self.update_button_states()

    def clear_loaded_files(self) -> None:
        """Reinicia la sesión para poder trabajar con otro conjunto de archivos.

        No elimina PAR/FT2/PH originales del disco. Solo descarta referencias
        cargadas y resultados temporales creados por PulsarGUI.
        """
        if self.process_running():
            return

        reply = QMessageBox.question(
            self,
            "Limpiar sesión",
            "¿Quieres retirar todos los archivos cargados y comenzar una sesión nueva?\n\n"
            "Los archivos originales no se eliminarán del disco.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self.files["par"] = None
        self.files["spacecraft"] = None

        photons = self.files["photons"]
        if isinstance(photons, list):
            photons.clear()

        self.processing_fits = None
        self.phase_fits = None
        self.pending_external_output = None

        # Los temporales generados por la sesión ya no son necesarios.
        self._cleanup_temp_dirs()

        self.refresh_file_list()
        self.status_label.setText("Estado: sesión limpia. Puedes cargar un nuevo conjunto de datos.")
        self.update_button_states()

    def load_par(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo PAR",
            "",
            "PAR files (*.par)",
        )

        if not path:
            return

        ok, message = validate_par_file(path)
        if not ok:
            self.show_message("PAR inválido", message, error=True)
            return

        self.files["par"] = path
        self.phase_fits = None

        self.refresh_file_list()
        self.update_button_states()

    def load_spacecraft(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar FT2",
            "",
            "FITS files (*.fits *.fit)",
        )

        if not path:
            return

        ok, message = validate_spacecraft_fits(path)
        if not ok:
            self.show_message("FT2 inválido", message, error=True)
            return

        self.files["spacecraft"] = path

        self.refresh_file_list()
        self.update_button_states()

        if "SC_VELOCITY" not in {
            name.upper()
            for name in (fits.getdata(path, ext=1).names or [])
        }:
            self.status_label.setText(
                "Estado: FT2 cargado. Aviso: no se detectó SC_VELOCITY."
            )

    def load_photons(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar FITS de fotones",
            "",
            "FITS files (*.fits *.fit)",
        )

        errors: list[str] = []
        added = 0

        photons = self.files["photons"]
        assert isinstance(photons, list)

        for path in paths:
            ok, message = validate_photon_fits(path)

            if not ok:
                errors.append(f"{os.path.basename(path)}: {message}")
                continue

            if path not in photons:
                photons.append(path)
                added += 1

        if added:
            self.invalidate_derived_outputs()

        self.refresh_file_list()
        self.update_button_states()

        if errors:
            self.show_message(
                "Algunos FITS fueron rechazados",
                "\n".join(errors),
                error=True,
            )

    def process_photons(self) -> None:
        photons = self.files["photons"]

        if not isinstance(photons, list) or not photons:
            self.show_message("Aviso", "No hay FITS de fotones cargados.")
            return

        try:
            output = merge_event_fits(photons)
        except Exception as exc:
            self.show_message(
                "Error de unificación",
                f"No fue posible unificar EVENTS + GTI:\n{exc}",
                error=True,
            )
            return

        self.processing_fits = str(output)
        self.phase_fits = None
        self._register_temp_file(output)

        self.status_label.setText(
            "Estado: dataset preparado correctamente (EVENTS + GTI)."
        )

        self.refresh_file_list()
        self.update_button_states()

        self.show_message(
            "Preparación completada",
            "El dataset de eventos quedó preparado correctamente.",
        )

    def plot_histogram(self) -> None:
        if not self.processing_fits:
            return

        try:
            with fits.open(self.processing_fits, memmap=False) as hdul:
                data = Table(hdul[1].data)

            fig = plt.figure(figsize=(7, 7))
            ax = fig.add_subplot(111)

            ax.set_title("Distribución espacial de eventos — RA vs DEC", fontsize=14)
            ax.set_xlabel("Ascensión Recta (RA) [deg]")
            ax.set_ylabel("Declinación (DEC) [deg]")

            image = ax.hist2d(
                data["RA"],
                data["DEC"],
                bins=(200, 200),
                cmin=1,
                cmap="viridis",
            )

            fig.colorbar(image[3], ax=ax, label="Número de eventos")

            fig.tight_layout()
            plt.show()

        except Exception as exc:
            self.show_message(
                "Error de visualización",
                f"No fue posible generar el histograma:\n{exc}",
                error=True,
            )

    def _start_external_worker(
        self,
        operation: str,
        command: list[str],
        output: Path | None = None,
    ) -> None:
        if self.process_running():
            self.show_message(
                "Proceso en curso",
                "Ya existe un proceso ejecutándose.",
                error=True,
            )
            return

        self.pending_external_output = output
        self.worker = ExternalCommandWorker(operation, command)

        self.worker.completed.connect(self.finish_external_operation)
        self.worker.finished.connect(self._worker_finished)

        self.status_label.setText(f"Estado: ejecutando {operation}...")
        self.worker.start()
        self.update_button_states()

    def start_phase_calculation(self) -> None:
        if not self.processing_fits:
            return

        par = self.files["par"]
        spacecraft = self.files["spacecraft"]

        if not isinstance(par, str):
            return

        try:
            source = Path(self.processing_fits)

            # 1) Verificar compatibilidad temporal del modelo, cuando START/FINISH existen.
            coverage_state, coverage_message = par_fits_coverage_status(par, source)

            if coverage_state == "none":
                self.show_message(
                    "Efeméride incompatible",
                    coverage_message,
                    error=True,
                )
                return

            if coverage_state == "partial":
                self.show_message(
                    "Advertencia de cobertura",
                    coverage_message
                    + "\n\nEl cálculo continuará, pero las fases fuera del rango de la "
                    "efeméride no deben considerarse fiables.",
                )

            # 2) Decidir si PINT necesita FT2 según TIMESYS/TIMEREF.
            time_state = detect_fermi_time_reference(source)
            ft2_path: str | None = None

            if time_state == "raw":
                if not isinstance(spacecraft, str):
                    self.show_message(
                        "Falta FT2",
                        "El FT1 es TT/LOCAL (eventos Fermi crudos). "
                        "PINT necesita el FT2 para registrar la órbita de Fermi.",
                        error=True,
                    )
                    return

                ok, message = validate_ft2_temporal_coverage(source, spacecraft)
                if not ok:
                    self.show_message("Cobertura FT2 insuficiente", message, error=True)
                    return

                ft2_path = spacecraft

            # Geocéntrico o previamente baricentrado: no pasar FT2 innecesariamente.
            phase_dir = Path(tempfile.mkdtemp(prefix="pulsargui_phase_"))
            self._temp_dirs.add(phase_dir)

            output = phase_dir / f"{source.stem}_con_fase{source.suffix}"

            command = build_fermiphase_command(
                source,
                par,
                ft2_path=ft2_path,
                output_path=output,
            )

            self.status_label.setText(
                "Estado: PINT preparado. "
                + (
                    "FT1 crudo: se usará FT2 para la órbita de Fermi."
                    if time_state == "raw"
                    else f"Referencia temporal detectada: {time_state}."
                )
            )

        except Exception as exc:
            self.show_message(
                "Error preparando cálculo de fase",
                str(exc),
                error=True,
            )
            return

        self._start_external_worker("fermiphase", command, output)

    def finish_external_operation(
        self,
        operation: str,
        success: bool,
        message: str,
    ) -> None:
        output = self.pending_external_output

        if success and operation == "fermiphase":
            if output is None or not output.exists():
                success = False
                message = "fermiphase terminó sin error, pero no existe el archivo de salida."

            elif not has_column(output, "PULSE_PHASE"):
                success = False
                message = "fermiphase terminó, pero EVENTS no contiene PULSE_PHASE."

            else:
                self.phase_fits = str(output)
                message = (
                    "Cálculo de fases completado correctamente.\n"
                    "El TIME original del FITS se conserva."
                )

        self.status_label.setText(
            f"Estado: {operation} {'completado' if success else 'falló'}."
        )

        self.refresh_file_list()
        self.update_button_states()

        self.show_message(
            operation,
            message,
            error=not success,
        )

    def _worker_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()

        self.worker = None
        self.pending_external_output = None
        self.update_button_states()

    def cancel_external_process(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.status_label.setText("Estado: cancelando proceso...")
            self.worker.cancel()

    def plot_phaseogram_and_profile(self) -> None:
        if not self.phase_fits:
            return

        try:
            with fits.open(self.phase_fits, memmap=False) as hdul:
                data = Table(hdul[1].data)
                header = hdul[1].header.copy()

            if "PULSE_PHASE" not in data.colnames or "TIME" not in data.colnames:
                raise ValueError("El FITS no contiene TIME y PULSE_PHASE.")

            phases = np.asarray(data["PULSE_PHASE"], dtype=float) % 1.0
            times_original = np.asarray(data["TIME"], dtype=float)

            # MJD se calcula exclusivamente para visualización.
            times_mjd = event_times_to_mjd(times_original, header)

            mask = np.isfinite(phases) & np.isfinite(times_mjd)
            phases = phases[mask]
            times_mjd = times_mjd[mask]

            if phases.size == 0:
                raise ValueError("No existen fases válidas para visualizar.")

            # Duplicación visual: el segundo ciclo no agrega información física nueva.
            display_phases = np.concatenate((phases, phases + 1.0))
            display_times = np.concatenate((times_mjd, times_mjd))

            counts, edges = np.histogram(phases, bins=50, range=(0.0, 1.0))
            centers = 0.5 * (edges[:-1] + edges[1:])

            profile_x = np.concatenate((centers, centers + 1.0))
            profile_y = np.concatenate((counts, counts))

            fig = plt.figure(figsize=(10, 8))
            grid = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.08)

            ax_phase = fig.add_subplot(grid[0])
            ax_profile = fig.add_subplot(grid[1], sharex=ax_phase)

            ax_phase.scatter(display_phases, display_times, s=1)
            ax_phase.set_title("Faseograma y Perfil de Pulso — 2 ciclos")
            ax_phase.set_ylabel("Tiempo (MJD)")
            ax_phase.set_xlim(0.0, 2.0)
            ax_phase.grid(True, alpha=0.3)
            ax_phase.tick_params(axis="x", labelbottom=False)

            ax_profile.step(profile_x, profile_y, where="mid")
            ax_profile.set_xlabel("Fase de Pulso")
            ax_profile.set_ylabel("Eventos")
            ax_profile.set_xlim(0.0, 2.0)
            ax_profile.grid(True, alpha=0.3)

            fig.tight_layout()
            plt.show()

        except Exception as exc:
            self.show_message(
                "Error de visualización temporal",
                f"No fue posible generar faseograma/perfil:\n{exc}",
                error=True,
            )

    def _cleanup_temp_dirs(self) -> None:
        for directory in sorted(self._temp_dirs, key=lambda p: len(str(p)), reverse=True):
            try:
                if directory.exists():
                    shutil.rmtree(directory)
            except OSError:
                pass

        self._temp_dirs.clear()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()

            if not self.worker.wait(2000):
                event.ignore()
                self.show_message(
                    "Proceso aún cerrándose",
                    "Se solicitó detener el proceso. Intenta cerrar nuevamente en unos segundos.",
                    error=True,
                )
                return

        self._cleanup_temp_dirs()
        event.accept()


def graphical_interface() -> None:
    app = QApplication(sys.argv)
    window = PulsarGUISprint3()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    graphical_interface()



