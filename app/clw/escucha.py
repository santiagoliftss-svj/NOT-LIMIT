"""Detecta Ctrl + clic en cualquier parte de la pantalla (sin ganchos de teclado: solo revisa el estado).

Para no estorbar en juegos:
- no hace nada si al frente hay una app en pantalla completa que no es navegador,
- y solo cuenta el clic si el Ctrl se presiono hace poco (en juegos el Ctrl se deja apretado para agacharse).
"""

import threading
import time

from . import entrada

CTRL_FRESCO = 2.5   # segundos maximos entre presionar Ctrl y dar clic


class EscuchaCtrlClic:
    def __init__(self, al_disparar, es_propia=None, intervalo=0.01, al_ignorar=None):
        self.al_disparar = al_disparar          # funcion(x, y)
        self.es_propia = es_propia or (lambda x, y: False)
        self.al_ignorar = al_ignorar or (lambda motivo: None)
        self.intervalo = intervalo
        self._parar = threading.Event()
        self._hilo = None

    @property
    def corriendo(self):
        return self._hilo is not None and self._hilo.is_alive()

    def iniciar(self):
        if self.corriendo:
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="escucha", daemon=True)
        self._hilo.start()

    def detener(self):
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=1)
        self._hilo = None

    def _bucle(self):
        entrada.bajar_prioridad_hilo()
        boton = entrada.boton_izquierdo()
        antes = entrada.tecla_abajo(boton)
        ctrl_antes = entrada.tecla_abajo(entrada.VK_CONTROL)
        ctrl_desde = time.time() if ctrl_antes else None
        while not self._parar.is_set():
            ctrl = entrada.tecla_abajo(entrada.VK_CONTROL)
            if ctrl and not ctrl_antes:
                ctrl_desde = time.time()
            ctrl_antes = ctrl
            abajo = entrada.tecla_abajo(boton)
            if abajo and not antes and ctrl:
                try:
                    if ctrl_desde is not None and time.time() - ctrl_desde > CTRL_FRESCO:
                        self.al_ignorar("ctrl_sostenido")
                    elif entrada.juego_en_pantalla_completa():
                        self.al_ignorar("pantalla_completa")
                    else:
                        x, y = entrada.posicion_mouse()
                        if not self.es_propia(x, y):
                            self.al_disparar(x, y)
                except Exception:
                    pass
            antes = abajo
            time.sleep(self.intervalo)
