# %%
import sys
import os
import tempfile  

from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QListWidget, QFileDialog, QMessageBox)
from PyQt5.QtGui import QIcon, QFont

from astropy.io import fits
from astropy.table import Table, vstack 
 
class Validador(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('✨ Carga de Archivos - Sprint 1 ✨')
        self.resize(600, 500)
        
        self.f = {
            'par': None,
            'sc': None,
            'ph': [] 
        }
        
        self.ui()

    def ui(self):
        self.setStyleSheet('''
            QWidget { background-color: #1a1a2e; color: #e2f3f5; font-family: Arial; }
            QPushButton {
                background-color: #4cc9f0; color: #16213e;
                padding: 10px; font-weight: bold; border-radius: 5px;
            }
            QPushButton:hover { background-color: #6bd6ff; }
            QListWidget { background-color: rgba(22, 33, 62, 0.7); border: 2px solid #4cc9f0; }
        ''')

        lay = QVBoxLayout()
        
        tit = QLabel('📤 Cargar Archivos Manualmente')
        tit.setFont(QFont('Arial', 16, QFont.Bold))
        lay.addWidget(tit)

        lay_b = QHBoxLayout()
        
        self.b_par = QPushButton('📄 Cargar PAR')
        self.b_par.clicked.connect(lambda: self.cargar('par'))
        lay_b.addWidget(self.b_par)

        self.b_sc = QPushButton('🛰️ Cargar FITS (Nave)')
        self.b_sc.clicked.connect(lambda: self.cargar('sc'))
        lay_b.addWidget(self.b_sc)

        self.b_ph = QPushButton('✨ Cargar FITS (Fotones)')
        self.b_ph.clicked.connect(lambda: self.cargar('ph'))
        lay_b.addWidget(self.b_ph)

        lay.addLayout(lay_b)

        self.lista = QListWidget()
        lay.addWidget(self.lista)

        # --- PASO 1: EL BOTÓN DE ACCIÓN ---
        self.b_procesar = QPushButton('🚀 Unificar Fotones')
        self.b_procesar.setStyleSheet("background-color: #f72585; color: white;") 
        self.b_procesar.clicked.connect(self.procesar_datos) 
        lay.addWidget(self.b_procesar)

        self.setLayout(lay)

    # --- PASO 2: LA FUNCIÓN DE CONTROL (EL GATILLO) ---
    def procesar_datos(self):
        """Revisa que estén los datos antes de operar y llama a la unificación"""
        if len(self.f['ph']) == 0:
            self.msg('Aviso', 'No hay archivos de fotones en la lista para unificar.')
            return
            
        # se llama a la función matemática y guarda el resultado
        ruta_unificada = self.unificar_archivos_fits(self.f['ph'])
        
        if ruta_unificada:
            self.msg('Éxito', f'¡Archivos unificados correctamente!\nGuardado temporalmente en:\n{ruta_unificada}')
        else:
            self.msg('Error', 'Ocurrió un problema al unificar los archivos FITS.')

    # --- PASO 3: LA LÓGICA MATEMÁTICA CON ASTROPY ---
    def unificar_archivos_fits(self, lista_rutas_fits):
        """Apila los eventos de múltiples FITS en una sola tabla usando vstack"""
        if len(lista_rutas_fits) == 1:
            return lista_rutas_fits[0]
        
        try:
            tablas = []
            # se extrae la data espacial y energética (hdu=1) de cada FITS
            for ruta in lista_rutas_fits:
                tabla_individual = Table.read(ruta, hdu=1)
                tablas.append(tabla_individual)
            
            # se apila verticalmente
            tabla_combinada = vstack(tablas)
            
            # se genera el archivo en una carpeta temporal segura
            directorio_temp = tempfile.mkdtemp(prefix="pulsar_")
            ruta_final = os.path.join(directorio_temp, "eventos_unificados.fits")
            
            # se exporta el resultado
            tabla_combinada.write(ruta_final, format='fits', overwrite=True)
            
            return ruta_final
            
        except Exception as e:
            print(f"Error interno de Astropy: {str(e)}")
            return None

    def msg(self, tit, txt):
        m = QMessageBox(self)
        m.setWindowTitle(tit)
        m.setText(txt)
        m.setStyleSheet('QMessageBox { background-color: #1a1a2e; color: #e2f3f5; }')
        m.exec_()

    def act_lista(self):
        self.lista.clear()
        p = self.f['par']
        sc = self.f['sc']
        ph = self.f['ph']
        
        if p: self.lista.addItem('📄 PAR: ' + os.path.basename(p))
        if sc: self.lista.addItem('🛰️ SC FITS: ' + os.path.basename(sc))
        for x in ph: self.lista.addItem('✨ PH FITS: ' + os.path.basename(x))

    def cargar(self, t):
        if t == 'par':
            r, _ = QFileDialog.getOpenFileName(self, 'Seleccionar PAR', '', 'PAR files (*.par)')
            if r: self.f['par'] = r
                
        elif t == 'sc':
            r, _ = QFileDialog.getOpenFileName(self, 'Seleccionar FITS Nave', '', 'FITS files (*.fits *.fit)')
            if r:
                try:
                    with fits.open(r) as h:
                        cols = h[1].columns.names
                        nom = os.path.basename(r).upper()
                        if 'SC_POS' in cols or 'SC' in nom:
                            self.f['sc'] = r
                        else:
                            self.msg('Error', 'No parece un archivo Spacecraft válido.')
                except Exception as e:
                    self.msg('Error', 'Fallo al leer FITS: ' + str(e))

        elif t == 'ph':
            rs, _ = QFileDialog.getOpenFileNames(self, 'Seleccionar FITS Fotones', '', 'FITS files (*.fits *.fit)')
            for r in rs:
                try:
                    with fits.open(r) as h:
                        cols = h[1].columns.names
                        nom = os.path.basename(r).upper()
                        if 'ENERGY' in cols or 'PH' in nom:
                            if r not in self.f['ph']:
                                self.f['ph'].append(r)
                        else:
                            self.msg('Error', 'Este archivo no contiene datos de fotones: ' + nom)
                except Exception as e:
                    self.msg('Error', 'Fallo al leer: ' + str(e))
                    
        self.act_lista()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ven = Validador()
    ven.show()
    sys.exit(app.exec_())