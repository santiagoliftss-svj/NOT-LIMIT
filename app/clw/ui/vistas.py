"""Pantallas de CLW GANG. Todo es logica pura + dibujo con PIL (se puede probar sin ventana)."""

import math
import time
from collections import deque
from datetime import datetime

from .. import version
from ..proveedores import MODELOS, PROVEEDORES, buscar_modelo, clave_parece_de
from . import estilo as E
from .estilo import ALTO, ANCHO, BLANCO, ERROR, LINEA, LINEA_FUERTE, NEGRO, SUAVE, TENUE, TEXTO, Lienzo

ESTADOS = {
    "apagado": ("Apagado", "Toca Inyectar y luego Ctrl + clic en la pregunta"),
    "activo": ("Activo", "Pon el puntero en la pregunta y haz Ctrl + clic"),
    "leyendo": ("Leyendo la pantalla…", "Espera un segundo"),
    "pensando": ("Pensando la respuesta…", "Espera un segundo"),
    "escribiendo": ("Escribiendo…", "No toques el teclado. Esc para cancelar"),
}
OCUPADO = ("leyendo", "pensando", "escribiendo")

BOTON = (72, 258, 236, 64)      # x, y, w, h de INYECTAR


def _enmascarar(t):
    if len(t) <= 12:
        return "•" * len(t)
    return t[:7] + "•" * 8 + t[-4:]


class Interfaz:
    """Controlador de pantallas. 'app' da las acciones de afuera:
       iniciar(), detener(), verificar_clave(prov, texto), leer_portapapeles(), abrir_url(u), abrir_carpeta()"""

    def __init__(self, config, app, escala=1.0):
        self.config = config
        self.app = app
        self.e = escala
        self.ancho_px, self.alto_px = round(ANCHO * escala), round(ALTO * escala)
        self.pantalla = "principal"
        self.capa = None
        self.hover = None
        self.presionado = None
        self.cursor = "arrow"
        self.estado = "apagado"
        self.actividad = deque(maxlen=4)
        self.nueva_version = None
        self.clave = {"prov": "claude", "texto": "", "msg": "", "tipo": "", "verificando": False,
                      "volver": "principal", "iniciar": False}
        self.zonas = []
        self._cache_llave = None
        self._cache = None

    # ================================================================ estado
    def modelo_actual(self):
        return buscar_modelo(self.config["modelo"])

    def ocupado(self):
        return self.estado in OCUPADO

    def encendido(self):
        return self.estado != "apagado"

    def animando(self):
        return self.pantalla == "principal" and self.capa is None and self.encendido()

    def agregar_actividad(self, texto, tipo="ok"):
        self.actividad.appendleft((datetime.now().strftime("%H:%M"), texto, tipo))

    def evento_bot(self, ev):
        tipo = ev[0]
        if tipo == "estado":
            self.estado = ev[1]
        elif tipo == "actividad":
            self.agregar_actividad(ev[1], ev[2] if len(ev) > 2 else "ok")
        elif tipo == "falta_clave":
            if self.pantalla != "clave":
                self.abrir_clave(ev[1], volver="principal",
                                 msg="Agrega tu clave para empezar.", tipo="info")
        elif tipo == "nueva_version":
            self.nueva_version = ev[1]

    # ================================================================ navegacion
    def abrir_clave(self, prov, volver="principal", iniciar=False, msg="", tipo=""):
        self.capa = None
        self.pantalla = "clave"
        self.clave = {"prov": prov, "texto": "", "msg": msg, "tipo": tipo, "verificando": False,
                      "volver": volver, "iniciar": iniciar}

    def _accion(self, zid):
        c = self.config
        if zid == "inyectar":
            if self.encendido():
                self.app.detener()
            else:
                prov = self.modelo_actual().proveedor
                if c.tiene_clave(prov):
                    self.app.iniciar()
                else:
                    self.abrir_clave(prov, iniciar=True, msg="Agrega tu clave para empezar.", tipo="info")
        elif zid == "modelo":
            self.capa = "modelos"
        elif zid == "cerrar_capa":
            self.capa = None
        elif zid.startswith("modelo:"):
            nuevo = buscar_modelo(zid.split(":", 1)[1])
            c["modelo"] = nuevo.id
            self.capa = None
            if self.encendido() and not c.tiene_clave(nuevo.proveedor):
                self.app.detener()
                self.agregar_actividad(f"Agrega tu clave de {PROVEEDORES[nuevo.proveedor].nombre} para usar {nuevo.nombre}", "info")
        elif zid == "agregar_clave":
            self.abrir_clave(self.modelo_actual().proveedor)
        elif zid == "ajustes":
            self.pantalla = "ajustes"
        elif zid == "volver":
            self.pantalla = "principal"
        elif zid.startswith("clave:"):
            self.abrir_clave(zid.split(":", 1)[1], volver="ajustes")
        elif zid == "preciso":
            c["modo_preciso"] = not c["modo_preciso"]
        elif zid == "capturas":
            c["guardar_capturas"] = not c["guardar_capturas"]
        elif zid == "carpeta":
            self.app.abrir_carpeta()
        elif zid in ("pagina", "actualizar"):
            self.app.abrir_url(version.PAGINA)
        elif zid == "pegar":
            texto = (self.app.leer_portapapeles() or "").strip()
            if texto:
                self.clave["texto"] = "".join(texto.split())
                self.clave["msg"], self.clave["tipo"] = "", ""
        elif zid == "usar_gemini":
            c["modelo"] = "gemini-flash-latest"
            k = self.clave
            if c.tiene_clave("gemini"):
                self.pantalla = k["volver"]
                if k["iniciar"]:
                    self.app.iniciar()
            else:
                self.abrir_clave("gemini", volver=k["volver"], iniciar=k["iniciar"])
        elif zid == "sacar_clave":
            self.app.abrir_url(PROVEEDORES[self.clave["prov"]].url_clave)
        elif zid == "guardar_clave":
            self.guardar_clave()
        elif zid in ("cancelar_clave", "volver_clave"):
            self.pantalla = self.clave["volver"]

    def guardar_clave(self):
        k = self.clave
        if k["verificando"]:
            return
        texto = k["texto"].strip()
        if not texto:
            k["msg"], k["tipo"] = "Pega tu clave primero.", "error"
            return
        parece = clave_parece_de(texto)
        if parece and parece != k["prov"]:
            otro = PROVEEDORES[parece].nombre
            k["msg"], k["tipo"] = f"Esa clave parece de {otro}. Pégala en {otro} o usa una de {PROVEEDORES[k['prov']].nombre}.", "error"
            return
        k["verificando"] = True
        k["msg"], k["tipo"] = "", ""
        self.app.verificar_clave(k["prov"], texto)

    def clave_verificada(self, prov, texto, error):
        """La app la llama cuando termina de revisar la clave (error=None si sirve)."""
        k = self.clave
        if self.pantalla != "clave" or k["prov"] != prov:
            return
        k["verificando"] = False
        if error is not None and getattr(error, "tipo", "") != "red":
            k["msg"], k["tipo"] = error.mensaje if hasattr(error, "mensaje") else str(error), "error"
            return
        self.config.poner_clave(prov, texto)
        nombre = PROVEEDORES[prov].nombre
        if error is not None:  # sin internet: se guarda igual, se revisa al usarla
            self.agregar_actividad(f"Clave de {nombre} guardada (sin internet para revisarla)", "info")
        else:
            self.agregar_actividad(f"Clave de {nombre} guardada", "ok")
        self.pantalla = k["volver"]
        if k["iniciar"]:
            self.app.iniciar()

    # ================================================================ eventos
    def _zona_en(self, x, y):
        for zid, (zx, zy, zw, zh), cursor in reversed(self.zonas):
            if zx <= x <= zx + zw and zy <= y <= zy + zh:
                return zid, cursor
        return None, "arrow"

    def mover(self, x, y):
        zid, cursor = self._zona_en(x, y)
        cambio = zid != self.hover
        self.hover, self.cursor = zid, cursor
        return cambio

    def salir(self):
        cambio = self.hover is not None or self.presionado is not None
        self.hover = self.presionado = None
        self.cursor = "arrow"
        return cambio

    def presionar(self, x, y):
        self.presionado, _ = self._zona_en(x, y)
        return self.presionado is not None

    def soltar(self, x, y):
        zid, _ = self._zona_en(x, y)
        antes, self.presionado = self.presionado, None
        if zid and zid == antes and zid != "panel":
            self._accion(zid)
        return True

    def tecla(self, char, keysym, ctrl=False):
        if self.capa and keysym == "Escape":
            self.capa = None
            return True
        if self.pantalla == "clave":
            k = self.clave
            if keysym == "Return":
                self.guardar_clave()
            elif keysym == "Escape":
                self.pantalla = k["volver"]
            elif keysym == "BackSpace":
                k["texto"] = "" if ctrl else k["texto"][:-1]
                k["msg"] = ""
            elif ctrl and keysym.lower() == "v":
                self._accion("pegar")
            elif char and char.isprintable() and not char.isspace() and not ctrl and len(k["texto"]) < 300:
                k["texto"] += char
                k["msg"] = ""
            else:
                return False
            return True
        if self.pantalla == "ajustes" and keysym == "Escape":
            self.pantalla = "principal"
            return True
        return False

    # ================================================================ dibujo
    def _llave(self, t):
        k = self.clave
        extra = ()
        if self.pantalla == "clave":
            extra = (k["prov"], k["texto"], k["msg"], k["tipo"], k["verificando"], int(t * 2) % 2,
                     int(t * 3) % 4 if k["verificando"] else 0)
        c = self.config
        return (self.pantalla, self.capa, self.hover, self.presionado, self.estado, tuple(self.actividad),
                c["modelo"], c["modo_preciso"], c["guardar_capturas"], tuple(sorted(c["claves"].keys())),
                self.nueva_version) + extra

    def render(self, t=None):
        t = time.time() if t is None else t
        llave = self._llave(t)
        if llave != self._cache_llave:
            l = Lienzo(self.e, base=E.fondo_estrellas(self.ancho_px, self.alto_px, self.e))
            if self.pantalla == "principal":
                self._principal(l, t)
                if self.capa == "modelos":
                    self._modelos(l)
            elif self.pantalla == "ajustes":
                self._ajustes(l)
            elif self.pantalla == "clave":
                self._pantalla_clave(l, t)
            self.zonas = l.zonas
            self._cache, self._cache_llave = l.im, llave
        if not self.animando():
            return self._cache
        l = Lienzo(self.e, base=self._cache)
        self._animado(l, t)
        return l.im

    # ---------------------------------------------------------------- principal
    def _principal(self, l, t):
        c = self.config
        # logo
        wm = E.logo(l.px(346))
        l.pegar_px(wm, (l.w - wm.width) // 2, l.px(16))

        # modelo
        m = self.modelo_actual()
        tiene = c.tiene_clave(m.proveedor)
        l.texto(30, 148, "Modelo", "chico", SUAVE)
        hov = self.hover in ("modelo", "agregar_clave")
        l.caja(30, 168, 320, 54, 16, relleno=NEGRO + (255,), borde=LINEA_FUERTE if hov else LINEA, grosor=1)
        l.texto_centrado_v(48, 195, m.nombre, "nombre", TEXTO)
        l.icono("abajo", 322, 188, 14, SUAVE if not hov else TEXTO)
        l.zona("modelo", 30, 168, 320, 54)
        if tiene:
            l.texto_centrado_v(314, 195, m.nota, "chico", SUAVE, ancla="ra")
        else:
            col = BLANCO if self.hover == "agregar_clave" else TEXTO
            ancho = l.texto_centrado_v(314, 195, "Agregar clave", "chico", col, ancla="ra")
            l.linea_h(314 - ancho, 203, ancho, col + (150,))
            l.zona("agregar_clave", 314 - ancho - 6, 180, ancho + 12, 30)

        # boton principal
        x, y, w, h = BOTON
        pres = self.presionado == "inyectar"
        hov = self.hover == "inyectar"
        if pres:
            x, y, w, h = x + 3, y + 2, w - 6, h - 4
        if not self.encendido():
            relleno = (205, 205, 205) if pres else (232, 232, 232) if hov else BLANCO
            l.caja(x, y, w, h, h / 2, relleno=relleno + (255,))
            l.texto_centrado_v(x + w / 2, y + h / 2, "INYECTAR", "boton", NEGRO, ancla="ma", contorno=False)
        else:
            l.caja(x, y, w, h, h / 2, relleno=NEGRO + (255,), borde=(255, 255, 255, 255 if hov else 225), grosor=1.6)
            l.texto_centrado_v(x + w / 2, y + h / 2, "DETENER", "boton", BLANCO, ancla="ma")
        l.zona("inyectar", *BOTON)

        # estado
        titulo, ayuda = ESTADOS.get(self.estado, ESTADOS["apagado"])
        col = SUAVE if self.estado == "apagado" else TEXTO
        ancho = E.medir(titulo, "cuerpo", self.e) / self.e
        x0 = ANCHO / 2 - (ancho + 14) / 2
        if self.estado == "apagado":
            l.punto(x0 + 4, 353, 3.2, TENUE)
        l.texto_centrado_v(x0 + 14, 353, titulo, "cuerpo", col)
        l.texto(ANCHO / 2, 371, ayuda, "chico", TENUE, ancla="ma")
        self._punto_estado = (x0 + 4, 353)

        # actividad
        l.linea_h(30, 404, 320)
        if not self.actividad:
            l.texto(30, 420, "Aquí vas a ver lo que va contestando", "cuerpo", TENUE)
        for i, (hora, texto, tipo) in enumerate(self.actividad):
            yy = 420 + i * 27
            alfa = 255 if i == 0 else 200 if i == 1 else 150
            col = ERROR if tipo == "error" else TEXTO if tipo == "ok" else SUAVE
            l.texto(30, yy + 1.5, hora, "mini", TENUE)
            l.texto(72, yy, E.recortar(texto, "cuerpo", self.e, 278 * self.e), "cuerpo", col, alfa=alfa)

        # pie
        hov = self.hover == "ajustes"
        l.icono("engrane", 30, 557, 14, TEXTO if hov else SUAVE)
        l.texto_centrado_v(50, 564, "Ajustes", "chico", TEXTO if hov else SUAVE)
        l.zona("ajustes", 24, 550, 90, 28)
        if self.nueva_version:
            hov = self.hover == "actualizar"
            txt = f"Actualizar a v{self.nueva_version}"
            ancho = l.texto_centrado_v(350, 564, txt, "chico", BLANCO if hov else TEXTO, ancla="ra")
            l.linea_h(350 - ancho, 572, ancho, (255, 255, 255, 140))
            l.zona("actualizar", 350 - ancho - 6, 550, ancho + 12, 28)
        else:
            l.texto_centrado_v(350, 564, f"v{version.VERSION}", "mini", TENUE, ancla="ra")

    def _animado(self, l, t):
        x, y, w, h = BOTON
        fase = 0.5 + 0.5 * math.sin(t * 2 * math.pi / (1.2 if self.ocupado() else 2.6))
        nivel = int(round(fase * 10))
        brillo, pad = E.resplandor(l.px(w), l.px(h), l.px(h / 2), max(4, l.px(9)), nivel)
        l.pegar_px(brillo, l.px(x) - pad, l.px(y) - pad)
        # el boton se vuelve a pintar encima del brillo (solo la pastilla, sin esquinas)
        l.pegar_forma(self._cache, x, y, w, h, h / 2)
        px, py = getattr(self, "_punto_estado", (ANCHO / 2, 353))
        l.punto(px, py, 3.2 + 3.5 * fase, BLANCO, alfa=int(40 + 50 * (1 - fase)))
        l.punto(px, py, 3.2, BLANCO)

    # ---------------------------------------------------------------- selector de modelo
    def _modelos(self, l):
        l.oscurecer(205)
        l.zona("cerrar_capa", 0, 0, ANCHO, ALTO, cursor="arrow")
        grupos = []
        for m in MODELOS:
            if not grupos or grupos[-1][0] != m.proveedor:
                grupos.append((m.proveedor, []))
            grupos[-1][1].append(m)
        alto = 58 + sum(30 + 44 * len(ms) for _, ms in grupos) + 14
        y = (ALTO - alto) / 2
        l.caja(18, y, 344, alto, 22, relleno=NEGRO + (255,), borde=(255, 255, 255, 60), grosor=1)
        l.zona("panel", 18, y, 344, alto, cursor="arrow")
        l.texto(38, y + 22, "Elige el modelo", "subtitulo", TEXTO)
        yy = y + 58
        actual = self.config["modelo"]
        for prov, ms in grupos:
            l.texto(38, yy + 9, PROVEEDORES[prov].nombre, "mini", SUAVE)
            if not self.config.tiene_clave(prov):
                l.texto(342, yy + 9, "Sin clave", "mini", TENUE, ancla="ra")
            yy += 30
            for m in ms:
                zid = "modelo:" + m.id
                if self.hover == zid:
                    l.caja(28, yy, 324, 42, 12, relleno=(255, 255, 255, 18))
                sel = m.id == actual
                l.texto_centrado_v(42, yy + 21, m.nombre, "nombre", BLANCO if sel else TEXTO)
                derecha = 338
                if sel:
                    l.icono("palomita", 324, yy + 14, 14, BLANCO)
                    derecha = 316
                l.texto_centrado_v(derecha, yy + 21, m.nota, "chico", SUAVE, ancla="ra")
                l.zona(zid, 28, yy, 324, 42)
                yy += 44

    # ---------------------------------------------------------------- ajustes
    def _volver(self, l, zid):
        hov = self.hover == zid
        l.icono("atras", 22, 24, 16, TEXTO if hov else SUAVE)
        l.texto_centrado_v(40, 32, "Volver", "chico", TEXTO if hov else SUAVE)
        l.zona(zid, 16, 16, 90, 32)

    def _toggle(self, l, x, y, encendido, hov):
        if encendido:
            l.caja(x, y, 44, 24, 12, relleno=BLANCO + (255,))
            l.punto(x + 32, y + 12, 8, NEGRO)
        else:
            l.caja(x, y, 44, 24, 12, relleno=NEGRO + (255,), borde=LINEA_FUERTE if hov else (255, 255, 255, 70), grosor=1.2)
            l.punto(x + 12, y + 12, 7, (140, 140, 140) if not hov else (200, 200, 200))

    def _boton_fantasma(self, l, zid, x, y, w, h, texto):
        hov = self.hover == zid
        pres = self.presionado == zid
        l.caja(x, y, w, h, h / 2, relleno=(255, 255, 255, 30 if pres else 14 if hov else 0) if (hov or pres) else None,
               borde=LINEA_FUERTE if hov else (255, 255, 255, 64), grosor=1)
        l.texto_centrado_v(x + w / 2, y + h / 2, texto, "boton_chico", TEXTO, ancla="ma")
        l.zona(zid, x, y, w, h)

    def _boton_blanco(self, l, zid, x, y, w, h, texto, apagado=False):
        hov = self.hover == zid and not apagado
        pres = self.presionado == zid and not apagado
        relleno = (70, 70, 70) if apagado else (205, 205, 205) if pres else (232, 232, 232) if hov else BLANCO
        l.caja(x, y, w, h, h / 2, relleno=relleno + (255,))
        l.texto_centrado_v(x + w / 2, y + h / 2, texto, "boton_chico", NEGRO if not apagado else (20, 20, 20), ancla="ma",
                           contorno=False)
        l.zona(zid, x, y, w, h)

    def _ajustes(self, l):
        c = self.config
        self._volver(l, "volver")
        l.texto(30, 66, "Ajustes", "titulo", TEXTO)

        l.texto(30, 118, "Tus claves", "chico", SUAVE)
        for i, prov in enumerate(("claude", "gemini", "openai")):
            y = 138 + i * 60
            p = PROVEEDORES[prov]
            tiene = c.tiene_clave(prov)
            l.texto(30, y + 10, p.nombre, "nombre", TEXTO)
            if tiene:
                l.icono("palomita", 29, y + 31, 12, SUAVE)
                l.texto(44, y + 31, "Guardada", "chico", SUAVE)
            else:
                l.texto(30, y + 31, "Gratis en Google AI Studio" if prov == "gemini" else "Sin clave", "chico", TENUE)
            self._boton_fantasma(l, "clave:" + prov, 240, y + 12, 110, 32, "CAMBIAR" if tiene else "AGREGAR")
            if i < 2:
                l.linea_h(30, y + 59, 320)

        l.texto(30, 336, "Cómo contesta", "chico", SUAVE)
        hov = self.hover == "preciso"
        l.texto(30, 360, "Modo preciso", "nombre", TEXTO)
        for j, linea in enumerate(E.partir("Piensa más antes de contestar. Tarda un poco más.", "chico", self.e, 250 * self.e)):
            l.texto(30, 383 + j * 17, linea, "chico", SUAVE)
        self._toggle(l, 306, 362, c["modo_preciso"], hov)
        l.zona("preciso", 24, 352, 332, 58)

        hov = self.hover == "capturas"
        l.linea_h(30, 418, 320)
        l.texto(30, 434, "Guardar capturas", "nombre", TEXTO)
        for j, linea in enumerate(E.partir("Guarda lo último que vio para revisar si algo falla.", "chico", self.e, 250 * self.e)):
            l.texto(30, 457 + j * 17, linea, "chico", SUAVE)
        self._toggle(l, 306, 436, c["guardar_capturas"], hov)
        l.zona("capturas", 24, 426, 332, 52)
        hov = self.hover == "carpeta"
        ancho = l.texto(30, 496, "Abrir carpeta", "chico", TEXTO if hov else SUAVE)
        l.linea_h(30, 511, ancho, (255, 255, 255, 140 if hov else 70))
        l.zona("carpeta", 26, 490, ancho + 8, 26)

        hov = self.hover == "pagina"
        ancho = l.texto_centrado_v(30, 564, "Página de CLW GANG", "chico", TEXTO if hov else SUAVE)
        l.icono("afuera", 34 + ancho, 558, 12, TEXTO if hov else SUAVE)
        l.zona("pagina", 24, 550, ancho + 30, 28)
        l.texto_centrado_v(350, 564, f"v{version.VERSION}", "mini", TENUE, ancla="ra")

    # ---------------------------------------------------------------- clave
    def _pantalla_clave(self, l, t):
        k = self.clave
        p = PROVEEDORES[k["prov"]]
        self._volver(l, "volver_clave")
        l.texto(30, 66, f"Clave de {p.nombre}", "titulo", TEXTO)
        desc = "Pégala aquí. Se guarda cifrada y solo en esta computadora."
        for j, linea in enumerate(E.partir(desc, "cuerpo", self.e, 320 * self.e)):
            l.texto(30, 104 + j * 19, linea, "cuerpo", SUAVE)

        # campo
        error = k["tipo"] == "error"
        borde = (255, 104, 104, 190) if error else LINEA_FUERTE
        l.caja(30, 160, 320, 54, 16, relleno=NEGRO + (255,), borde=borde, grosor=1.2)
        l.zona("campo", 30, 160, 220, 54, cursor="xterm")
        if k["texto"]:
            visible = E.recortar(_enmascarar(k["texto"]), "cuerpo", self.e, 196 * self.e)
            ancho = l.texto_centrado_v(46, 187, visible, "cuerpo", TEXTO)
        else:
            ancho = 0
            l.texto_centrado_v(46, 187, p.prefijo + "…", "cuerpo", TENUE)
        if int(t * 2) % 2 == 0 and not k["verificando"]:
            l.caja(46 + ancho + 1.5, 178, 1.4, 18, 0.5, relleno=(255, 255, 255, 230))
        self._boton_fantasma(l, "pegar", 256, 171, 84, 32, "PEGAR")

        # enlace para sacar la clave
        hov = self.hover == "sacar_clave"
        ancho = l.texto(30, 232, p.texto_clave, "chico", TEXTO if hov else SUAVE)
        l.icono("afuera", 34 + ancho, 231, 12, TEXTO if hov else SUAVE)
        l.linea_h(30, 247, ancho, (255, 255, 255, 140 if hov else 60))
        l.zona("sacar_clave", 26, 226, ancho + 26, 26)

        # mensaje
        if k["verificando"]:
            puntos = "." * (int(t * 3) % 4)
            l.texto(30, 276, "Revisando la clave" + puntos, "cuerpo", SUAVE)
        elif k["msg"]:
            col = ERROR if k["tipo"] == "error" else TEXTO if k["tipo"] == "ok" else SUAVE
            for j, linea in enumerate(E.partir(k["msg"], "cuerpo", self.e, 320 * self.e)[:4]):
                l.texto(30, 276 + j * 19, linea, "cuerpo", col)

        if k["prov"] != "gemini" and not self.config.tiene_clave(k["prov"]):
            # atajo para quien no tiene saldo: Gemini Flash con clave gratis
            hov = self.hover == "usar_gemini"
            l.linea_h(30, 452, 320)
            l.texto(30, 468, "¿Sin saldo?", "chico", TENUE)
            ancho = l.texto(30, 486, "Usa Gemini Flash con una clave gratis", "chico", TEXTO if hov else SUAVE)
            l.linea_h(30, 501, ancho, (255, 255, 255, 140 if hov else 60))
            l.zona("usar_gemini", 26, 480, ancho + 8, 26)

        self._boton_fantasma(l, "cancelar_clave", 30, 516, 148, 52, "CANCELAR")
        self._boton_blanco(l, "guardar_clave", 190, 516, 160, 52, "GUARDAR",
                           apagado=not k["texto"] or k["verificando"])
