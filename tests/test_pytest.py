from pathlib import Path
import pytest
from astropy.io import fits
from astropy.table import Table

from PulsarGUI.Pulsargui import (
    _find_hdu_index,
    find_fermiphase_executable,
    build_fermiphase_command,
)


def crear_fits_prueba(ruta: Path, con_gti: bool = True, con_events: bool = True) -> Path:
    """Helper para generar un archivo FITS sintético de prueba."""
    hdus = [fits.PrimaryHDU()]

    if con_events:
        tabla_events = Table({
            "TIME": [100.0, 101.0, 102.0],
            "RA": [45.0, 45.1, 45.2],
            "DEC": [-12.0, -12.1, -12.2],
            "ENERGY": [1000.0, 1200.0, 1100.0]
        })
        hdus.append(fits.BinTableHDU(tabla_events, name="EVENTS"))

    if con_gti:
        tabla_gti = Table({
            "START": [100.0],
            "STOP": [110.0]
        })
        hdus.append(fits.BinTableHDU(tabla_gti, name="GTI"))

    hdul = fits.HDUList(hdus)
    hdul.writeto(ruta, overwrite=True)
    return ruta


# **Pruebas para _find_hdu_index**

def test_find_hdu_index_exitoso():
    hdus = fits.HDUList([
        fits.PrimaryHDU(),
        fits.BinTableHDU(name="EVENTS"),
        fits.BinTableHDU(name="GTI")
    ])
    
    assert _find_hdu_index(hdus, "EVENTS") == 1
    assert _find_hdu_index(hdus, "events") == 1  # Insensible a mayúsculas
    assert _find_hdu_index(hdus, "GTI") == 2


def test_find_hdu_index_no_encontrado():
    hdus = fits.HDUList([fits.PrimaryHDU()])
    assert _find_hdu_index(hdus, "EVENTS") is None


# **Pruebas para find_fermiphase_executable**

def test_find_fermiphase_executable_encontrado(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/fermiphase")
    assert find_fermiphase_executable() == "/usr/local/bin/fermiphase"


def test_find_fermiphase_executable_fallback(monkeypatch):
    # Simula que no existe en el PATH del sistema
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    
    # Simula que tampoco existe dentro de la carpeta Scripts de Python
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)

    # Verifica que la función lance FileNotFoundError cuando no encuentra el ejecutable
    with pytest.raises(FileNotFoundError):
        find_fermiphase_executable()


# **Pruebas para build_fermiphase_command**

def test_build_fermiphase_command_basico(monkeypatch):
    monkeypatch.setattr("PulsarGUI.Pulsargui.find_fermiphase_executable", lambda: "fermiphase")

    cmd = build_fermiphase_command(
        fits_path="evento.fits",
        par_path="pulsar.par"
    )

    assert cmd == [
        "fermiphase",
        "evento.fits",
        "pulsar.par",
        "CALC",
        "--addphase"
    ]


def test_build_fermiphase_command_opciones_completas(monkeypatch):
    monkeypatch.setattr("PulsarGUI.Pulsargui.find_fermiphase_executable", lambda: "fermiphase")
    
    cmd = build_fermiphase_command(
        fits_path="evento.fits",
        par_path="pulsar.par",
        ft2_path="ft2.fits",
        output_path="salida.fits"
    )
    
    # Valida el uso de --outfile y la ausencia de --addphase cuando hay archivo de salida
    assert cmd == [
        "fermiphase",
        "evento.fits",
        "pulsar.par",
        "CALC",
        "--ft2",
        "ft2.fits",
        "--outfile",
        "salida.fits",
    ]


# **Pruebas de archivos FITS (Usando tmp_path)**

def test_estructura_fits_valido(tmp_path):
    fits_path = tmp_path / "test_valido.fits"
    crear_fits_prueba(fits_path, con_gti=True, con_events=True)

    with fits.open(fits_path) as hdul:
        assert _find_hdu_index(hdul, "EVENTS") is not None
        assert _find_hdu_index(hdul, "GTI") is not None


def test_estructura_fits_sin_gti(tmp_path):
    fits_path = tmp_path / "test_invalido.fits"
    crear_fits_prueba(fits_path, con_gti=False, con_events=True)

    with fits.open(fits_path) as hdul:
        assert _find_hdu_index(hdul, "EVENTS") is not None
        assert _find_hdu_index(hdul, "GTI") is None