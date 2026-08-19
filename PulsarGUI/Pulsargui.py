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
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.table import Table, vstack
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QFont
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
GTI_REQUIRED_COLUMNS = {"START", "STOP"}
TIME_HEADER_KEYS = ("TIMESYS", "TIMEREF", "TIMEUNIT")
EXTERNAL_PROCESS_TIMEOUT_S = 15 * 60


def validate_par_file(path: str | Path) -> tuple[bool, str]:
    """Validación estructural básica del archivo de parámetros del púlsar."""
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
                return False, None, "El FITS no contiene una extensión HDU 1 con datos tabulares."
            columns = getattr(hdul[1], "columns", None)
            if columns is None or columns.names is None:
                return False, None, "La HDU 1 del FITS no contiene columnas tabulares."
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
    """Valida la tabla EVENTS y exige una extensión GTI utilizable para Sprint 3."""
    ok, columns, message = _get_hdu1_columns(path)
    if not ok or columns is None:
        return False, message

    missing = sorted(PHOTON_REQUIRED_COLUMNS - columns)
    if missing:
        return False, "Faltan columnas requeridas para eventos: " + ", ".join(missing)

    try:
        with fits.open(path, memmap=False) as hdul:
            gti_index = _find_hdu_index(hdul, "GTI")
            if gti_index is None:
                return False, "El FITS no contiene una extensión GTI requerida para la unificación final."
            gti_columns = getattr(hdul[gti_index], "columns", None)
            if gti_columns is None or gti_columns.names is None:
                return False, "La extensión GTI no contiene una tabla válida."
            gti_names = {str(name).upper() for name in gti_columns.names}
            missing_gti = sorted(GTI_REQUIRED_COLUMNS - gti_names)
            if missing_gti:
                return False, "La GTI no contiene las columnas: " + ", ".join(missing_gti)
    except Exception as exc:
        return False, f"No se pudo validar la GTI: {exc}"

    return True, "FITS de eventos y GTI válido."


def validate_spacecraft_fits(path: str | Path) -> tuple[bool, str]:
    """Validación estructural del archivo FT2/spacecraft."""
    ok, columns, message = _get_hdu1_columns(path)
    if not ok or columns is None:
        return False, message
    if not columns:
        return False, "El FITS de nave no contiene columnas en la HDU 1."
    return True, "FITS de nave legible."


def _time_metadata(header: fits.Header) -> dict[str, str]:
    return {
        key: str(header[key]).strip()
        for key in TIME_HEADER_KEYS
        if key in header and str(header[key]).strip()
    }


def _assert_time_metadata_compatible(paths: list[Path]) -> None:
    """Evita mezclar archivos que declaran sistemas temporales incompatibles."""
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
            if left is not None and right is not None and left != right:
                raise ValueError(
                    f"Metadatos temporales incompatibles: {key}={left!r} en "
                    f"{reference_name} y {key}={right!r} en {path.name}."
                )


def _read_events_and_gti(path: Path) -> tuple[Table, Table, fits.Header, fits.Header, str, str]:
    with fits.open(path, memmap=False) as hdul:
        gti_index = _find_hdu_index(hdul, "GTI")
        if gti_index is None:
            raise ValueError(f"{path.name}: no contiene extensión GTI.")

        event_table = Table(hdul[1].data)
        gti_table = Table(hdul[gti_index].data)
        return (
            event_table,
            gti_table,
            hdul[1].header.copy(),
            hdul[gti_index].header.copy(),
            hdul[1].name or "EVENTS",
            hdul[gti_index].name or "GTI",
        )


def merge_event_fits(
    paths: Iterable[str | Path],
    output_path: str | Path | None = None,
) -> Path:
    """Fusiona EVENTS y GTI preservando headers base y metadatos temporales.

    La función concatena las tablas EVENTS y GTI de todos los FITS compatibles,
    ordena los eventos por TIME y los intervalos GTI por START. También verifica
    que los metadatos temporales declarados no sean incompatibles.
    """
    file_paths = [Path(p) for p in paths]
    if not file_paths:
        raise ValueError("Se requiere al menos un archivo FITS de eventos.")

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
        events, gti, current_event_header, current_gti_header, current_event_name, current_gti_name = (
            _read_events_and_gti(path)
        )
        event_tables.append(events)
        gti_tables.append(gti)
        if index == 0:
            event_header = current_event_header
            gti_header = current_gti_header
            event_name = current_event_name
            gti_name = current_gti_name

    combined_events = vstack(event_tables, join_type="exact", metadata_conflicts="silent")
    combined_gti = vstack(gti_tables, join_type="exact", metadata_conflicts="silent")

    if "TIME" in combined_events.colnames:
        combined_events.sort("TIME")
    if "START" in combined_gti.colnames:
        combined_gti.sort("START")

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


def find_fermiphase_executable() -> str:
    """Localiza fermiphase sin depender exclusivamente del PATH.

    Primero intenta resolver el ejecutable mediante shutil.which(). Si no está
    visible en el PATH heredado por la aplicación, busca en la carpeta Scripts
    asociada al mismo intérprete de Python que está ejecutando PulsarGUI.
    """
    executable = shutil.which("fermiphase")
    if executable:
        return executable

    scripts_dir = Path(sysconfig.get_path("scripts"))
    candidates = [
        scripts_dir / "fermiphase.exe",
        scripts_dir / "fermiphase",
    ]

    for candidate in candidates:
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
    """Construye el comando PINT/fermiphase que agrega PULSE_PHASE.

    En Windows se evita modificar el FITS de entrada *in-place*. Si se entrega
    ``output_path`` se usa ``--outfile`` para que PINT abra el FITS de entrada en
    solo lectura y escriba el resultado en un archivo nuevo. Esto evita el
    PermissionError/WinError 32 que puede aparecer cuando Astropy necesita
    redimensionar una tabla FITS abierta en modo update para agregar PULSE_PHASE.

    Si se entrega un FT2, se pasa mediante --ft2 para registrar correctamente
    el observatorio satelital Fermi al procesar eventos FT1 crudos.
    """
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


def _read_par_parameter(path: str | Path, key: str) -> str | None:
    target = key.upper()
    with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[0].upper() == target:
                return parts[1]
    return None


def extract_radec_from_par(path: str | Path) -> tuple[float, float]:
    """Obtiene RA/DEC en grados desde RAJ/DECJ o RA/DEC de un archivo PAR."""
    raj = _read_par_parameter(path, "RAJ")
    decj = _read_par_parameter(path, "DECJ")
    if raj is not None and decj is not None:
        coord = SkyCoord(raj, decj, unit=(u.hourangle, u.deg), frame="icrs")
        return float(coord.ra.deg), float(coord.dec.deg)

    ra = _read_par_parameter(path, "RA")
    dec = _read_par_parameter(path, "DEC")
    if ra is not None and dec is not None:
        return float(ra), float(dec)

    raise ValueError(
        "No fue posible obtener RA/DEC desde el PAR. Se esperaba RAJ/DECJ o RA/DEC."
    )


def build_gtbary_command(
    fits_path: str | Path,
    spacecraft_path: str | Path,
    output_path: str | Path,
    ra_deg: float,
    dec_deg: float,
) -> list[str]:
    """Construye la llamada externa a FermiTools/gtbary."""
    return [
        "gtbary",
        str(fits_path),
        str(spacecraft_path),
        str(output_path),
        f"{ra_deg:.10f}",
        f"{dec_deg:.10f}",
    ]


def has_column(path: str | Path, column_name: str) -> bool:
    ok, columns, _ = _get_hdu1_columns(path)
    return bool(ok and columns and column_name.upper() in columns)


def prepare_phase_output(source: str | Path) -> Path:
    """Crea una copia derivada para que fermiphase no modifique el FITS base."""
    source_path = Path(source)
    output = source_path.with_name(f"{source_path.stem}_con_fase{source_path.suffix}")
    shutil.copy2(source_path, output)
    return output


class ExternalCommandWorker(QThread):
    """Ejecuta un proceso externo sin bloquear la GUI y con espera acotada.

    Medidas de seguridad de concurrencia:
    - un único proceso externo por worker;
    - comunicación con la GUI exclusivamente mediante señales;
    - communicate() drena stdout/stderr y evita bloqueos por pipes llenos;
    - timeout finito con kill del proceso externo;
    - cancelación cooperativa sin esperar indefinidamente al hilo desde la GUI.
    """

    completed = pyqtSignal(str, bool, str)

    def __init__(self, operation: str, command: list[str], timeout_s: int = EXTERNAL_PROCESS_TIMEOUT_S):
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
                    f"La operación superó el tiempo máximo de {self.timeout_s} s y fue detenida.",
                )
                return

            if self.isInterruptionRequested():
                self.completed.emit(self.operation, False, "Operación cancelada por el usuario.")
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


class PulsarGUISprint3(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PulsarGUI - Sprint 3")
        self.resize(760, 760)

        self.files: dict[str, str | list[str] | None] = {
            "par": None,
            "spacecraft": None,
            "photons": [],
        }
        self.processing_fits: str | None = None
        self.phase_fits: str | None = None
        self.worker: ExternalCommandWorker | None = None
        self.pending_external_output: Path | None = None

        self.build_ui()
        self.update_button_states()

    def build_ui(self) -> None:
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

        title = QLabel("PulsarGUI — Sprint 3 / Incremento final")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel(
            "Validación, unificación EVENTS+GTI, visualización RA–DEC, baricentrado opcional "
            "con FermiTools, cálculo de fase con PINT y generación de faseograma/perfil de pulso."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        file_buttons = QHBoxLayout()

        self.par_button = QPushButton("📄 Cargar PAR")
        self.par_button.clicked.connect(self.load_par)
        file_buttons.addWidget(self.par_button)

        self.spacecraft_button = QPushButton("🛰️ Cargar FT2")
        self.spacecraft_button.clicked.connect(self.load_spacecraft)
        file_buttons.addWidget(self.spacecraft_button)

        self.photons_button = QPushButton("✨ Cargar FITS Fotones")
        self.photons_button.clicked.connect(self.load_photons)
        file_buttons.addWidget(self.photons_button)

        layout.addLayout(file_buttons)

        self.file_list = QListWidget()
        layout.addWidget(self.file_list)

        self.merge_button = QPushButton("🚀 Unificar EVENTS + GTI")
        self.merge_button.setStyleSheet("background-color: #f72585; color: white;")
        self.merge_button.clicked.connect(self.process_photons)
        layout.addWidget(self.merge_button)

        self.histogram_button = QPushButton("🌌 Generar Histograma 2D RA–DEC")
        self.histogram_button.setStyleSheet("background-color: #2ecc71; color: white;")
        self.histogram_button.clicked.connect(self.plot_histogram)
        layout.addWidget(self.histogram_button)

        self.bary_button = QPushButton("🛰️ Baricentrar con gtbary (FermiTools)")
        self.bary_button.setStyleSheet("background-color: #8e44ad; color: white;")
        self.bary_button.clicked.connect(self.start_barycenter)
        layout.addWidget(self.bary_button)

        self.phase_button = QPushButton("⏱️ Calcular PULSE_PHASE con PINT")
        self.phase_button.setStyleSheet("background-color: #f39c12; color: white;")
        self.phase_button.clicked.connect(self.start_phase_calculation)
        layout.addWidget(self.phase_button)

        self.profile_button = QPushButton("📊 Faseograma + Perfil de Pulso")
        self.profile_button.setStyleSheet("background-color: #16a085; color: white;")
        self.profile_button.clicked.connect(self.plot_phaseogram_and_profile)
        layout.addWidget(self.profile_button)

        self.cancel_button = QPushButton("⛔ Cancelar proceso externo")
        self.cancel_button.setStyleSheet("background-color: #c0392b; color: white;")
        self.cancel_button.clicked.connect(self.cancel_external_process)
        layout.addWidget(self.cancel_button)

        self.status_label = QLabel("Estado: esperando archivos.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        note = QLabel(
            "Concurrencia Sprint 3: la GUI no espera indefinidamente al worker. Los procesos "
            "externos usan timeout, cancelación y señales. Para eventos Fermi crudos, "
            "fermiphase utiliza el FT2 cargado mediante --ft2. gtbary queda como "
            "preprocesamiento opcional si FermiTools está instalado."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.setLayout(layout)

    def show_message(self, title: str, text: str, error: bool = False) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Critical if error else QMessageBox.Icon.Information)
        box.exec()

    def refresh_file_list(self) -> None:
        self.file_list.clear()

        par = self.files["par"]
        spacecraft = self.files["spacecraft"]
        photons = self.files["photons"]

        if isinstance(par, str):
            self.file_list.addItem("📄 PAR: " + os.path.basename(par))
        if isinstance(spacecraft, str):
            self.file_list.addItem("🛰️ FT2: " + os.path.basename(spacecraft))
        if isinstance(photons, list):
            for path in photons:
                self.file_list.addItem("✨ PH FITS: " + os.path.basename(path))
        if self.processing_fits:
            self.file_list.addItem("✅ FITS de procesamiento: " + os.path.basename(self.processing_fits))
        if self.phase_fits:
            self.file_list.addItem("📈 FITS con PULSE_PHASE: " + os.path.basename(self.phase_fits))

    def process_running(self) -> bool:
        return bool(self.worker is not None and self.worker.isRunning())

    def update_button_states(self) -> None:
        photons = self.files["photons"]
        has_photons = isinstance(photons, list) and len(photons) > 0
        has_processing = self.processing_fits is not None
        has_par = isinstance(self.files["par"], str)
        has_spacecraft = isinstance(self.files["spacecraft"], str)
        running = self.process_running()

        self.par_button.setEnabled(not running)
        self.spacecraft_button.setEnabled(not running)
        self.photons_button.setEnabled(not running)
        self.merge_button.setEnabled(has_photons and not running)
        self.histogram_button.setEnabled(has_processing and not running)
        self.bary_button.setEnabled(has_processing and has_par and has_spacecraft and not running)
        self.phase_button.setEnabled(has_processing and has_par and not running)
        self.profile_button.setEnabled(self.phase_fits is not None and not running)
        self.cancel_button.setEnabled(running)

    def invalidate_derived_outputs(self) -> None:
        self.processing_fits = None
        self.phase_fits = None
        self.pending_external_output = None

    def load_par(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo PAR", "", "PAR files (*.par)")
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
            "Seleccionar FITS de nave/FT2",
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
            self.show_message("Algunos FITS fueron rechazados", "\n".join(errors), error=True)

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
        self.status_label.setText("Estado: EVENTS y GTI unificados correctamente.")
        self.refresh_file_list()
        self.update_button_states()
        self.show_message(
            "Unificación completada",
            "Se creó un FITS consolidado con EVENTS y GTI en:\n" + self.processing_fits,
        )

    def plot_histogram(self) -> None:
        if not self.processing_fits:
            return

        try:
            with fits.open(self.processing_fits, memmap=False) as hdul:
                data = Table(hdul[1].data)

            fig = plt.figure(figsize=(7, 7))
            ax = fig.add_subplot(111)
            ax.set_title("Histograma 2D Espacial (RA–DEC)", fontsize=14)
            ax.set_xlabel("Ascensión Recta (RA)")
            ax.set_ylabel("Declinación (DEC)")
            image = ax.hist2d(data["RA"], data["DEC"], bins=(200, 200), cmin=1, cmap="viridis")
            fig.colorbar(image[3], ax=ax, label="Número de eventos")
            fig.tight_layout()
            plt.show()
        except Exception as exc:
            self.show_message("Error de visualización", f"No fue posible generar el histograma:\n{exc}", error=True)

    def _start_external_worker(self, operation: str, command: list[str], output: Path | None = None) -> None:
        if self.process_running():
            self.show_message("Proceso en curso", "Ya existe un proceso externo ejecutándose.", error=True)
            return

        self.pending_external_output = output
        self.worker = ExternalCommandWorker(operation, command)
        self.worker.completed.connect(self.finish_external_operation)
        self.worker.finished.connect(self._worker_finished)
        self.status_label.setText(f"Estado: ejecutando {operation}...")
        self.worker.start()
        self.update_button_states()

    def start_barycenter(self) -> None:
        if not self.processing_fits:
            return

        par = self.files["par"]
        spacecraft = self.files["spacecraft"]
        if not isinstance(par, str) or not isinstance(spacecraft, str):
            return

        try:
            ra_deg, dec_deg = extract_radec_from_par(par)
        except Exception as exc:
            self.show_message("No se pudo obtener RA/DEC", str(exc), error=True)
            return

        source = Path(self.processing_fits)
        output = source.with_name(f"{source.stem}_baricentrado{source.suffix}")
        command = build_gtbary_command(source, spacecraft, output, ra_deg, dec_deg)
        self._start_external_worker("gtbary", command, output)

    def start_phase_calculation(self) -> None:
        if not self.processing_fits:
            return

        par = self.files["par"]
        spacecraft = self.files["spacecraft"]

        if not isinstance(par, str):
            return

        # FT2 es opcional para archivos ya geocentrados/baricentrados, pero para
        # eventos Fermi FT1 crudos PINT lo necesita. Si el usuario lo cargó,
        # siempre se lo entregamos a fermiphase mediante --ft2.
        ft2_path = spacecraft if isinstance(spacecraft, str) else None

        try:
            # No copiamos el FITS para que fermiphase lo modifique en modo update.
            # En Windows esa operación puede fallar con WinError 32 al agregar una
            # nueva columna porque Astropy necesita redimensionar el archivo.
            # Usamos un directorio temporal nuevo y --outfile, de modo que PINT
            # lea el FITS consolidado y escriba PULSE_PHASE en un archivo distinto.
            source = Path(self.processing_fits)
            phase_dir = Path(tempfile.mkdtemp(prefix="pulsargui_phase_"))
            output = phase_dir / f"{source.stem}_con_fase{source.suffix}"

            command = build_fermiphase_command(
                source,
                par,
                ft2_path=ft2_path,
                output_path=output,
            )
        except Exception as exc:
            self.show_message(
                "Error preparando cálculo de fase",
                str(exc),
                error=True,
            )
            return

        self._start_external_worker("fermiphase", command, output)

    def finish_external_operation(self, operation: str, success: bool, message: str) -> None:
        output = self.pending_external_output

        if success and operation == "gtbary":
            if output is None or not output.exists():
                success = False
                message = "gtbary terminó sin error, pero no se encontró el archivo de salida."
            else:
                self.processing_fits = str(output)
                self.phase_fits = None
                message = "Baricentrado completado.\n" + str(output)

        elif success and operation == "fermiphase":
            if output is None or not output.exists():
                success = False
                message = "fermiphase terminó sin error, pero no se encontró el archivo procesado."
            elif not has_column(output, "PULSE_PHASE"):
                success = False
                message = "fermiphase terminó, pero no se detectó PULSE_PHASE en EVENTS."
            else:
                self.phase_fits = str(output)
                message = "Cálculo de fases completado. PULSE_PHASE está disponible."

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
            self.status_label.setText("Estado: cancelando proceso externo...")
            self.worker.cancel()

    def plot_phaseogram_and_profile(self) -> None:
        if not self.phase_fits:
            return

        try:
            with fits.open(self.phase_fits, memmap=False) as hdul:
                data = Table(hdul[1].data)

            if "PULSE_PHASE" not in data.colnames or "TIME" not in data.colnames:
                raise ValueError("El FITS no contiene TIME y PULSE_PHASE.")

            phases = np.asarray(data["PULSE_PHASE"], dtype=float) % 1.0
            times = np.asarray(data["TIME"], dtype=float)
            mask = np.isfinite(phases) & np.isfinite(times)
            phases = phases[mask]
            times = times[mask]

            if phases.size == 0:
                raise ValueError("No existen fases válidas para visualizar.")

            fig = plt.figure(figsize=(9, 8))
            grid = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.08)
            ax_phase = fig.add_subplot(grid[0])
            ax_profile = fig.add_subplot(grid[1], sharex=ax_phase)

            ax_phase.scatter(phases, times, s=1)
            ax_phase.set_title("Faseograma y Perfil de Pulso")
            ax_phase.set_ylabel("Tiempo / Fermi MET (s)")
            ax_phase.set_xlim(0.0, 1.0)
            ax_phase.grid(True, alpha=0.3)
            ax_phase.tick_params(axis="x", labelbottom=False)

            ax_profile.hist(phases, bins=50, histtype="step")
            ax_profile.set_xlabel("Fase de Pulso")
            ax_profile.set_ylabel("Eventos")
            ax_profile.set_xlim(0.0, 1.0)
            ax_profile.grid(True, alpha=0.3)

            fig.tight_layout()
            plt.show()
        except Exception as exc:
            self.show_message(
                "Error de visualización temporal",
                f"No fue posible generar faseograma/perfil:\n{exc}",
                error=True,
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        """Cierre acotado: nunca espera indefinidamente por el worker."""
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            # Espera finita solo durante el cierre; evita un wait() indefinido.
            if not self.worker.wait(2000):
                event.ignore()
                self.show_message(
                    "Proceso aún cerrándose",
                    "Se solicitó detener el proceso externo. Intenta cerrar nuevamente en unos segundos.",
                    error=True,
                )
                return
        event.accept()


def graphical_interface() -> None:
    app = QApplication(sys.argv)
    window = PulsarGUISprint3()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    graphical_interface()
