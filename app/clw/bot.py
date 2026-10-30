"""Une todo: escucha el Ctrl + clic, corre el motor en segundo plano y avisa a la interfaz."""

import logging
import os
import queue
import re
import threading
import time
import traceback
from datetime import datetime

from . import entrada, motor, rutas
from .escucha import EscuchaCtrlClic
from .ocr import OCR
from .proveedores import ClienteIA, ErrorIA, PROVEEDORES, buscar_modelo

log = logging.getLogger("clw")


def configurar_registro():
    try:
        from logging.handlers import RotatingFileHandler
        ruta = os.path.join(rutas.carpeta_datos(), "registro.txt")
        h = RotatingFileHandler(ruta, maxBytes=400_000, backupCount=1, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    except Exception:
        pass


def _corto(texto, n=60):
    texto = " ".join(str(texto or "").split())
    texto = re.sub(r"^(?:[©®°@•·*.]{1,4}\s+)+(?=\S)", "", texto)   # circulitos de opcion leidos como simbolos
    return texto if len(texto) <= n else texto[: n - 1] + "…"


class Bot:
    """Eventos que manda a la interfaz por la cola:
       ("estado", "apagado" | "activo" | "leyendo" | "pensando" | "escribiendo")
       ("actividad", texto, "ok" | "error" | "info")
       ("falta_clave", proveedor)
    """

    def __init__(self, config, eventos=None, ocr=None, cliente=None, acciones=entrada):
        self.config = config
        self.eventos = eventos or queue.Queue()
        self.ocr = ocr if ocr is not None else OCR()
        self.cliente = cliente or ClienteIA()
        self.acciones = acciones
        self.activo = False
        self._ocupado = threading.Lock()
        self._cancelar = threading.Event()
        self.hwnd_propio = None
        self.escucha = EscuchaCtrlClic(self._disparo, es_propia=self._es_propia, al_ignorar=self._ignorado)
        self.ignorados = {"ctrl_sostenido": 0, "pantalla_completa": 0}

    # ------------------------------------------------ control
    def _emitir(self, *evento):
        self.eventos.put(evento)

    def _es_propia(self, x, y):
        if not self.hwnd_propio:
            return False
        return entrada.ventana_raiz_en(x, y) == self.hwnd_propio

    def modelo(self):
        propio = self.config["modelos_propios"]
        m = buscar_modelo(self.config["modelo"])
        return m, propio.get(m.id, m.id)

    def puede_iniciar(self):
        m, _ = self.modelo()
        return self.config.tiene_clave(m.proveedor)

    def iniciar(self):
        m, _ = self.modelo()
        if not self.config.tiene_clave(m.proveedor):
            self._emitir("falta_clave", m.proveedor)
            return False
        self._cancelar.clear()
        self.activo = True
        self.escucha.iniciar()
        self._emitir("estado", "activo")
        log.info("activado con %s", m.id)
        return True

    def detener(self):
        self.activo = False
        self._cancelar.set()
        self.escucha.detener()
        if not self._ocupado.locked():
            self._emitir("estado", "apagado")
        log.info("detenido")

    # ------------------------------------------------ trabajo
    def _ignorado(self, motivo):
        self.ignorados[motivo] = self.ignorados.get(motivo, 0) + 1

    def _disparo(self, x, y):
        if not self.activo:
            return
        if not self._ocupado.acquire(blocking=False):
            self._emitir("actividad", "Espera, sigo con la anterior", "info")
            return
        threading.Thread(target=self._trabajo, args=(x, y), name="trabajo", daemon=True).start()

    def _esperar_que_suelte_ctrl(self, max_seg=3.0):
        fin = time.time() + max_seg
        while self.acciones.tecla_abajo(entrada.VK_CONTROL) and time.time() < fin:
            time.sleep(0.03)
        time.sleep(0.12)

    def _trabajo(self, x, y):
        self._cancelar.clear()
        entrada.bajar_prioridad_hilo()
        try:
            self._emitir("estado", "leyendo")
            self._esperar_que_suelte_ctrl()
            img, left, top = motor.capturar(x, y)
            self._tapar_ventana_propia(img, left, top)
            res = self.analizar(img, x - left, y - top, motor.factor_zoom())
            if res is None:
                return
            if res.tipo == "abierta" and any(p["punto"] for p in res.pasos):
                self._emitir("estado", "escribiendo")
            hecho, n = motor.ejecutar(res, left, top, cancelar=self._cancelar.is_set, acciones=self.acciones)
            self._reportar(res, hecho, n)
        except entrada.Cancelado:
            self._emitir("actividad", "Cancelado", "info")
        except ErrorIA as e:
            log.warning("IA: %s | %s", e.mensaje, e.detalle[:300])
            self._emitir("actividad", e.mensaje, "error")
            if e.tipo == "clave":
                m, _ = self.modelo()
                self._emitir("falta_clave", m.proveedor)
        except Exception as e:
            log.error("fallo: %s\n%s", e, traceback.format_exc())
            self._emitir("actividad", f"Algo falló: {_corto(e, 70)}", "error")
        finally:
            self._emitir("estado", "activo" if self.activo else "apagado")
            self._ocupado.release()

    def _tapar_ventana_propia(self, img, left, top, paso=16):
        """Pinta de negro solo la parte VISIBLE de la ventana de NO LIMIT en la captura
        (si esta detras del navegador no se tapa nada)."""
        if not self.hwnd_propio:
            return
        r = entrada.rect_ventana(self.hwnd_propio)
        if not r:
            return
        from PIL import ImageDraw
        dib = ImageDraw.Draw(img)
        for y in range(r[1], r[3], paso):
            for x in range(r[0], r[2], paso):
                cx, cy = min(x + paso // 2, r[2] - 1), min(y + paso // 2, r[3] - 1)
                if entrada.ventana_raiz_en(cx, cy) == self.hwnd_propio:
                    dib.rectangle((x - left, y - top, min(x + paso, r[2]) - 1 - left, min(y + paso, r[3]) - 1 - top),
                                  fill=(0, 0, 0))

    def analizar(self, img, px, py, zoom=1.0):
        """Lee la captura y pregunta a la IA. Devuelve motor.Resultado (lanza ErrorIA si falla)."""
        m, id_real = self.modelo()
        clave = self.config.clave(m.proveedor)
        preciso = bool(self.config["modo_preciso"])

        def preguntar(b64, mime, texto):
            return self.cliente.preguntar(m.proveedor, id_real, clave, motor.SISTEMA, b64, mime, texto, preciso)

        res = motor.procesar(img, px, py, preguntar, zoom, self.ocr,
                             avisar=lambda e: self._emitir("estado", e))
        log.info("modelo=%s lectura=%.1fs ia=%.1fs cajas=%d campos=%d salida=%s",
                 id_real, res.t_lectura, res.t_ia, len(res.cajas), len(res.campos), res.salida[:400])
        if self.config["guardar_capturas"]:
            motor.guardar_revision(os.path.join(rutas.carpeta_datos(), "revision"),
                                   img, res.cajas, res.campos, px, py, res.pasos)
        if not res.salida and res.cortado:
            self._emitir("actividad", "La IA se quedó sin espacio. Prueba otra vez.", "error")
            return None
        return res

    def _reportar(self, res, hecho, n):
        if hecho == "clic":
            textos = [p["punto"][2] for p in res.pasos if p["punto"]]
            if n == 1:
                nombre = res.datos.get("respuesta") if isinstance(res.datos.get("respuesta"), str) else ""
                self._emitir("actividad", f"Marcó: {_corto(nombre or (textos[0] if textos else 'la opción'))}", "ok")
            else:
                self._emitir("actividad", f"Marcó {n} opciones", "ok")
        elif hecho == "escrita":
            if n == 1:
                texto = next(p["texto"] for p in res.pasos if p["punto"])
                self._emitir("actividad", f"Escribió: {_corto(texto)}", "ok")
            else:
                self._emitir("actividad", f"Escribió {n} respuestas", "ok")
        elif hecho == "solo_mostrar":
            texto = " | ".join(p["texto"] for p in res.pasos)
            self._emitir("actividad", f"No vi dónde escribir. Respuesta: {_corto(texto, 80)}", "info")
        else:
            if res.tipo == "ninguna":
                self._emitir("actividad", "No vi ninguna pregunta ahí", "info")
            else:
                self._emitir("actividad", "No supe dónde dar clic", "info")


def hora():
    return datetime.now().strftime("%H:%M")


__all__ = ["Bot", "configurar_registro", "hora", "PROVEEDORES"]
