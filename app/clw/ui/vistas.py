"""Pantallas de CLW GANG: total black, vidrio, letras anchas y animaciones suaves.

Todo es logica pura + dibujo con PIL (se puede probar sin ventana). La parte fija de cada pantalla se guarda
en cache; encima se pintan las piezas que se mueven (estrella del halo, boton, punto de estado, transiciones).
"""

import math
import time
from collections import deque
from datetime import datetime

from PIL import Image, ImageDraw

from .. import version
from ..proveedores import MODELOS, PROVEEDORES, buscar_modelo, clave_parece_de
from . import estilo as E
from .estilo import ALTO, ANCHO, BLANCO, ERROR, NEGRO, SUAVE, TENUE, TEXTO, Lienzo

ESTADOS = {
    "apagado": ("Apagado", "Toca Inyectar y se va junto al reloj"),
    "activo": ("Activo", "Ctrl + clic sobre cualquier pregunta"),
    "leyendo": ("Leyendo la pantalla…", "Espera un segundo"),
    "pensando": ("Pensando la respuesta…", "Espera un segundo"),
    "escribiendo": ("Escribiendo…", "No toques el teclado. Esc cancela"),
}
OCUPADO = ("leyendo", "pensando", "escribiendo")

MARCA_ANCHO = 324
BOTON = (90, 252, 200, 54)          # x, y, w, h de INYECTAR
T_ENCENDER, T_ANILLO, T_APAGAR = 0.5, 0.45, 0.32
T_TRANSICION, T_CAPA, T_FILA = 0.26, 0.24, 0.4
VUELTA_ESTRELLA = 10.0              # segundos por vuelta del halo
VUELTA_HAZ = 3.4                    # segundos por vuelta de la luz del boton


def _enmascarar(t):
    if len(t) <= 12:
        return "•" * len(t)
    return t[:7] + "•" * 8 + t[-4:]


class Interfaz:
    """Controlador de pantallas. 'app' da las acciones de afuera:
       iniciar(), detener(), verificar_clave(prov, texto), leer_portapapeles(), abrir_url(u), abrir_carpeta()"""

    def __init__(self, config, app, escala=1.0, reloj=time.time):
        self.config = config
        self.app = app
        self.e = escala
        self.reloj = reloj
        self.ancho_px, self.alto_px = round(ANCHO * escala), round(ALTO * escala)
        self.pantalla = "principal"
        self.capa = None
        self.hover = None
        self.presionado = None
        self.cursor = "arrow"
        self.estado = "apagado"
        self.actividad = deque(maxlen=4)
        self.nueva_version = None
        self.visible = True
        self.enfocado = True
        self.clave = {"prov": "claude", "texto": "", "msg": "", "tipo": "", "verificando": False,
                      "volver": "principal", "iniciar": False}
        self.zonas = []
        self._cache_llave = self._cache = None
        self._quieto_llave = self._quieto = None
        self._ultima = None
        self._anim_boton = None            # ("encender" | "apagar", t0)
        self._esconder_en = None
        self._trans = None                 # {"desde": img, "t0": t, "dir": 1 | -1}
        self._capa_t0 = 0.0
        self._t_fila = -10.0
        self._punto_estado = (ANCHO / 2, 332)
        self._textos = {}
        self._grados = None                # angulo de la estrella del halo
        self._t_estrella = None

    # ================================================================ estado
    def modelo_actual(self):
        return buscar_modelo(self.config["modelo"])

    def ocupado(self):
        return self.estado in OCUPADO

    def encendido(self):
        return self.estado != "apagado"

    def _anim_activa(self, t):
        if self._trans and t - self._trans["t0"] < T_TRANSICION:
            return True
        if self._anim_boton:
            tipo, t0 = self._anim_boton
            dur = T_ENCENDER + T_ANILLO if tipo == "encender" else T_APAGAR
            if t - t0 < dur:
                return True
        if self.capa and t - self._capa_t0 < T_CAPA:
            return True
        if t - self._t_fila < T_FILA:
            return True
        return False

    def animando(self, t=None):
        t = self.reloj() if t is None else t
        if not self.visible:
            return False
        if self._anim_activa(t):
            return True
        return self.enfocado and self.pantalla == "principal" and self.capa is None

    def ritmo(self, t=None):
        """Cada cuantos ms conviene volver a dibujar (None = nada se mueve)."""
        t = self.reloj() if t is None else t
        if not self.visible:
            return None
        if self._anim_activa(t):
            return 16
        if self.animando(t):
            return 40
        return None

    def agregar_actividad(self, texto, tipo="ok"):
        self.actividad.appendleft((datetime.now().strftime("%H:%M"), texto, tipo))
        self._t_fila = self.reloj()

    def evento_bot(self, ev):
        tipo = ev[0]
        if tipo == "estado":
            self.estado = ev[1]
        elif tipo == "actividad":
            self.agregar_actividad(ev[1], ev[2] if len(ev) > 2 else "ok")
        elif tipo == "falta_clave":
            if self.pantalla != "clave":
                self.abrir_clave(ev[1], volver="principal", msg="Agrega tu clave para empezar.", tipo="info")
        elif tipo == "nueva_version":
            self.nueva_version = ev[1]

    def debe_esconder(self, t=None):
        """True una sola vez cuando termina la animacion de INYECTAR (la ventana se va a la bandeja)."""
        t = self.reloj() if t is None else t
        if self._esconder_en is not None and t >= self._esconder_en:
            self._esconder_en = None
            return self.encendido()
        return False

    # ================================================================ navegacion
    def _ir(self, pantalla, direccion=1):
        if pantalla == self.pantalla:
            return
        if self._ultima is not None and self.visible:
            self._trans = {"desde": self._ultima, "t0": self.reloj(), "dir": direccion}
        self.pantalla = pantalla
        self.capa = None

    def abrir_clave(self, prov, volver="principal", iniciar=False, msg="", tipo=""):
        self.clave = {"prov": prov, "texto": "", "msg": msg, "tipo": tipo, "verificando": False,
                      "volver": volver, "iniciar": iniciar}
        self._ir("clave", 1)

    def _encender(self):
        ahora = self.reloj()
        self.app.iniciar()
        self._anim_boton = ("encender", ahora)
        self._esconder_en = ahora + T_ENCENDER + T_ANILLO + 0.15

    def inyectar(self):
        """Lo mismo que tocar el boton (prende o apaga)."""
        self._accion("inyectar")

    def _accion(self, zid):
        c = self.config
        if zid == "inyectar":
            if self.encendido():
                self.app.detener()
                self._anim_boton = ("apagar", self.reloj())
                self._esconder_en = None
            else:
                prov = self.modelo_actual().proveedor
                if c.tiene_clave(prov):
                    self._encender()
                else:
                    self.abrir_clave(prov, iniciar=True, msg="Agrega tu clave para empezar.", tipo="info")
        elif zid == "modelo":
            self.capa = "modelos"
            self._capa_t0 = self.reloj()
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
            self._ir("ajustes", 1)
        elif zid == "volver":
            self._ir("principal", -1)
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
        elif zid == "sacar_clave":
            self.app.abrir_url(PROVEEDORES[self.clave["prov"]].url_clave)
        elif zid == "usar_gemini":
            c["modelo"] = "gemini-flash-latest"
            k = self.clave
            if c.tiene_clave("gemini"):
                self._ir(k["volver"], -1)
                if k["iniciar"]:
                    self._encender()
            else:
                self.abrir_clave("gemini", volver=k["volver"], iniciar=k["iniciar"])
        elif zid == "guardar_clave":
            self.guardar_clave()
        elif zid in ("cancelar_clave", "volver_clave"):
            self._ir(self.clave["volver"], -1)

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
        k = self.clave
        if self.pantalla != "clave" or k["prov"] != prov:
            return
        k["verificando"] = False
        if error is not None and getattr(error, "tipo", "") != "red":
            k["msg"], k["tipo"] = (error.mensaje if hasattr(error, "mensaje") else str(error)), "error"
            return
        self.config.poner_clave(prov, texto)
        nombre = PROVEEDORES[prov].nombre
        if error is not None:
            self.agregar_actividad(f"Clave de {nombre} guardada (sin internet para revisarla)", "info")
        else:
            self.agregar_actividad(f"Clave de {nombre} guardada", "ok")
        self._ir(k["volver"], -1)
        if k["iniciar"]:
            self._encender()

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
                self._ir(k["volver"], -1)
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
            self._ir("principal", -1)
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
        fila_animada = t - self._t_fila < T_FILA
        return (self.pantalla, self.capa, self.hover, self.presionado, self.estado, tuple(self.actividad),
                fila_animada, c["modelo"], c["modo_preciso"], c["guardar_capturas"],
                tuple(sorted(c["claves"].keys())), self.nueva_version) + extra

    def render(self, t=None):
        t = self.reloj() if t is None else t
        llave = self._llave(t)
        if llave != self._cache_llave:
            l = Lienzo(self.e)
            if self.pantalla == "principal":
                self._principal(l, t)
            elif self.pantalla == "ajustes":
                self._ajustes(l)
            elif self.pantalla == "clave":
                self._pantalla_clave(l, t)
            if self.capa == "modelos":
                self._zonas_modelos(l)
            self.zonas = l.zonas
            self._cache, self._cache_llave = l.im, llave

        if not self.animando(t):
            llave_q = (llave, "quieto", round(self._grados or 0, 1))
            if llave_q != self._quieto_llave:
                l = Lienzo(self.e, base=self._cache)
                self._encima(l, t, quieto=True)
                self._quieto, self._quieto_llave = l.im, llave_q
            self._ultima = self._quieto
            return self._quieto

        l = Lienzo(self.e, base=self._cache)
        self._encima(l, t, quieto=False)
        im = l.im
        if self._trans:
            p = (t - self._trans["t0"]) / T_TRANSICION
            if p >= 1:
                self._trans = None
            else:
                im = self._mezclar(self._trans["desde"], im, E.suave(p), self._trans["dir"])
        self._ultima = im
        return im

    def _mezclar(self, viejo, nuevo, p, direccion):
        """El viejo se va hacia un lado y se desvanece; el nuevo llega del otro lado."""
        d = 26 * self.e
        lienzo = Image.new("RGBA", nuevo.size, NEGRO + (255,))
        for img, alfa, desp in ((viejo, 1 - p, -direccion * d * p), (nuevo, p, direccion * d * (1 - p))):
            capa = img.copy()
            capa.putalpha(capa.getchannel("A").point(lambda a, k=alfa: int(a * k)))
            desp = int(round(desp))
            if desp >= 0:
                lienzo.alpha_composite(capa.crop((0, 0, capa.width - desp, capa.height)), (desp, 0))
            else:
                lienzo.alpha_composite(capa.crop((-desp, 0, capa.width, capa.height)), (0, 0))
        return lienzo

    # ---------------------------------------------------------------- piezas que se mueven
    def _encima(self, l, t, quieto):
        if self.pantalla == "principal":
            self._estrella(l, t, quieto)
            self._boton(l, t, quieto)
            self._punto(l, t, quieto)
            if not quieto and t - self._t_fila < T_FILA and self.actividad:
                self._fila(l, 0, self.actividad[0], E.suave((t - self._t_fila) / T_FILA))
        if self.capa == "modelos":
            self._modelos(l, 1.0 if quieto else E.suave((t - self._capa_t0) / T_CAPA))

    def _estrella(self, l, t, quieto):
        im, geo = E.marca(l.px(MARCA_ANCHO))
        X0 = (l.w - im.width) // 2
        Y0 = l.px(30)
        if self._grados is None:
            self._grados = geo["estrella"]
        if quieto:
            self._t_estrella = None
        else:
            if self._t_estrella is not None:
                paso = max(0.0, min(0.1, t - self._t_estrella))
                self._grados = (self._grados + 360 * paso / VUELTA_ESTRELLA) % 360
            self._t_estrella = t
        grados = self._grados
        x, y = E.punto_halo(geo, grados)
        adelante = 0 <= grados <= 180
        r = max(3, int(geo["alto_letras"] * (0.17 if adelante else 0.12)))
        sprite = E.estrella(r, 255 if adelante else 80)
        l.pegar_px(sprite, X0 + x - sprite.width / 2, Y0 + y - sprite.height / 2)

    def _boton(self, l, t, quieto):
        x, y, w, h = BOTON
        X, Y, W, H = l.caja_px(x, y, w, h)
        R = H // 2
        hov = self.hover == "inyectar"
        pres = self.presionado == "inyectar"
        encendido = self.encendido()

        relleno = 1.0 if encendido else 0.0
        anillo = None
        animando_encender = False
        if self._anim_boton:
            tipo, t0 = self._anim_boton
            dt = t - t0
            if quieto:
                self._anim_boton = None
            elif tipo == "encender":
                animando_encender = True
                relleno = E.ida_y_vuelta(dt / T_ENCENDER)
                if dt > T_ENCENDER:
                    anillo = E.suave((dt - T_ENCENDER) / T_ANILLO)
                if dt > T_ENCENDER + T_ANILLO:
                    self._anim_boton = None
            else:
                relleno = 1 - E.ida_y_vuelta(dt / T_APAGAR)
                if dt > T_APAGAR:
                    self._anim_boton = None

        if encendido and relleno >= 1 and anillo is None:
            fase = 0.5 if quieto else 0.5 + 0.5 * math.sin(t * 2 * math.pi / (1.2 if self.ocupado() else 2.8))
            brillo, pad = E.resplandor(W, H, R, max(4, l.px(10)), int(round(fase * 10)))
            l.pegar_px(brillo, X - pad, Y - pad)
        if anillo is not None and anillo < 1:
            k = 1 + 0.34 * anillo
            Wk, Hk = int(W * k), int(H * k)
            a = int(235 * (1 - anillo))
            aro = E.vidrio(Wk, Hk, Hk // 2, borde=(a, a), relleno=(0, 0), grosor=1.6 * self.e)
            l.pegar_px(aro, X - (Wk - W) / 2, Y - (Hk - H) / 2)

        if pres:
            X, Y, W, H = X + l.px(2), Y + l.px(1.5), W - l.px(4), H - l.px(3)
            R = H // 2
        capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if relleno < 1:
            borde = (255, 175) if hov else (215, 105)
            fondo = (46, 18) if pres else (30, 12) if hov else (16, 5)
            capa.alpha_composite(E.vidrio(W, H, R, borde=borde, relleno=fondo, grosor=1.3 * self.e))
            if not quieto and not encendido and not animando_encender:
                paso = int((t % VUELTA_HAZ) / VUELTA_HAZ * 72)
                capa.alpha_composite(E.haz_borde(W, H, R, 1.3 * self.e, paso))
        if anillo is not None:
            texto = "ACTIVO"
        elif encendido or animando_encender:
            texto = "DETENER" if not animando_encender else "INYECTAR"
        else:
            texto = "INYECTAR"
        blanco_txt = self._texto_capa(W, H, texto, BLANCO)
        if relleno > 0:
            corte = Image.new("L", (W, H), 0)
            ImageDraw.Draw(corte).rectangle((0, 0, int(W * relleno), H), fill=255)
            mascara = Image.new("L", (W, H), 0)
            mascara.paste(E.forma(W, H, R), (0, 0), corte)
            color = (205, 205, 205) if pres else (238, 238, 238) if (hov and encendido) else BLANCO
            pastilla = Image.new("RGBA", (W, H), color + (0,))
            pastilla.putalpha(mascara)
            capa.alpha_composite(pastilla)
            negro_txt = self._texto_capa(W, H, texto, NEGRO)
            capa.alpha_composite(Image.composite(negro_txt, blanco_txt, mascara))
        else:
            capa.alpha_composite(blanco_txt)
        l.pegar_px(capa, X, Y)

    def _texto_capa(self, W, H, texto, color):
        clave = (W, H, texto, color)
        if clave not in self._textos:
            mini = Lienzo(self.e, base=Image.new("RGBA", (W, H), (0, 0, 0, 0)))
            mini.texto_centrado_v(W / 2 / self.e, H / 2 / self.e, texto, "boton", color, ancla="ma")
            self._textos[clave] = mini.im
            if len(self._textos) > 40:
                self._textos.pop(next(iter(self._textos)))
        return self._textos[clave]

    def _punto(self, l, t, quieto):
        x, y = self._punto_estado
        if self.estado == "apagado":
            l.punto(x, y, 3.6, BLANCO, alfa=150, anillo_solo=True)
            return
        if not quieto:
            fase = 0.5 + 0.5 * math.sin(t * 2 * math.pi / (1.0 if self.ocupado() else 2.0))
            l.punto(x, y, 3.6 + 4 * fase, BLANCO, alfa=int(25 + 55 * (1 - fase)))
        l.punto(x, y, 3.6, BLANCO)

    # ---------------------------------------------------------------- principal
    def _principal(self, l, t):
        c = self.config
        im, _ = E.marca(l.px(MARCA_ANCHO))
        l.pegar_px(im, (l.w - im.width) // 2, l.px(30))

        # modelo
        m = self.modelo_actual()
        tiene = c.tiene_clave(m.proveedor)
        hov = self.hover in ("modelo", "agregar_clave")
        l.vidrio(28, 146, 324, 60, 18, borde=(150, 40) if hov else (95, 24), relleno=(16, 5) if hov else (10, 3))
        l.texto(46, 158, PROVEEDORES[m.proveedor].nombre, "mini", SUAVE)
        l.texto(46, 175, m.corto or m.nombre, "nombre", TEXTO)
        l.icono("abajo", 326, 169, 14, TEXTO if hov else SUAVE)
        l.zona("modelo", 28, 146, 324, 60)
        if tiene:
            ancho = E.medir(m.nota, "mini", self.e) / self.e + 22
            l.vidrio(316 - ancho, 164, ancho, 24, 12, borde=(90, 50), relleno=(0, 0))
            l.texto_centrado_v(316 - ancho / 2, 176, m.nota, "mini", SUAVE, ancla="ma")
        else:
            ancho = E.medir("Agregar clave", "mini", self.e) / self.e + 24
            hov2 = self.hover == "agregar_clave"
            l.solido(316 - ancho, 164, ancho, 24, 12, (255, 255, 255, 255 if hov2 else 235))
            l.texto_centrado_v(316 - ancho / 2, 176, "Agregar clave", "mini", NEGRO, ancla="ma")
            l.zona("agregar_clave", 316 - ancho - 4, 160, ancho + 8, 32)

        l.zona("inyectar", *BOTON)

        # estado
        titulo, ayuda = ESTADOS.get(self.estado, ESTADOS["apagado"])
        ancho = E.medir(titulo, "cuerpo", self.e) / self.e
        x0 = ANCHO / 2 - (ancho + 16) / 2
        self._punto_estado = (x0 + 4, 332)
        l.texto_centrado_v(x0 + 16, 332, titulo, "cuerpo", TEXTO if self.encendido() else SUAVE)
        l.texto(ANCHO / 2, 348, ayuda, "chico", TENUE, ancla="ma")

        # actividad
        l.vidrio(28, 384, 324, 152, 18, borde=(70, 18), relleno=(8, 2))
        if not self.actividad:
            l.texto(ANCHO / 2, 452, "Aquí vas a ver lo que va contestando", "cuerpo", TENUE, ancla="ma")
        fila_animada = t - self._t_fila < T_FILA
        for i, fila in enumerate(self.actividad):
            if i == 0 and fila_animada:
                continue
            self._fila(l, i, fila, 1.0)

        # pie
        hov = self.hover == "ajustes"
        l.icono("engrane", 30, 557, 14, TEXTO if hov else SUAVE)
        l.texto_centrado_v(50, 564, "Ajustes", "chico", TEXTO if hov else SUAVE)
        l.zona("ajustes", 24, 550, 90, 28)
        if self.nueva_version:
            hov = self.hover == "actualizar"
            txt = f"Actualizar a v{self.nueva_version}"
            ancho = E.medir(txt, "mini", self.e) / self.e + 24
            l.solido(352 - ancho, 552, ancho, 24, 12, (255, 255, 255, 255 if hov else 235))
            l.texto_centrado_v(352 - ancho / 2, 564, txt, "mini", NEGRO, ancla="ma")
            l.zona("actualizar", 352 - ancho - 4, 548, ancho + 8, 32)
        else:
            l.texto_centrado_v(350, 564, f"v{version.VERSION}", "mini", TENUE, ancla="ra")

    def _fila(self, l, i, fila, p):
        hora, texto, tipo = fila
        yy = 400 + i * 32 - (1 - p) * 8
        base = 255 if i == 0 else 205 if i == 1 else 160 if i == 2 else 120
        alfa = int(base * p)
        col = ERROR if tipo == "error" else TEXTO if tipo == "ok" else SUAVE
        l.texto(46, yy + 2, hora, "mini", TENUE, alfa=alfa)
        l.texto(90, yy, E.recortar(texto, "cuerpo", self.e, 244 * self.e), "cuerpo", col, alfa=alfa)

    # ---------------------------------------------------------------- selector de modelo
    def _grupos(self):
        grupos = []
        for m in MODELOS:
            if not grupos or grupos[-1][0] != m.proveedor:
                grupos.append((m.proveedor, []))
            grupos[-1][1].append(m)
        alto = 62 + sum(30 + 44 * len(ms) for _, ms in grupos) + 12
        return grupos, alto

    def _zonas_modelos(self, l):
        grupos, alto = self._grupos()
        y = ALTO - alto - 12
        l.zona("cerrar_capa", 0, 0, ANCHO, ALTO, cursor="arrow")
        l.zona("panel", 12, y, 356, alto, cursor="arrow")
        yy = y + 62
        for prov, ms in grupos:
            yy += 30
            for m in ms:
                l.zona("modelo:" + m.id, 22, yy, 336, 42)
                yy += 44

    def _modelos(self, l, p):
        l.oscurecer(int(205 * p))
        grupos, alto = self._grupos()
        y = ALTO - alto - 12 + (1 - p) * 40
        panel = Lienzo(self.e, base=Image.new("RGBA", (l.w, l.h), (0, 0, 0, 0)))
        panel.solido(12, y, 356, alto, 26, (0, 0, 0, 255))
        panel.vidrio(12, y, 356, alto, 26, borde=(130, 34), relleno=(10, 2))
        panel.texto(32, y + 24, "ELIGE EL MODELO", "subtitulo", TEXTO)
        yy = y + 62
        actual = self.config["modelo"]
        for prov, ms in grupos:
            panel.texto(32, yy + 9, PROVEEDORES[prov].nombre, "mini", SUAVE)
            if not self.config.tiene_clave(prov):
                panel.texto(348, yy + 9, "Sin clave", "mini", TENUE, ancla="ra")
            yy += 30
            for m in ms:
                if self.hover == "modelo:" + m.id:
                    panel.solido(22, yy, 336, 42, 12, (255, 255, 255, 22))
                sel = m.id == actual
                panel.texto_centrado_v(34, yy + 21, m.nombre, "nombre", BLANCO if sel else SUAVE)
                derecha = 346
                if sel:
                    panel.icono("palomita", 332, yy + 14, 14, BLANCO)
                    derecha = 324
                panel.texto_centrado_v(derecha, yy + 21, m.nota, "chico", SUAVE if sel else TENUE, ancla="ra")
                yy += 44
        k = min(1.0, 2 * p)
        if k < 1:
            panel.im.putalpha(panel.im.getchannel("A").point(lambda a: int(a * k)))
        l.im.alpha_composite(panel.im)

    # ---------------------------------------------------------------- ajustes
    def _volver(self, l, zid):
        hov = self.hover == zid
        l.icono("atras", 22, 24, 16, TEXTO if hov else SUAVE)
        l.texto_centrado_v(40, 32, "Volver", "chico", TEXTO if hov else SUAVE)
        l.zona(zid, 16, 16, 90, 32)

    def _toggle(self, l, x, y, encendido, hov):
        if encendido:
            l.solido(x, y, 46, 26, 13, (255, 255, 255, 255))
            l.punto(x + 33, y + 13, 9, NEGRO)
        else:
            l.vidrio(x, y, 46, 26, 13, borde=(200, 120) if hov else (140, 70), relleno=(14, 6))
            l.punto(x + 13, y + 13, 8, (210, 210, 210) if hov else (160, 160, 160))

    def _boton_vidrio(self, l, zid, x, y, w, h, texto):
        hov = self.hover == zid
        pres = self.presionado == zid
        l.vidrio(x, y, w, h, h / 2, borde=(240, 150) if hov else (190, 90),
                 relleno=(40, 16) if pres else (26, 10) if hov else (12, 4), grosor=1.2)
        l.texto_centrado_v(x + w / 2, y + h / 2, texto, "boton_chico", TEXTO, ancla="ma")
        l.zona(zid, x, y, w, h)

    def _boton_blanco(self, l, zid, x, y, w, h, texto, apagado=False):
        if apagado:
            l.solido(x, y, w, h, h / 2, (255, 255, 255, 34))
            l.texto_centrado_v(x + w / 2, y + h / 2, texto, "boton_chico", TENUE, ancla="ma")
            l.zona(zid, x, y, w, h)
            return
        hov = self.hover == zid
        pres = self.presionado == zid
        color = (205, 205, 205, 255) if pres else (236, 236, 236, 255) if hov else (255, 255, 255, 255)
        l.solido(x, y, w, h, h / 2, color)
        l.texto_centrado_v(x + w / 2, y + h / 2, texto, "boton_chico", NEGRO, ancla="ma")
        l.zona(zid, x, y, w, h)

    def _ajustes(self, l):
        c = self.config
        self._volver(l, "volver")
        l.texto(30, 64, "AJUSTES", "titulo", TEXTO)

        l.texto(30, 110, "Tus claves", "chico", SUAVE)
        l.vidrio(28, 130, 324, 186, 18, borde=(85, 22), relleno=(9, 3))
        for i, prov in enumerate(("claude", "gemini", "openai")):
            y = 130 + i * 62
            p = PROVEEDORES[prov]
            tiene = c.tiene_clave(prov)
            l.texto(46, y + 14, p.nombre, "nombre", TEXTO)
            if tiene:
                l.icono("palomita", 45, y + 36, 12, SUAVE)
                l.texto(61, y + 36, "Guardada", "chico", SUAVE)
            else:
                l.texto(46, y + 36, "Gratis en Google AI Studio" if prov == "gemini" else "Sin clave", "chico", TENUE)
            self._boton_vidrio(l, "clave:" + prov, 236, y + 15, 100, 32, "CAMBIAR" if tiene else "AGREGAR")
            if i < 2:
                l.linea_h(44, y + 62, 292, (255, 255, 255, 28))

        l.texto(30, 334, "Cómo contesta", "chico", SUAVE)
        l.vidrio(28, 354, 324, 160, 18, borde=(85, 22), relleno=(9, 3))
        hov = self.hover == "preciso"
        l.texto(46, 368, "Modo preciso", "nombre", TEXTO)
        for j, linea in enumerate(E.partir("Piensa antes de contestar. Se equivoca menos y tarda un poco más.",
                                           "chico", self.e, 222 * self.e)):
            l.texto(46, 391 + j * 16, linea, "chico", SUAVE)
        self._toggle(l, 290, 374, c["modo_preciso"], hov)
        l.zona("preciso", 28, 354, 324, 76)
        l.linea_h(44, 432, 292, (255, 255, 255, 28))

        hov = self.hover == "capturas"
        l.texto(46, 446, "Guardar capturas", "nombre", TEXTO)
        l.texto(46, 469, "Para revisar si algo falla.", "chico", SUAVE)
        self._toggle(l, 290, 450, c["guardar_capturas"], hov)
        l.zona("capturas", 28, 434, 324, 48)
        hov = self.hover == "carpeta"
        ancho = l.texto(46, 489, "Abrir carpeta", "chico", TEXTO if hov else SUAVE)
        l.linea_h(46, 504, ancho, (255, 255, 255, 150 if hov else 70))
        l.zona("carpeta", 42, 484, ancho + 8, 26)

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
        l.texto(30, 64, f"CLAVE DE {p.nombre.upper()}", "titulo", TEXTO)
        desc = "Pégala aquí. Se guarda cifrada y solo en esta computadora."
        for j, linea in enumerate(E.partir(desc, "cuerpo", self.e, 320 * self.e)):
            l.texto(30, 100 + j * 19, linea, "cuerpo", SUAVE)

        error = k["tipo"] == "error"
        if error:
            l.solido(28, 150, 324, 56, 16, (255, 107, 107, 24))
        l.vidrio(28, 150, 324, 56, 16, borde=(255, 140) if not error else (255, 220), relleno=(14, 5), grosor=1.2)
        l.zona("campo", 28, 150, 220, 56, cursor="xterm")
        if k["texto"]:
            visible = E.recortar(_enmascarar(k["texto"]), "cuerpo", self.e, 190 * self.e)
            ancho = l.texto_centrado_v(46, 178, visible, "cuerpo", TEXTO)
        else:
            ancho = -2.5
            l.texto_centrado_v(50, 178, p.prefijo + "…", "cuerpo", TENUE)
        if int(t * 2) % 2 == 0 and not k["verificando"]:
            l.solido(46 + ancho + 1.5, 169, 1.5, 18, 0.5, (255, 255, 255, 235))
        self._boton_vidrio(l, "pegar", 262, 162, 78, 32, "PEGAR")

        hov = self.hover == "sacar_clave"
        ancho = l.texto(30, 222, p.texto_clave, "chico", TEXTO if hov else SUAVE)
        l.icono("afuera", 34 + ancho, 221, 12, TEXTO if hov else SUAVE)
        l.linea_h(30, 237, ancho, (255, 255, 255, 150 if hov else 60))
        l.zona("sacar_clave", 26, 216, ancho + 26, 26)

        if k["verificando"]:
            l.texto(30, 264, "Revisando la clave" + "." * (int(t * 3) % 4), "cuerpo", SUAVE)
        elif k["msg"]:
            col = ERROR if k["tipo"] == "error" else TEXTO if k["tipo"] == "ok" else SUAVE
            for j, linea in enumerate(E.partir(k["msg"], "cuerpo", self.e, 320 * self.e)[:4]):
                l.texto(30, 264 + j * 19, linea, "cuerpo", col)

        if k["prov"] != "gemini" and not self.config.tiene_clave(k["prov"]):
            hov = self.hover == "usar_gemini"
            l.linea_h(30, 446, 320, (255, 255, 255, 30))
            l.texto(30, 460, "¿Sin saldo?", "chico", TENUE)
            ancho = l.texto(30, 478, "Usa Gemini Flash con una clave gratis", "chico", TEXTO if hov else SUAVE)
            l.linea_h(30, 493, ancho, (255, 255, 255, 150 if hov else 60))
            l.zona("usar_gemini", 26, 472, ancho + 8, 26)

        self._boton_vidrio(l, "cancelar_clave", 28, 514, 152, 54, "CANCELAR")
        self._boton_blanco(l, "guardar_clave", 192, 514, 160, 54, "GUARDAR", apagado=not k["texto"] or k["verificando"])
