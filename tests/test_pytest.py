from pathlib import Path

import pytest
from astropy.io import fits
from astropy.table import Table

from PulsarGUI.Pulsargui import (
    PHOTON_REQUIRED_COLUMNS,
    build_fermiphase_command,
    has_column,
    merge_event_fits,
    validate_par_file,
    validate_photon_fits,
)


def crear_fits_eventos(ruta: Path, filas: int = 3, incluir_energy: bool = True):
    """Crea un FITS pequeño y controlado para las pruebas, incluyendo la extensión GTI."""
    data = {
        "TIME": [float(i) for i in range(filas)],
        "RA": [80.0 + i for i in range(filas)],
        "DEC": [20.0 + i for i in range(filas)],
    }

    if incluir_energy:
        data["ENERGY"] = [1000.0 + i for i in range(filas)]

    tabla = Table(data)

    primary_hdu = fits.PrimaryHDU()
    events_hdu = fits.BinTableHDU(tabla, name="EVENTS")
    
    # Crear extensión GTI requerida para la validación
    gti_tabla = Table({"START": [0.0], "STOP": [10.0]})
    gti_hdu = fits.BinTableHDU(gti_tabla, name="GTI")

    fits.HDUList([primary_hdu, events_hdu, gti_hdu]).writeto(ruta, overwrite=True)
    
def test_par_valido(tmp_path):
    par = tmp_path / "pulsar.par"
    par.write_text("PSR J1234+5678\nF0 1.0\n", encoding="utf-8")

    ok, mensaje = validate_par_file(par)

    assert ok is True
    assert "válido" in mensaje.lower()


def test_par_vacio_es_rechazado(tmp_path):
    par = tmp_path / "vacio.par"
    par.write_text("", encoding="utf-8")

    ok, mensaje = validate_par_file(par)

    assert ok is False
    assert "vacío" in mensaje.lower()


def test_fits_fotones_valido(tmp_path):
    archivo = tmp_path / "fotones.fits"
    crear_fits_eventos(archivo)

    ok, mensaje = validate_photon_fits(archivo)

    assert ok is True
    assert "válido" in mensaje.lower()


def test_fits_sin_energy_es_rechazado(tmp_path):
    archivo = tmp_path / "sin_energy.fits"
    crear_fits_eventos(archivo, incluir_energy=False)

    ok, mensaje = validate_photon_fits(archivo)

    assert ok is False
    assert "ENERGY" in mensaje


def test_unificacion_de_dos_fits(tmp_path):
    fits_1 = tmp_path / "eventos_1.fits"
    fits_2 = tmp_path / "eventos_2.fits"
    salida = tmp_path / "unificado.fits"

    crear_fits_eventos(fits_1, filas=2)
    crear_fits_eventos(fits_2, filas=3)

    resultado = merge_event_fits([fits_1, fits_2], salida)

    assert resultado.exists()

    tabla = Table.read(resultado, hdu=1)

    assert len(tabla) == 5
    assert PHOTON_REQUIRED_COLUMNS.issubset(
        {str(nombre).upper() for nombre in tabla.colnames}
    )


def test_comando_fermiphase(monkeypatch):
    # Simular la presencia del ejecutable para evitar FileNotFoundError si no está instalado
    monkeypatch.setattr("PulsarGUI.Pulsargui.find_fermiphase_executable", lambda: "fermiphase")
    
    comando = build_fermiphase_command("eventos.fits", "pulsar.par")

    assert comando == [
        "fermiphase",
        "eventos.fits",
        "pulsar.par",
        "CALC",
        "--addphase",
    ]
    
def test_has_column(tmp_path):
    archivo = tmp_path / "fotones.fits"
    crear_fits_eventos(archivo)

    assert has_column(archivo, "RA") is True
    assert has_column(archivo, "PULSE_PHASE") is False
