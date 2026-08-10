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

class PhaseWorker(QThread):
    """Ejecuta fermiphase sin bloquear la interfaz.

    El uso del hilo es inicial: la optimización completa del rendimiento queda
    como trabajo de Sprint 3.
    """

    finished_with_status = pyqtSignal(bool, str)

    def __init__(self, par_file: str, fits_file: str):
        super().__init__()
        self.par_file = par_file
        self.fits_file = fits_file

    def run(self):
        command = build_fermiphase_command(self.fits_file, self.par_file)

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            self.finished_with_status.emit(
                False,
                "No se encontró el comando 'fermiphase'. Verifica que pint-pulsar "
                "esté instalado y disponible en el entorno de Python.",
            )
            return
        except Exception as exc:
            self.finished_with_status.emit(False, f"Error al ejecutar fermiphase: {exc}")
            return

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Sin detalle adicional").strip()
            self.finished_with_status.emit(False, f"fermiphase terminó con error:\n{detail}")
            return

        if has_column(self.fits_file, "PULSE_PHASE"):
            self.finished_with_status.emit(
                True,
                "Cálculo de fases completado. La columna PULSE_PHASE está disponible.",
            )
        else:
            self.finished_with_status.emit(
                True,
                "fermiphase terminó correctamente, pero no se detectó PULSE_PHASE en la HDU 1. "
                "Revise el archivo antes de continuar.",
            )

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

        self.merge_button = QPushButton("🚀 Unificar Fotones")
        self.merge_button.setStyleSheet("background-color: #f72585; color: white;")
        self.merge_button.clicked.connect(self.process_photons)
        layout.addWidget(self.merge_button)

        self.histogram_button = QPushButton("🌌 Generar Histograma 2D RA–DEC")
        self.histogram_button.setStyleSheet("background-color: #2ecc71; color: white;")
        self.histogram_button.clicked.connect(self.plot_histogram)
        layout.addWidget(self.histogram_button)

        self.phase_button = QPushButton("⏱️ Calcular fases con PINT")
        self.phase_button.setStyleSheet("background-color: #f39c12; color: white;")
        self.phase_button.clicked.connect(self.start_phase_calculation)
        layout.addWidget(self.phase_button)

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


