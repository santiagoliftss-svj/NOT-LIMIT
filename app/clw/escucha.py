"""Detecta el clic sostenido en cualquier parte de la pantalla (sin ganchos de teclado: solo revisa el
estado del boton).

Mantener presionado el boton del mouse 1 segundo sobre la pregunta, sin moverlo, dispara el trabajo.
Sirve donde bloquean los atajos con teclas (como Respondus LockDown Browser): un clic sostenido no lo
pueden bloquear. El Ctrl + clic ya no se usa: alla no sirve y sobraba.

Para no estorbar en juegos:
- no hace nada si al frente hay una app en pantalla completa que no es navegador.
"""

import sys
import threading
import time

from . import entrada

MANTENER_SEG = 1.0  # mantener presionado el boton esta cantidad de segundos dispara la pregunta
MANTENER_PIX = 14   # ... siempre que el mouse no se haya movido mas que esto desde que se presiono


class EscuchaCtrlClic:
    def __init__(self, al_disparar, es_propia=None, intervalo=0.01, al_ignorar=None, mantener=MANTENER_SEG):
        self.al_disparar = al_disparar          # funcion(x, y)
        self.es_propia = es_propia or (lambda x, y: False)
        self.al_ignorar = al_ignorar or (lambda motivo: None)
        self.intervalo = intervalo
        self.mantener = mantener                # None = no escuchar (solo para pruebas)
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
        pres_desde, pres_x, pres_y, ya_disparado = None, 0, 0, False
        while not self._parar.is_set():
            abajo = entrada.tecla_abajo(boton)
            ahora = time.time()
            if abajo and not antes:                      # acaban de presionar el boton
                try:
                    pres_x, pres_y = entrada.posicion_mouse()
                    pres_desde, ya_disparado = ahora, False
                except Exception:
                    pres_desde = None
            # mantener presionado 1 segundo sin moverse: dispara (las teclas no sirven, Respondus las bloquea)
            if abajo and pres_desde is not None and not ya_disparado and self.mantener:
                if ahora - pres_desde >= self.mantener:
                    try:
                        x, y = entrada.posicion_mouse()
                        if max(abs(x - pres_x), abs(y - pres_y)) > MANTENER_PIX:
                            pres_desde = None           # arrastro el mouse (o leyo con movimiento): no cuenta
                        elif entrada.juego_en_pantalla_completa():
                            self.al_ignorar("pantalla_completa")
                            pres_desde = None
                        elif not self.es_propia(x, y):
                            ya_disparado = True
                            self.al_disparar(x, y)
                    except Exception:
                        pres_desde = None
            if not abajo:
                pres_desde = None
            antes = abajo
            time.sleep(self.intervalo)


if sys.platform == "darwin":             # Mac: mismo clic sostenido, con un event tap de Quartz
    from .mac.escucha import EscuchaCtrlClic  # noqa: F401,F811,E402
