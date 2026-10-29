"""Detecta Ctrl + clic en cualquier parte de la pantalla (sin ganchos de teclado: solo revisa el estado)."""

import threading
import time

from . import entrada


class EscuchaCtrlClic:
    def __init__(self, al_disparar, es_propia=None, intervalo=0.008):
        self.al_disparar = al_disparar          # funcion(x, y)
        self.es_propia = es_propia or (lambda x, y: False)
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
        boton = entrada.boton_izquierdo()
        antes = entrada.tecla_abajo(boton)
        while not self._parar.is_set():
            abajo = entrada.tecla_abajo(boton)
            if abajo and not antes and entrada.tecla_abajo(entrada.VK_CONTROL):
                try:
                    x, y = entrada.posicion_mouse()
                    if not self.es_propia(x, y):
                        self.al_disparar(x, y)
                except Exception:
                    pass
            antes = abajo
            time.sleep(self.intervalo)
