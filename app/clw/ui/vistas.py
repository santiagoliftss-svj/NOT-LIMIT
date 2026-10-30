"""Pantallas de NO LIMIT: total black, vidrio y blanco liquido, como la pagina.

Todo es logica pura + dibujo con PIL (se puede probar sin ventana). Para que no se trabe:
- las piezas (textos, vidrios, pastillas) salen de cache,
- la pantalla fija se guarda y encima solo se pintan las piezas que se mueven,
- 'sucio' dice que rectangulos cambiaron, asi la ventana solo actualiza esos pedazos.
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
    "leyendo": ("Leyendo la pantalla…", "Esc cancela"),
    "pensando": ("Pensando la respuesta…", "Esc cancela"),
    "escribiendo": ("Escribiendo…", "No toques el teclado. Esc cancela"),
}
OCUPADO = ("leyendo", "pensando", "escribiendo")
SELLOS = {"claude": "Cl", "gemini": "Ge", "openai": "GPT"}

MARCA_W, MARCA_X, MARCA_Y = 250, 65, 20
MARCA_H = MARCA_W * 592 / 1400
REFLEJO_H = 30
MODELO = (24, 172, 332, 64)
BOTON = (85, 266, 210, 58)
ESTADO_Y = 360
ACTIVIDAD = (24, 400, 332, 138)
PIE_Y = 566

T_ENCENDER, T_ANILLO, T_APAGAR = 0.5, 0.45, 0.32
T_TRANSICION, T_CAPA, T_FILA = 0.28, 0.26, 0.4
CICLO_BRILLO, T_BRILLO = 4.5, 1.4   # cada cuanto cruza el reflejo del logo y cuanto tarda
VUELTA_HAZ = 3.4                    # segundos por vuelta de la luz del boton
VUELTA_GOTAS = 1.8

# lo que se repinta cuando algo se mueve (coordenadas logicas)
R_MARCA = (MARCA_X - 6, MARCA_Y - 6, MARCA_W + 12, MARCA_H + 12)
R_BOTON = (BOTON[0] - 30, BOTON[1] - 30, BOTON[2] + 60, BOTON[3] + 60 + 30)


def _enmascarar(t):
    if len(t) <= 12:
        return "•" * len(t)
    return t[:7] + "•" * 8 + t[-4:]


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0] + a[2], b[0] + b[2]) - min(a[0], b[0]),
            max(a[1] + a[3], b[1] + b[3]) - min(a[1], b[1]))


class Interfaz:
    """Controlador de pantallas. 'app' da las acciones de afuera:
       iniciar(), detener(), verificar_clave(prov, texto), leer_portapapeles(), abrir_url(u), abrir_carpeta(),
       actualizar()"""

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
        self.descarga = None               # % de la actualizacion que se esta bajando
        self.actualizacion_lista = False
        self.visible = True
        self.enfocado = True
        self.clave = {"prov": "claude", "texto": "", "msg": "", "tipo": "", "verificando": False,
                      "volver": "principal", "iniciar": False}
        self.zonas = []
        self.sucio = None                  # None = todo; lista de (x0, y0, x1, y1) en px = solo eso cambio
        self._base = None
        self._llave_datos = self._llave_inter = None
        self._quieto_llave = self._quieto = None
        self._ultima = None
        self._anim_antes = []
        self._anim_boton = None            # ("encender" | "apagar", t0)
        self._esconder_en = None
        self._trans = None                 # {"desde": img, "t0": t, "dir": 1 | -1}
        self._capa_t0 = -10.0
        self._t_fila = -10.0
        self._punto_estado = (ANCHO / 2, ESTADO_Y)
        self._textos = {}
        self._fase = 0.0                   # segundos dentro del ciclo del reflejo del logo
        self._t_brillo = None
        self._mouse = None
        self._esp = None
        self._panel = None                 # (llave, imagen, y, caja) de la hoja de modelos
        self._prev_completo = False
        self._por_calentar = None          # pantallas que se arman antes de verlas (ver precalentar)

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
        if t - self._capa_t0 < T_CAPA:
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
        elif tipo == "descarga":
            self.descarga = ev[1]
        elif tipo == "actualizacion_lista":
            self.nueva_version, self.descarga, self.actualizacion_lista = ev[1], None, True
        elif tipo == "actualizacion_error":
            self.descarga = None

    def debe_esconder(self, t=None):
        """True una sola vez cuando termina la animacion de INYECTAR (la ventana se va junto al reloj)."""
        t = self.reloj() if t is None else t
        if self._esconder_en is not None and t >= self._esconder_en:
            self._esconder_en = None
            return self.encendido()
        return False

    def precalentar(self):
        """Arma una vez, sin mostrarlas, las pantallas que todavia no se han visto (Ajustes, la clave), para que
        el primer clic no espere a hacer sus piezas. La ventana lo llama de a un paso cuando esta quieta.
        Devuelve True mientras queden pasos."""
        if self._por_calentar is None:
            prov = self.modelo_actual().proveedor
            pasos = [lambda: self._ajustes(self._lienzo_suelto())]
            for p in dict.fromkeys((prov, "gemini")):
                for texto in ("", "x" * 16):
                    k = dict(self.clave, prov=p, texto=texto, msg="", tipo="", verificando=False)
                    pasos.append(lambda k=k: self._pantalla_clave(self._lienzo_suelto(), self.reloj(), k))
            self._por_calentar = pasos
        if self._por_calentar:
            self._por_calentar.pop(0)()
        return bool(self._por_calentar)

    def _lienzo_suelto(self):
        return Lienzo(self.e, base=E.foco(self.ancho_px, self.alto_px))

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
        elif zid == "pagina":
            self.app.abrir_url(version.PAGINA)
        elif zid == "actualizar":
            if self.actualizacion_lista and hasattr(self.app, "actualizar"):
                self.app.actualizar()
            else:
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

    def _especular_px(self):
        """Donde va el brillo del logo (px dentro del logo, redondeado) o None."""
        if self._mouse is None or self.pantalla != "principal" or self.capa or not self.enfocado:
            return None
        mx, my = self._mouse
        if my > MARCA_Y + MARCA_H + 46 or mx < MARCA_X - 50 or mx > MARCA_X + MARCA_W + 50:
            return None
        x = (mx - MARCA_X) * self.e
        y = (my - MARCA_Y) * self.e
        w, h = MARCA_W * self.e, MARCA_H * self.e
        x, y = max(-40 * self.e, min(w + 40 * self.e, x)), max(-40 * self.e, min(h + 40 * self.e, y))
        q = max(4, round(6 * self.e))
        return int(x // q * q), int(y // q * q)

    def mover(self, x, y):
        zid, cursor = self._zona_en(x, y)
        cambio = zid != self.hover
        self.hover, self.cursor = zid, cursor
        self._mouse = (x, y)
        esp = self._especular_px()
        if esp != self._esp:
            cambio = True
        return cambio

    def salir(self):
        cambio = self.hover is not None or self.presionado is not None or self._mouse is not None
        self.hover = self.presionado = None
        self._mouse = None
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
    def _datos(self, t):
        k = self.clave
        extra = ()
        if self.pantalla == "clave":
            extra = (k["prov"], k["texto"], k["msg"], k["tipo"], k["verificando"], int(t * 2) % 2,
                     int(t * 3) % 4 if k["verificando"] else 0)
        c = self.config
        fila_animada = t - self._t_fila < T_FILA
        return (self.pantalla, self.capa, self.estado, tuple(self.actividad), fila_animada, c["modelo"], c["modo_preciso"],
                c["guardar_capturas"], tuple(sorted(c["claves"].keys())), self.nueva_version, self.descarga,
                self.actualizacion_lista) + extra

    def _rect_zona(self, zid):
        if zid is None:
            return None
        if zid in ("cerrar_capa", "panel", "campo"):
            return (0, 0, 0, 0)                 # sin cambio visual al pasar el mouse
        if zid == "agregar_clave":
            zid = "modelo"                      # la tarjeta entera se ilumina
        if zid == "inyectar":
            if self.encendido():
                return R_BOTON
            return (BOTON[0] - 6, BOTON[1] - 6, BOTON[2] + 12, BOTON[3] + 12)
        for z, r, _ in self.zonas:
            if z == zid:
                return (r[0] - 12, r[1] - 12, r[2] + 24, r[3] + 24 + (70 if zid == "guardar_clave" else 0))
        return None

    def _a_px(self, rects):
        """Rectangulos logicos -> px, sin repetidos y juntando los que se enciman."""
        out = []
        for x, y, w, h in rects:
            x0, y0 = max(0, math.floor(x * self.e)), max(0, math.floor(y * self.e))
            x1, y1 = min(self.ancho_px, math.ceil((x + w) * self.e)), min(self.alto_px, math.ceil((y + h) * self.e))
            if x1 > x0 and y1 > y0:
                out.append((x0, y0, x1, y1))
        juntos = True
        while juntos and len(out) > 1:
            juntos = False
            for i in range(len(out)):
                for j in range(i + 1, len(out)):
                    a, b = out[i], out[j]
                    if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
                        out[i] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                        del out[j]
                        juntos = True
                        break
                if juntos:
                    break
        return out

    def render(self, t=None):
        t = self.reloj() if t is None else t
        datos = self._datos(t)
        inter = (self.hover, self.presionado)
        sucio_fijo = []
        if datos != self._llave_datos or inter != self._llave_inter or self._base is None:
            solo_mouse = datos == self._llave_datos and self._base is not None
            antes = self._llave_inter
            l = Lienzo(self.e, base=E.foco(self.ancho_px, self.alto_px))
            if self.pantalla == "principal":
                self._principal(l, t)
            elif self.pantalla == "ajustes":
                self._ajustes(l)
            elif self.pantalla == "clave":
                self._pantalla_clave(l, t)
            if self.capa == "modelos":
                self._zonas_modelos(l)
            if solo_mouse:
                for zid in set((antes or (None, None)) + inter):
                    r = self._rect_zona(zid)
                    if r is None and zid is not None:
                        sucio_fijo = None
                        break
                    if r is not None:
                        sucio_fijo.append(r)
            else:
                sucio_fijo = None
            self.zonas = l.zonas
            self._base, self._llave_datos, self._llave_inter = l.im, datos, inter

        if not self.animando(t):
            llave_q = (datos, inter, "quieto")
            if llave_q == self._quieto_llave and self._ultima is self._quieto:
                self.sucio = []
                return self._quieto
            l = Lienzo(self.e, base=self._base)
            self._encima(l, t, quieto=True)
            self._quieto, self._quieto_llave = l.im, llave_q
            if self.pantalla == "principal" and self.capa is None:
                self._panel_modelos()
            completo = sucio_fijo is None or self._prev_completo
            self.sucio = None if completo else self._a_px(sucio_fijo + self._anim_antes)
            self._anim_antes, self._prev_completo = [], False
            self._ultima = self._quieto
            return self._quieto

        l = Lienzo(self.e, base=self._base)
        movidos = self._encima(l, t, quieto=False)
        im = l.im
        if self.pantalla == "principal" and self.capa is None and not self._anim_activa(t):
            self._panel_modelos()
        este_completo = "todo" in movidos
        if self._trans:
            p = (t - self._trans["t0"]) / T_TRANSICION
            if p >= 1:
                self._trans = None
            else:
                im = self._mezclar(self._trans["desde"], im, E.suave(p), self._trans["dir"])
                este_completo = True
        completo = sucio_fijo is None or este_completo or self._prev_completo
        rects = [r for r in movidos if r != "todo"]
        self.sucio = None if completo else self._a_px(sucio_fijo + rects + self._anim_antes)
        self._anim_antes, self._prev_completo = rects, este_completo
        self._ultima = im
        return im

    def _mezclar(self, viejo, nuevo, p, direccion):
        """El viejo se va hacia un lado y se apaga; el nuevo llega del otro lado."""
        d = 22 * self.e
        a = Image.new("RGBA", nuevo.size, NEGRO + (255,))
        b = a.copy()
        dv, dn = int(round(-direccion * d * p)), int(round(direccion * d * (1 - p)))
        a.paste(viejo, (dv, 0))
        b.paste(nuevo, (dn, 0))
        return Image.blend(a, b, p)

    # ---------------------------------------------------------------- piezas que se mueven
    def _encima(self, l, t, quieto):
        """Pinta lo que se mueve. Devuelve los rectangulos (logicos) que tocaron, o 'todo'."""
        movidos = []
        if self.pantalla == "principal":
            if self._marca_viva(l, t, quieto):
                movidos.append(R_MARCA)
            r = self._boton(l, t, quieto)
            if r:
                movidos.append(r)
            if self._punto(l, t, quieto):
                x, y = self._punto_estado
                movidos.append((x - 14, y - 14, 28, 28))
            if not quieto and t - self._t_fila < T_FILA and self.actividad:
                self._fila(l, 0, self.actividad[0], E.suave((t - self._t_fila) / T_FILA))
                movidos.append((ACTIVIDAD[0], ACTIVIDAD[1] + 4, ACTIVIDAD[2], 36))
        elif self.pantalla == "clave" and not quieto and self.hover == "guardar_clave" and self._guardar_activo():
            self._gotas_guardar(l, t)
            movidos.append(self._rect_zona("guardar_clave") or (0, 0, ANCHO, ALTO))
        if self.capa == "modelos":
            p = 1.0 if quieto else E.suave((t - self._capa_t0) / T_CAPA)
            self._modelos(l, p)
            if p < 1:
                movidos.append("todo")
        return movidos

    def _marca_viva(self, l, t, quieto):
        """Reflejo que cruza el logo de vez en cuando + brillo que sigue al mouse."""
        tocado = False
        ancho = l.px(MARCA_W)
        X, Y = l.px(MARCA_X), l.px(MARCA_Y)
        if quieto:
            self._t_brillo = None
        else:
            if self._t_brillo is not None:
                self._fase = (self._fase + max(0.0, min(0.1, t - self._t_brillo))) % CICLO_BRILLO
            self._t_brillo = t
            if self._fase < T_BRILLO:
                paso = int(E.suave(self._fase / T_BRILLO) * (E.PASOS_BRILLO - 1))
                l.pegar_px(E.brillo_marca(ancho, paso), X, Y)
                tocado = True
        esp = None if quieto or not self.enfocado else self._especular_px()
        if esp is not None:
            l.pegar_px(E.especular(ancho, esp[0], esp[1], l.px(46)), X, Y)
            tocado = True
        if esp != self._esp:
            tocado = True
        self._esp = esp
        return tocado

    def _boton(self, l, t, quieto):
        x, y, w, h = BOTON
        X, Y, W, H = l.caja_px(x, y, w, h)
        R = H // 2
        hov = self.hover == "inyectar"
        pres = self.presionado == "inyectar"
        encendido = self.encendido()
        animado = False

        relleno = 1.0 if encendido else 0.0
        anillo = None
        gota = None
        encendiendo = False
        if self._anim_boton:
            tipo, t0 = self._anim_boton
            dt = t - t0
            if quieto:
                self._anim_boton = None
            elif tipo == "encender":
                encendiendo, animado = True, True
                relleno = E.ida_y_vuelta(dt / T_ENCENDER)
                if dt > T_ENCENDER:
                    anillo = E.suave((dt - T_ENCENDER) / T_ANILLO)
                    gota = min(E.GOTAS_N - 1, int((dt - T_ENCENDER) / 0.6 * E.GOTAS_N * .62))
                if dt > T_ENCENDER + T_ANILLO:
                    self._anim_boton = None
            else:
                animado = True
                relleno = 1 - E.ida_y_vuelta(dt / T_APAGAR)
                if dt > T_APAGAR:
                    self._anim_boton = None

        if pres:
            X, Y, W, H = X + round(W * .015), Y + round(H * .03), W - round(W * .03), H - round(H * .06)
            R = H // 2
        lleno = encendido and relleno >= 1 and anillo is None

        bx, by, bw, bh = BOTON
        if lleno:
            # pastilla blanca liquida: DETENER (brilla y escurre gotas con el mouse encima)
            fase = 0.5 if quieto else 0.5 + 0.5 * math.sin(t * 2 * math.pi / (1.2 if self.ocupado() else 2.8))
            brillo, pad = E.resplandor(W, H, R, max(4, l.px(10)), int(round(fase * 10)))
            l.pegar_px(brillo, X - pad, Y - pad)
            if hov and not quieto:
                cuadro = int((t % VUELTA_GOTAS) / VUELTA_GOTAS * E.GOTAS_N) % E.GOTAS_N
                capa, gp = E.gotas(W, H, self.e, cuadro)
                l.pegar_px(capa, X - gp, Y - gp)
            l.pegar_px(E.liquido(W, H, R, 2 if pres else 1 if hov else 0), X, Y)
            l.pegar_px(self._texto_capa(W, H, "DETENER", NEGRO), X, Y)
            if quieto and not animado:
                return None
            return (bx - 30, by - 30, bw + 60, bh + 60 + (30 if hov else 0))

        if anillo is not None and anillo < 1:
            k = 1 + 0.34 * anillo
            Wk, Hk = int(W * k), int(H * k)
            a = int(235 * (1 - anillo))
            aro = E.vidrio(Wk, Hk, Hk // 2, borde=(a, a), relleno=(0, 0), grosor=1.6 * self.e)
            l.pegar_px(aro, X - (Wk - W) / 2, Y - (Hk - H) / 2)
        if gota is not None:
            capa, gp = E.gotas(W, H, self.e, gota, una=True)
            l.pegar_px(capa, X - gp, Y - gp)

        capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if relleno < 1:
            borde = (255, 175) if hov else (225, 110)
            fondo = (46, 18) if pres else (30, 12) if hov else (16, 5)
            capa.alpha_composite(E.vidrio(W, H, R, borde=borde, relleno=fondo, grosor=1.3 * self.e))
            if not quieto and not encendido and not encendiendo:
                paso = int((t % VUELTA_HAZ) / VUELTA_HAZ * 72)
                capa.alpha_composite(E.haz_borde(W, H, R, 1.3 * self.e, paso))
                animado = True
        texto = "ACTIVO" if anillo is not None else "DETENER" if (encendido and not encendiendo) else "INYECTAR"
        blanco_txt = self._texto_capa(W, H, texto, BLANCO)
        if relleno > 0:
            corte = Image.new("L", (W, H), 0)
            ImageDraw.Draw(corte).rectangle((0, 0, int(W * relleno), H), fill=255)
            mascara = Image.new("L", (W, H), 0)
            mascara.paste(E.forma(W, H, R), (0, 0), corte)
            pastilla = E.liquido(W, H, R).copy()
            pastilla.putalpha(mascara)
            capa.alpha_composite(pastilla)
            negro_txt = self._texto_capa(W, H, texto, NEGRO)
            capa.alpha_composite(Image.composite(negro_txt, blanco_txt, mascara))
        else:
            capa.alpha_composite(blanco_txt)
        l.pegar_px(capa, X, Y)
        if not animado:
            return None
        if anillo is not None or gota is not None or self._anim_boton:
            return (bx - 40, by - 40, bw + 80, bh + 80 + 30)
        return (bx - 4, by - 4, bw + 8, bh + 8)

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
            l.punto(x, y, 3.6, BLANCO, alfa=160, anillo_solo=True)
            return False
        if not quieto:
            fase = 0.5 + 0.5 * math.sin(t * 2 * math.pi / (1.0 if self.ocupado() else 2.0))
            l.punto(x, y, 3.6 + 4 * fase, BLANCO, alfa=int(25 + 55 * (1 - fase)))
        l.punto(x, y, 3.6, BLANCO)
        return not quieto

    # ---------------------------------------------------------------- principal
    def _principal(self, l, t):
        c = self.config
        logo = E.marca(l.px(MARCA_W))
        X, Y = l.px(MARCA_X), l.px(MARCA_Y)
        l.pegar_px(E.reflejo_marca(logo.width, l.px(REFLEJO_H), self.e), X, Y + logo.height - l.px(1))
        l.pegar_px(E.piso(l.px(MARCA_W - 30)), X + l.px(15), Y + logo.height - l.px(1))
        l.pegar_px(logo, X, Y)

        # modelo
        m = self.modelo_actual()
        tiene = c.tiene_clave(m.proveedor)
        x, y, w, h = MODELO
        hov = self.hover in ("modelo", "agregar_clave")
        pres = self.presionado == "modelo"
        l.vidrio(x, y, w, h, 20, borde=(210, 60) if hov else (135, 34), relleno=(30, 8) if pres else (20, 6) if hov else (11, 3))
        l.pegar(E.sello(SELLOS[m.proveedor], 40, self.e), x + 12, y + 12)
        prov = PROVEEDORES[m.proveedor].nombre
        l.texto(x + 64, y + 15, f"{prov} · {m.nota}" if tiene else prov, "mini", SUAVE)
        l.texto(x + 64, y + 31, m.corto or m.nombre, "nombre", TEXTO)
        l.icono("abajo", x + w - 30, y + 25, 14, TEXTO if hov else SUAVE)
        l.zona("modelo", x, y, w, h)
        if not tiene:
            ancho = E.medir("Agregar clave", "mini", self.e) / self.e + 24
            cx = x + w - 42 - ancho
            l.liquido(cx, y + 20, ancho, 24, 12, 1 if self.hover == "agregar_clave" else 0)
            l.texto_centrado_v(cx + ancho / 2, y + 32, "Agregar clave", "mini", NEGRO, ancla="ma")
            l.zona("agregar_clave", cx - 4, y + 14, ancho + 8, 36)

        l.zona("inyectar", *BOTON)

        # estado
        titulo, ayuda = ESTADOS.get(self.estado, ESTADOS["apagado"])
        ancho = E.medir(titulo, "cuerpo", self.e) / self.e
        x0 = ANCHO / 2 - (ancho + 16) / 2
        self._punto_estado = (x0 + 4, ESTADO_Y)
        l.texto_centrado_v(x0 + 16, ESTADO_Y, titulo, "cuerpo", TEXTO if self.encendido() else SUAVE)
        l.texto(ANCHO / 2, ESTADO_Y + 16, ayuda, "chico", TENUE, ancla="ma")

        # actividad
        x, y, w, h = ACTIVIDAD
        l.vidrio(x, y, w, h, 20, borde=(80, 18), relleno=(9, 2))
        if not self.actividad:
            l.texto(ANCHO / 2, y + h / 2 - 8, "Aquí vas a ver lo que va contestando", "cuerpo", TENUE, ancla="ma")
        fila_animada = t - self._t_fila < T_FILA
        for i, fila in enumerate(self.actividad):
            if i == 0 and fila_animada:
                continue
            self._fila(l, i, fila, 1.0)

        # pie
        hov = self.hover == "ajustes"
        l.icono("engrane", 26, PIE_Y - 7, 14, TEXTO if hov else SUAVE)
        l.texto_centrado_v(46, PIE_Y, "Ajustes", "chico", TEXTO if hov else SUAVE)
        l.zona("ajustes", 20, PIE_Y - 14, 92, 28)
        self._chip_version(l)

    def _chip_version(self, l):
        hov = self.hover == "actualizar"
        v = self.nueva_version
        if self.actualizacion_lista and v:
            txt = f"Actualizar a v{v}"
            ancho = E.medir(txt, "mini", self.e) / self.e + 26
            l.liquido(356 - ancho, PIE_Y - 12, ancho, 24, 12, 1 if hov else 0)
            l.texto_centrado_v(356 - ancho / 2, PIE_Y, txt, "mini", NEGRO, ancla="ma")
            l.zona("actualizar", 352 - ancho, PIE_Y - 16, ancho + 8, 32)
        elif self.descarga is not None and v:
            txt = f"Bajando v{v} · {int(self.descarga)}%"
            ancho = E.medir(txt, "mini", self.e) / self.e + 26
            l.vidrio(356 - ancho, PIE_Y - 12, ancho, 24, 12, borde=(150, 70), relleno=(14, 6))
            l.texto_centrado_v(356 - ancho / 2, PIE_Y, txt, "mini", SUAVE, ancla="ma")
        elif v:
            txt = f"Hay v{v}"
            ancho = E.medir(txt, "mini", self.e) / self.e + 26
            l.vidrio(356 - ancho, PIE_Y - 12, ancho, 24, 12, borde=(220, 120) if hov else (160, 80), relleno=(18, 8))
            l.texto_centrado_v(356 - ancho / 2, PIE_Y, txt, "mini", TEXTO, ancla="ma")
            l.zona("actualizar", 352 - ancho, PIE_Y - 16, ancho + 8, 32)
        else:
            l.texto_centrado_v(354, PIE_Y, f"v{version.VERSION}", "mini", TENUE, ancla="ra")

    def _fila(self, l, i, fila, p):
        hora, texto, tipo = fila
        yy = ACTIVIDAD[1] + 16 + i * 30 - (1 - p) * 8
        base = 255 if i == 0 else 200 if i == 1 else 150 if i == 2 else 110
        alfa = int(base * p)
        col = ERROR if tipo == "error" else TEXTO if tipo == "ok" else SUAVE
        l.texto(42, yy + 2, hora, "mini", TENUE, alfa=alfa)
        l.texto(86, yy, E.recortar(texto, "cuerpo", self.e, 256 * self.e), "cuerpo", col, alfa=alfa)

    # ---------------------------------------------------------------- hoja de modelos
    def _grupos(self):
        grupos = []
        for m in MODELOS:
            if not grupos or grupos[-1][0] != m.proveedor:
                grupos.append((m.proveedor, []))
            grupos[-1][1].append(m)
        alto = 70 + sum(28 + 48 * len(ms) for _, ms in grupos) + 10
        return grupos, alto

    def _zonas_modelos(self, l):
        grupos, alto = self._grupos()
        y = ALTO - alto - 10
        l.zona("cerrar_capa", 0, 0, ANCHO, ALTO, cursor="arrow")
        l.zona("panel", 10, y, 360, alto, cursor="arrow")
        yy = y + 70
        for prov, ms in grupos:
            yy += 28
            for m in ms:
                l.zona("modelo:" + m.id, 18, yy, 344, 46)
                yy += 48

    def _panel_modelos(self):
        """La hoja ya dibujada (cache por mouse encima / modelo elegido / claves)."""
        grupos, alto = self._grupos()
        y = ALTO - alto - 10
        actual = self.config["modelo"]
        llave = (actual, tuple(sorted(self.config["claves"].keys())), self.e)
        if self._panel and self._panel[0] == llave:
            return self._panel[1], y
        p = Lienzo(self.e, base=Image.new("RGBA", (round(ANCHO * self.e), round(ALTO * self.e)), (0, 0, 0, 0)))
        p.solido(10, y, 360, alto, 28, (8, 8, 9, 255))
        p.vidrio(10, y, 360, alto, 28, borde=(150, 36), relleno=(12, 2))
        p.solido(ANCHO / 2 - 18, y + 9, 36, 4, 2, (255, 255, 255, 60))
        p.texto_plata(28, y + 26, "Elige tu IA", "subtitulo")
        yy = y + 70
        for prov, ms in grupos:
            p.texto(30, yy + 8, PROVEEDORES[prov].nombre.upper(), "seccion", TENUE)
            if not self.config.tiene_clave(prov):
                p.texto(350, yy + 8, "SIN CLAVE", "seccion", TENUE, ancla="ra")
            yy += 28
            for m in ms:
                sel = m.id == actual
                if sel:
                    p.solido(18, yy, 344, 46, 14, (255, 255, 255, 22))
                p.pegar(E.sello(SELLOS[prov], 30, self.e), 28, yy + 8)
                p.texto_centrado_v(70, yy + 23, m.nombre, "nombre", BLANCO if sel else (220, 220, 224))
                derecha = 348
                if sel:
                    p.icono("palomita", 334, yy + 16, 14, BLANCO)
                    derecha = 326
                p.texto_centrado_v(derecha, yy + 23, m.nota, "chico", SUAVE if sel else TENUE, ancla="ra")
                yy += 48
        caja = p.im.getbbox() or (0, 0, 1, 1)
        img = p.im.crop(caja)
        self._panel = (llave, img, y, caja)
        return img, y

    def _modelos(self, l, p):
        l.oscurecer(int(200 * p))
        img, y = self._panel_modelos()
        caja = self._panel[3]
        k = min(1.0, 2 * p)
        if k < 1:
            img = img.copy()
            img.putalpha(img.getchannel("A").point(lambda a: int(a * k)))
        dy = (1 - p) * 46 * self.e
        l.pegar_px(img, caja[0], caja[1] + dy)
        hov = self.hover or ""
        if hov.startswith("modelo:") and p >= 1 and hov != "modelo:" + self.config["modelo"]:
            for z, (zx, zy, zw, zh), _ in self.zonas:
                if z == hov:
                    l.solido(zx, zy, zw, zh, 14, (255, 255, 255, 16))
                    break

    # ---------------------------------------------------------------- ajustes
    def _volver(self, l, zid):
        hov = self.hover == zid
        l.icono("atras", 18, 22, 16, TEXTO if hov else SUAVE)
        l.texto_centrado_v(36, 30, "Volver", "chico", TEXTO if hov else SUAVE)
        l.zona(zid, 12, 14, 92, 32)

    def _toggle(self, l, x, y, encendido, hov):
        if encendido:
            l.liquido(x, y, 48, 28, 14, 1 if hov else 0)
            l.punto(x + 34, y + 14, 10, NEGRO)
        else:
            l.vidrio(x, y, 48, 28, 14, borde=(210, 130) if hov else (150, 80), relleno=(16, 6))
            l.punto(x + 14, y + 14, 9, (210, 210, 214) if hov else (160, 160, 165))

    def _boton_vidrio(self, l, zid, x, y, w, h, texto):
        hov = self.hover == zid
        pres = self.presionado == zid
        if pres:
            x, y, w, h = x + 1.5, y + 1, w - 3, h - 2
        l.vidrio(x, y, w, h, h / 2, borde=(245, 160) if hov else (195, 95),
                 relleno=(44, 18) if pres else (28, 10) if hov else (12, 4), grosor=1.2)
        l.texto_centrado_v(x + w / 2, y + h / 2, texto, "boton_chico", TEXTO, ancla="ma")
        l.zona(zid, x, y, w, h)

    def _boton_blanco(self, l, zid, x, y, w, h, texto, apagado=False):
        if apagado:
            l.solido(x, y, w, h, h / 2, (255, 255, 255, 30))
            l.texto_centrado_v(x + w / 2, y + h / 2, texto, "boton_chico", TENUE, ancla="ma")
            l.zona(zid, x, y, w, h)
            return
        hov = self.hover == zid
        pres = self.presionado == zid
        if pres:
            x, y, w, h = x + 1.5, y + 1, w - 3, h - 2
        l.liquido(x, y, w, h, h / 2, 2 if pres else 1 if hov else 0)
        l.texto_centrado_v(x + w / 2, y + h / 2, texto, "boton_chico", NEGRO, ancla="ma")
        l.zona(zid, x, y, w, h)

    def _ajustes(self, l):
        c = self.config
        self._volver(l, "volver")
        l.texto_plata(24, 56, "Ajustes", "titulo")

        l.texto(26, 110, "TUS CLAVES", "seccion", TENUE)
        l.vidrio(24, 128, 332, 174, 20, borde=(95, 22), relleno=(10, 3))
        for i, prov in enumerate(("claude", "gemini", "openai")):
            y = 128 + i * 58
            p = PROVEEDORES[prov]
            tiene = c.tiene_clave(prov)
            l.pegar(E.sello(SELLOS[prov], 34, self.e), 40, y + 12)
            l.texto(86, y + 13, p.nombre, "nombre", TEXTO)
            if tiene:
                l.icono("palomita", 85, y + 35, 12, SUAVE)
                l.texto(101, y + 35, "Guardada", "chico", SUAVE)
            else:
                l.texto(86, y + 35, "Gratis en Google AI Studio" if prov == "gemini" else "Sin clave", "chico", TENUE)
            self._boton_vidrio(l, "clave:" + prov, 252, y + 14, 90, 30, "CAMBIAR" if tiene else "AGREGAR")
            if i < 2:
                l.linea_h(40, y + 58, 300, (255, 255, 255, 26))

        l.texto(26, 320, "CÓMO CONTESTA", "seccion", TENUE)
        l.vidrio(24, 338, 332, 168, 20, borde=(95, 22), relleno=(10, 3))
        hov = self.hover == "preciso"
        l.texto(40, 352, "Modo preciso", "nombre", TEXTO)
        for j, linea in enumerate(E.partir("Piensa antes de contestar. Se equivoca menos y tarda un poquito más.",
                                           "chico", self.e, 222 * self.e)):
            l.texto(40, 375 + j * 16, linea, "chico", SUAVE)
        self._toggle(l, 294, 358, c["modo_preciso"], hov)
        l.zona("preciso", 24, 338, 332, 76)
        l.linea_h(40, 416, 300, (255, 255, 255, 26))

        hov = self.hover == "capturas"
        l.texto(40, 430, "Guardar capturas", "nombre", TEXTO)
        l.texto(40, 453, "Para revisar si algo falla.", "chico", SUAVE)
        self._toggle(l, 294, 434, c["guardar_capturas"], hov)
        l.zona("capturas", 24, 418, 332, 52)
        hov = self.hover == "carpeta"
        ancho = l.texto(40, 476, "Abrir carpeta", "chico", TEXTO if hov else SUAVE)
        l.linea_h(40, 491, ancho, (255, 255, 255, 150 if hov else 70))
        l.zona("carpeta", 36, 470, ancho + 8, 28)

        hov = self.hover == "pagina"
        ancho = l.texto_centrado_v(24, PIE_Y, "Página de NO LIMIT", "chico", TEXTO if hov else SUAVE)
        l.icono("afuera", 28 + ancho, PIE_Y - 6, 12, TEXTO if hov else SUAVE)
        l.zona("pagina", 18, PIE_Y - 14, ancho + 30, 28)
        self._chip_version(l)

    # ---------------------------------------------------------------- clave
    def _guardar_activo(self, k=None):
        k = k or self.clave
        return bool(k["texto"]) and not k["verificando"]

    def _gotas_guardar(self, l, t):
        X, Y, W, H = l.caja_px(192, 514, 164, 54)
        cuadro = int((t % VUELTA_GOTAS) / VUELTA_GOTAS * E.GOTAS_N) % E.GOTAS_N
        capa, gp = E.gotas(W, H, self.e, cuadro)
        l.pegar_px(capa, X - gp, Y - gp)
        pres = self.presionado == "guardar_clave"
        l.pegar_px(E.liquido(W, H, H // 2, 2 if pres else 1), X, Y)
        l.texto_centrado_v(192 + 82, 514 + 27, "GUARDAR", "boton_chico", NEGRO, ancla="ma")

    def _pantalla_clave(self, l, t, k=None):
        k = k or self.clave
        p = PROVEEDORES[k["prov"]]
        self._volver(l, "volver_clave")
        titulo = f"Tu clave de {p.nombre}"
        rol = "titulo" if E.medir(titulo, "titulo", self.e) <= 332 * self.e else "titulo_m"
        l.texto_plata(24, 56, titulo, rol)
        desc = "Pégala aquí. Se guarda cifrada y solo en esta computadora."
        for j, linea in enumerate(E.partir(desc, "cuerpo", self.e, 330 * self.e)):
            l.texto(24, 100 + j * 19, linea, "cuerpo", SUAVE)

        error = k["tipo"] == "error"
        if error:
            l.solido(24, 150, 332, 58, 18, (255, 105, 97, 22))
        l.vidrio(24, 150, 332, 58, 18, borde=(255, 140) if not error else (255, 220), relleno=(14, 5), grosor=1.2)
        l.zona("campo", 24, 150, 226, 58, cursor="xterm")
        if k["texto"]:
            visible = E.recortar(_enmascarar(k["texto"]), "cuerpo", self.e, 196 * self.e)
            ancho = l.texto_centrado_v(42, 179, visible, "cuerpo", TEXTO)
        else:
            ancho = -2.5
            l.icono("candado", 42, 172, 13, TENUE)
            l.texto_centrado_v(62, 179, p.prefijo + "…", "cuerpo", TENUE)
        if int(t * 2) % 2 == 0 and not k["verificando"] and k["texto"]:
            l.solido(42 + ancho + 1.5, 170, 1.5, 18, 0.5, (255, 255, 255, 235))
        self._boton_vidrio(l, "pegar", 260, 163, 84, 32, "PEGAR")

        hov = self.hover == "sacar_clave"
        ancho = l.texto(24, 226, p.texto_clave, "chico", TEXTO if hov else SUAVE)
        l.icono("afuera", 28 + ancho, 225, 12, TEXTO if hov else SUAVE)
        l.linea_h(24, 241, ancho, (255, 255, 255, 150 if hov else 60))
        l.zona("sacar_clave", 20, 220, ancho + 26, 26)

        if k["verificando"]:
            l.texto(24, 268, "Revisando la clave" + "." * (int(t * 3) % 4), "cuerpo", SUAVE)
        elif k["msg"]:
            col = ERROR if k["tipo"] == "error" else TEXTO if k["tipo"] == "ok" else SUAVE
            for j, linea in enumerate(E.partir(k["msg"], "cuerpo", self.e, 328 * self.e)[:4]):
                l.texto(24, 268 + j * 19, linea, "cuerpo", col)

        if k["prov"] != "gemini" and not self.config.tiene_clave(k["prov"]):
            hov = self.hover == "usar_gemini"
            l.linea_h(24, 446, 332, (255, 255, 255, 28))
            l.texto(24, 460, "¿Sin saldo?", "chico", TENUE)
            ancho = l.texto(24, 478, "Usa Gemini Flash con una clave gratis", "chico", TEXTO if hov else SUAVE)
            l.linea_h(24, 493, ancho, (255, 255, 255, 150 if hov else 60))
            l.zona("usar_gemini", 20, 472, ancho + 8, 26)

        self._boton_vidrio(l, "cancelar_clave", 24, 514, 156, 54, "CANCELAR")
        self._boton_blanco(l, "guardar_clave", 192, 514, 164, 54, "GUARDAR", apagado=not self._guardar_activo(k))
