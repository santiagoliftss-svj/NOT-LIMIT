"""Detecta Ctrl + clic en cualquier parte de la pantalla (sin ganchos de teclado: solo revisa el estado).

Ademas: si mantienes presionado el boton del mouse 1 segundo sobre la pregunta (sin moverlo), se dispara
solo. Sirve donde bloquean los atajos con Ctrl (como Respondus LockDown Browser): un clic sostenido no lo
pueden bloquear.

Para no estorbar en juegos:
- no hace nada si al frente hay una app en pantalla completa que no es navegador,
- y solo cuenta el clic si el Ctrl se presiono hace poco (en juegos el Ctrl se deja apretado para agacharse).
"""

import sys
import threading
import time

from . import entrada

CTRL_FRESCO = 2.5   # segundos maximos entre presionar Ctrl y dar clic
MANTENER_SEG = 1.0  # mantener presionado el boton esta cantidad de segundos dispara la pregunta
MANTENER_PIX = 14   # ... siempre que el mouse no se haya movido mas que esto desde que se presiono


def _sobre_texto():
    """True si el puntero esta sobre texto (el cursor en forma de I): ahi viven las preguntas. Sobre botones
    (flecha) o enlaces (mano) no dispara: asi no se activa sola por mantener presionado un boton del examen
    (como el de iniciar el quiz). Si no se puede saber la forma del cursor, se permite."""
    try:
        forma = entrada.forma_cursor()
    except Exception:
        return True
    return forma is None or forma == "texto"


class EscuchaCtrlClic:
    def __init__(self, al_disparar, es_propia=None, intervalo=0.01, al_ignorar=None, mantener=MANTENER_SEG):
        self.al_disparar = al_disparar          # funcion(x, y)
        self.es_propia = es_propia or (lambda x, y: False)
        self.al_ignorar = al_ignorar or (lambda motivo: None)
        self.intervalo = intervalo
        self.mantener = mantener                # None = solo Ctrl + clic, sin el modo de mantener presionado
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
        pres_desde, pres_x, pres_y, ya_disparado = None, 0, 0, False
        while not self._parar.is_set():
            ctrl = entrada.tecla_abajo(entrada.VK_CONTROL)
            if ctrl and not ctrl_antes:
                ctrl_desde = time.time()
            ctrl_antes = ctrl
            abajo = entrada.tecla_abajo(boton)
            ahora = time.time()
            if abajo and not antes:                      # acaban de presionar el boton
                try:
                    pres_x, pres_y = entrada.posicion_mouse()
                    pres_desde, ya_disparado = ahora, False
                except Exception:
                    pres_desde = None
            # mantener presionado 1 segundo sin moverse: dispara (Ctrl no puede, Respondus lo bloquea)
            if abajo and pres_desde is not None and not ya_disparado and self.mantener:
                if ctrl:
                    pres_desde = None                   # eso lo atiende el Ctrl + clic de abajo
                elif ahora - pres_desde >= self.mantener:
                    try:
                        x, y = entrada.posicion_mouse()
                        if max(abs(x - pres_x), abs(y - pres_y)) > MANTENER_PIX:
                            pres_desde = None           # arrastro el mouse (o leyo con movimiento): no cuenta
                        elif not _sobre_texto():
                            pres_desde = None           # es un boton o un enlace, no una pregunta
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


if sys.platform == "darwin":             # Mac: Option + clic con un event tap de Quartz
    from .mac.escucha import EscuchaCtrlClic  # noqa: F401,F811,E402
