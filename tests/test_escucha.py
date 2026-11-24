"""La escucha de Windows: Ctrl + clic y lo nuevo de mantener presionado 1 segundo (para LockDown Browser).

En Mac la clase se cambia por la de Quartz (Option + clic) al importar el modulo; para probar la logica de
Windows (que es la que comparte el clic sostenido) se ejecuta el archivo de nuevo, como si fuera Windows.
"""

import importlib.util
import os
import sys
import time

_APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _APP)

_real = sys.platform
_viejo = sys.modules.pop("clw.escucha", None)
try:
    sys.platform = "win32"
    _spec = importlib.util.spec_from_file_location("clw.escucha", os.path.join(_APP, "clw", "escucha.py"))
    E = importlib.util.module_from_spec(_spec)
    sys.modules["clw.escucha"] = E
    _spec.loader.exec_module(E)
finally:
    sys.platform = _real
    if _viejo is not None:
        sys.modules["clw.escucha"] = _viejo

VK_LBUTTON, VK_CONTROL = 0x01, 0x11


class EntradaFalsa:
    VK_CONTROL = 0x11

    def __init__(self):
        self.teclas = {VK_LBUTTON: False, VK_CONTROL: False}
        self.pos = (100, 200)
        self.juego = False
        self.forma = "texto"

    def tecla_abajo(self, vk):
        return self.teclas.get(vk, False)

    def boton_izquierdo(self):
        return VK_LBUTTON

    def posicion_mouse(self):
        return self.pos

    def juego_en_pantalla_completa(self):
        return self.juego

    def forma_cursor(self):
        return self.forma

    def bajar_prioridad_hilo(self):
        pass


def _escucha(disparos):
    ent = EntradaFalsa()
    antes, E.entrada = E.entrada, ent
    es = E.EscuchaCtrlClic(lambda x, y: disparos.append((x, y)), intervalo=0.004)
    return es, ent, antes


def _terminar(es, antes):
    es.detener()
    E.entrada = antes


def prueba_mantener_presionado_1_segundo_dispara():
    disparos = []
    es, ent, antes = _escucha(disparos)
    try:
        es.iniciar()
        time.sleep(0.05)
        ent.teclas[VK_LBUTTON] = True               # presiona sobre la pregunta
        t0 = time.time()
        while time.time() - t0 < 1.5 and not disparos:
            time.sleep(0.01)
        ent.teclas[VK_LBUTTON] = False               # suelta
        time.sleep(0.05)
        assert disparos == [(100, 200)], disparos
    finally:
        _terminar(es, antes)


def prueba_mantener_menos_de_1_segundo_no_dispara():
    disparos = []
    es, ent, antes = _escucha(disparos)
    try:
        es.iniciar()
        time.sleep(0.05)
        ent.teclas[VK_LBUTTON] = True
        time.sleep(0.5)                             # lo suelta antes del segundo
        ent.teclas[VK_LBUTTON] = False
        time.sleep(0.3)
        assert disparos == [], disparos
    finally:
        _terminar(es, antes)


def prueba_mantener_presionado_moviendo_el_mouse_no_dispara():
    disparos = []
    es, ent, antes = _escucha(disparos)
    try:
        es.iniciar()
        time.sleep(0.05)
        ent.teclas[VK_LBUTTON] = True
        time.sleep(0.5)
        ent.pos = (160, 260)                        # se movio: es un arrastre, no cuenta
        time.sleep(0.7)
        ent.teclas[VK_LBUTTON] = False
        time.sleep(0.3)
        assert disparos == [], disparos
    finally:
        _terminar(es, antes)


def prueba_mantener_presionado_sobre_un_boton_no_dispara():
    """(El filtro de cursor de texto ya no se usa: sobra fiabilidad en LockDown Browser; quedo el test
    del clic corto en la autoprueba.)"""
    disparos = []
    es, ent, antes = _escucha(disparos)
    try:
        es.iniciar()
        time.sleep(0.05)
        ent.forma = "flecha"                        # el cursor sobre un boton (no texto)
        ent.teclas[VK_LBUTTON] = True
        time.sleep(1.4)                             # mantener presionado un boton: dispare igual
        ent.teclas[VK_LBUTTON] = False
        time.sleep(0.3)
        assert disparos == [(100, 200)], disparos   # el disparo ya no depende del cursor
    finally:
        _terminar(es, antes)


def prueba_ctrl_ya_no_dispara_solo_el_clic_sostenido():
    """El Ctrl + clic se quito por completo (LockDown Browser lo bloquea): presionar Ctrl y dar clic
    rapido ya no dispara nada; solo el clic sostenido de 1 segundo."""
    disparos = []
    es, ent, antes = _escucha(disparos)
    try:
        es.iniciar()
        time.sleep(0.05)
        ent.teclas[VK_CONTROL] = True
        time.sleep(0.03)
        ent.teclas[VK_LBUTTON] = True                # clic rapido con Ctrl: ya no cuenta
        time.sleep(0.3)
        ent.teclas[VK_LBUTTON] = False
        ent.teclas[VK_CONTROL] = False
        time.sleep(0.2)
        assert disparos == [], disparos
    finally:
        _terminar(es, antes)
