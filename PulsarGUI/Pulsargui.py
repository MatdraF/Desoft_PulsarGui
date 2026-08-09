import sys
import os
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QListWidget, QFileDialog, QMessageBox)
from PyQt5.QtGui import QIcon, QFont
from astropy.io import fits

class Validador(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('✨ Carga de Archivos - Sprint 1 ✨')
        self.resize(600, 450)
        
        # Guardamos las rutas de los archivos acá para tener todo centralizado
        # 'ph' es una lista porque los eventos de fotones suelen venir en varios archivos separados
        self.f = {
            'par': None,
            'sc': None,
            'ph': [] 
        }
        
        self.ui()

    def ui(self):
        # Le damos un poco de estilo oscuro a la interfaz para que no rompa los ojos
        self.setStyleSheet('''
            QWidget { background-color: #1a1a2e; color: #e2f3f5; font-family: Arial; }
            QPushButton {
                background-color: #4cc9f0; color: #16213e;
                padding: 10px; font-weight: bold; border-radius: 5px;
            }
            QPushButton:hover { background-color: #6bd6ff; }
            QListWidget { background-color: rgba(22, 33, 62, 0.7); border: 2px solid #4cc9f0; }
        ''')

        # Layout principal vertical y uno secundario horizontal para alinear los botones
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

        # Lista visual para que el usuario vea fácilmente qué archivos ya subió
        self.lista = QListWidget()
        lay.addWidget(self.lista)

        self.setLayout(lay)

    def msg(self, tit, txt):
        # Ventana emergente genérica para avisar errores de carga al usuario
        m = QMessageBox(self)
        m.setWindowTitle(tit)
        m.setText(txt)
        m.setStyleSheet('QMessageBox { background-color: #1a1a2e; color: #e2f3f5; }')
        m.exec_()

    def act_lista(self):
        # Limpiamos y volvemos a llenar la lista visual cada vez que se carga algo nuevo
        self.lista.clear()
        p = self.f['par']
        sc = self.f['sc']
        ph = self.f['ph']
        
        if p: self.lista.addItem('📄 PAR: ' + os.path.basename(p))
        if sc: self.lista.addItem('🛰️ SC FITS: ' + os.path.basename(sc))
        for x in ph: self.lista.addItem('✨ PH FITS: ' + os.path.basename(x))

    def cargar(self, t):
        # Lógica central para abrir el explorador según el botón presionado
        if t == 'par':
            r, _ = QFileDialog.getOpenFileName(self, 'Seleccionar PAR', '', 'PAR files (*.par)')
            if r: self.f['par'] = r
                
        elif t == 'sc':
            r, _ = QFileDialog.getOpenFileName(self, 'Seleccionar FITS Nave', '', 'FITS files (*.fits *.fit)')
            if r:
                try:
                    # Abrimos el FITS y validamos los headers para asegurar que sea de la nave
                    with fits.open(r) as h:
                        cols = h[1].columns.names
                        nom = os.path.basename(r).upper()
                        # La columna SC_POS nos confirma que el archivo tiene la posición espacial
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
                    # Repetimos la validación, pero ahora buscando energía de fotones
                    with fits.open(r) as h:
                        cols = h[1].columns.names
                        nom = os.path.basename(r).upper()
                        if 'ENERGY' in cols or 'PH' in nom:
                            # Evitamos cargar el mismo archivo dos veces en la lista
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

