"""Detecta Option + clic en cualquier parte de la pantalla (Mac).

Usa un 'event tap' de Quartz (necesita el permiso de Accesibilidad):
- Option + clic izquierdo dispara el trabajo y ese clic NO le llega a la pagina (en Safari o Chrome un
  Option + clic sobre un link lo descargaria).
- Tambien ve cuando se presiona Esc (para cancelar al instante).
- Los clics y teclas que manda NO LIMIT traen una marca y pasan sin tocarse.
"""

import logging
import threading

from . import entrada

try:
    import Quartz as Q
except ImportError:
    Q = None

log = logging.getLogger("clw")

DESACTIVADO = (0xFFFFFFFE, 0xFFFFFFFF)   # kCGEventTapDisabledByTimeout / ByUserInput


class EscuchaCtrlClic:
    """Mismo trato que la de Windows: al_disparar(x, y) en pixeles; es_propia(x, y) -> True si es NO LIMIT."""

    def __init__(self, al_disparar, es_propia=None, intervalo=0.01, al_ignorar=None):
        self.al_disparar = al_disparar
        self.es_propia = es_propia or (lambda x, y: False)
        self.al_ignorar = al_ignorar or (lambda motivo: None)
        self._hilo = None
        self._tap = None
        self._bucle = None
        self._funcion = None
        self._tragar_subida = False
        self.sin_permiso = False

    @property
    def corriendo(self):
        return self._hilo is not None and self._hilo.is_alive()

    def iniciar(self):
        """Devuelve False si macOS no deja escuchar (falta el permiso de Accesibilidad)."""
        if self.corriendo:
            return True
        mascara = 0
        for tipo in (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp, Q.kCGEventKeyDown, Q.kCGEventKeyUp):
            mascara |= Q.CGEventMaskBit(tipo)
        self._funcion = self._evento
        try:
            tap = Q.CGEventTapCreate(Q.kCGSessionEventTap, Q.kCGHeadInsertEventTap, Q.kCGEventTapOptionDefault,
                                     mascara, self._funcion, None)
        except Exception as ex:
            log.error("no se pudo crear la escucha: %s", ex)
            tap = None
        if not tap:
            self.sin_permiso = True
            log.warning("sin permiso de Accesibilidad: no se puede escuchar Option + clic")
            return False
        self.sin_permiso = False
        self._tap = tap
        listo = threading.Event()
        self._hilo = threading.Thread(target=self._correr, args=(tap, listo), name="escucha", daemon=True)
        self._hilo.start()
        listo.wait(2)
        return True

    def _correr(self, tap, listo):
        try:
            fuente = Q.CFMachPortCreateRunLoopSource(None, tap, 0)
            self._bucle = Q.CFRunLoopGetCurrent()
            Q.CFRunLoopAddSource(self._bucle, fuente, Q.kCFRunLoopCommonModes)
            Q.CGEventTapEnable(tap, True)
        except Exception as ex:
            log.error("escucha: %s", ex)
            listo.set()
            return
        listo.set()
        Q.CFRunLoopRun()                 # hasta que detener() lo pare

    def detener(self):
        tap, bucle, hilo = self._tap, self._bucle, self._hilo
        self._tap = self._bucle = self._hilo = None
        try:
            if tap is not None:
                Q.CGEventTapEnable(tap, False)
            if bucle is not None:
                Q.CFRunLoopStop(bucle)
            if hilo is not None:
                hilo.join(timeout=1)
            if tap is not None:
                Q.CFMachPortInvalidate(tap)
        except Exception as ex:
            log.warning("escucha al detener: %s", ex)

    # ------------------------------------------------ lo que llega de macOS (debe contestar rapido)
    def _evento(self, proxy, tipo, evento, dato):
        try:
            return self._decidir(tipo, evento)
        except Exception as ex:
            log.warning("escucha: %s", ex)
            return evento

    def _decidir(self, tipo, evento):
        if tipo in DESACTIVADO:          # macOS la apago (tardo mucho o algo raro): se vuelve a prender
            if self._tap is not None:
                Q.CGEventTapEnable(self._tap, True)
            return evento
        if Q.CGEventGetIntegerValueField(evento, Q.kCGEventSourceUserData) == entrada.MARCA:
            return evento                # lo mando NO LIMIT
        if tipo in (Q.kCGEventKeyDown, Q.kCGEventKeyUp):
            if Q.CGEventGetIntegerValueField(evento, Q.kCGKeyboardEventKeycode) == entrada.K_ESC:
                entrada.nota_esc(tipo == Q.kCGEventKeyDown)
            return evento
        if tipo == Q.kCGEventLeftMouseUp:
            if self._tragar_subida:
                self._tragar_subida = False
                return None
            return evento
        if tipo != Q.kCGEventLeftMouseDown:
            return evento
        banderas = int(Q.CGEventGetFlags(evento))
        otras = Q.kCGEventFlagMaskCommand | Q.kCGEventFlagMaskControl | Q.kCGEventFlagMaskShift
        if not banderas & Q.kCGEventFlagMaskAlternate or banderas & otras:
            return evento
        p = Q.CGEventGetLocation(evento)
        _, escala = entrada.pantalla_en(p.x, p.y)
        entrada.poner_escala(escala)
        x, y = p.x * escala, p.y * escala
        if self.es_propia(x, y):
            return evento                # Option + clic sobre NO LIMIT: clic normal
        self._tragar_subida = True
        threading.Thread(target=self._disparar, args=(x, y), name="disparo", daemon=True).start()
        return None                      # la pagina no recibe ese clic

    def _disparar(self, x, y):
        try:
            self.al_disparar(x, y)
        except Exception as ex:
            log.error("disparo: %s", ex)
