"""Autoprueba de NO LIMIT.app en una Mac de verdad (la corre GitHub en una Mac M1).

Abre la ventana nativa, revisa que se vea (nitida y derecha), mide lo que tarda cada cuadro, prueba el icono de
la barra de arriba y hace la prueba de punta a punta: Option + clic de verdad sobre ventanas de prueba, captura,
IA falsa, clic y escritura. Todo corre en el hilo de AppKit con relojes (como la de Windows con Tk).
"""

import json
import os
import shutil
import tempfile
import threading
import time
import traceback

import objc
from AppKit import (NSBackingStoreBuffered, NSColor, NSFont, NSImage, NSImageView, NSTextField, NSView, NSWindow,
                    NSWindowStyleMaskTitled)
from Foundation import NSMakeRect, NSMakeSize
from PIL import Image
import Quartz as Q

from . import permisos
from .ventana import _alto_principal, _cgimagen


# ---------------------------------------------------------------- ayudas

def _pil(cg):
    """CGImage -> PIL (las capturas de ventanas vienen en BGRA)."""
    w, h = Q.CGImageGetWidth(cg), Q.CGImageGetHeight(cg)
    fila = Q.CGImageGetBytesPerRow(cg)
    datos = bytes(Q.CGDataProviderCopyData(Q.CGImageGetDataProvider(cg)))
    return Image.frombuffer("RGBA", (w, h), datos, "raw", "BGRA", fila, 1).convert("RGB")


def foto_ventana(numero):
    """Imagen de una ventana de esta app (no necesita permiso de Grabacion de pantalla)."""
    try:
        cg = Q.CGWindowListCreateImage(Q.CGRectNull, Q.kCGWindowListOptionIncludingWindow, numero,
                                       Q.kCGWindowImageBoundsIgnoreFraming | Q.kCGWindowImageBestResolution)
        if cg is not None:
            return _pil(cg)
    except Exception:
        pass
    fd, ruta = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        import subprocess
        subprocess.run(["/usr/sbin/screencapture", "-x", "-o", "-l", str(numero), ruta], timeout=15)
        im = Image.open(ruta)
        im.load()
        return im.convert("RGB")
    finally:
        os.remove(ruta)


def option_clic(x, y):
    """Option + clic de verdad en (x, y) puntos (como si lo hiciera el usuario)."""
    time.sleep(0.4)
    p = Q.CGPointMake(x, y)
    for tipo, banderas in ((Q.kCGEventMouseMoved, 0), (Q.kCGEventLeftMouseDown, Q.kCGEventFlagMaskAlternate),
                           (Q.kCGEventLeftMouseUp, Q.kCGEventFlagMaskAlternate)):
        ev = Q.CGEventCreateMouseEvent(None, tipo, p, Q.kCGMouseButtonLeft)
        Q.CGEventSetFlags(ev, banderas)
        if tipo != Q.kCGEventMouseMoved:
            Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventClickState, 1)
        Q.CGEventPost(Q.kCGHIDEventTap, ev)
        time.sleep(0.12)


class _VistaClics(NSView):
    """Muestra una imagen y anota donde le dan clic (coordenadas desde arriba, en puntos)."""

    def initWithFrame_(self, marco):
        self = objc.super(_VistaClics, self).initWithFrame_(marco)
        if self is None:
            return None
        self.imagen = None
        self.clics = []
        return self

    def isFlipped(self):
        return True

    def acceptsFirstMouse_(self, evento):
        return True

    def drawRect_(self, rect):
        if self.imagen is not None:
            from AppKit import NSCompositingOperationCopy
            from Foundation import NSZeroRect
            self.imagen.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
                self.bounds(), NSZeroRect, NSCompositingOperationCopy, 1.0, True, None)

    def mouseDown_(self, evento):
        p = self.convertPoint_fromView_(evento.locationInWindow(), None)
        self.clics.append((p.x, p.y))


def _ventana_prueba(x, y, w, h, titulo):
    """Ventana de prueba con su esquina de arriba en (x, y) puntos (desde arriba de la pantalla)."""
    alto = _alto_principal()
    marco = NSMakeRect(x, alto - y - h, w, h)
    v = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(marco, NSWindowStyleMaskTitled,
                                                                     NSBackingStoreBuffered, False)
    v.setTitle_(titulo)
    v.setReleasedWhenClosed_(False)
    v.setBackgroundColor_(NSColor.whiteColor())
    from AppKit import NSApplication
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    return v


def _origen_contenido(v):
    """(x, y) en puntos, desde arriba, de la esquina del contenido de una ventana."""
    c = v.contentRectForFrameRect_(v.frame())
    return c.origin.x, _alto_principal() - (c.origin.y + c.size.height)


class _VistaArrastre(NSView):
    """Fondo (imagen) + una pieza que se arrastra con el mouse de verdad (mouseDown / mouseDragged / mouseUp)."""

    def initWithFrame_(self, marco):
        self = objc.super(_VistaArrastre, self).initWithFrame_(marco)
        if self is None:
            return None
        self.fondo = None
        self.pieza = None
        self.pos = [60.0, 150.0]          # esquina de la pieza (puntos, desde arriba)
        self.tam = (200.0, 60.0)
        self.agarre = None
        return self

    def isFlipped(self):
        return True

    def acceptsFirstMouse_(self, evento):
        return True

    def drawRect_(self, rect):
        from AppKit import NSCompositingOperationSourceOver
        from Foundation import NSZeroRect
        if self.fondo is not None:
            self.fondo.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
                self.bounds(), NSZeroRect, NSCompositingOperationSourceOver, 1.0, True, None)
        if self.pieza is not None:
            self.pieza.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
                NSMakeRect(self.pos[0], self.pos[1], self.tam[0], self.tam[1]), NSZeroRect,
                NSCompositingOperationSourceOver, 1.0, True, None)

    def _p(self, evento):
        p = self.convertPoint_fromView_(evento.locationInWindow(), None)
        return p.x, p.y

    def mouseDown_(self, evento):
        x, y = self._p(evento)
        if self.pos[0] <= x <= self.pos[0] + self.tam[0] and self.pos[1] <= y <= self.pos[1] + self.tam[1]:
            self.agarre = (x - self.pos[0], y - self.pos[1])

    def mouseDragged_(self, evento):
        if self.agarre is not None:
            x, y = self._p(evento)
            self.pos = [x - self.agarre[0], y - self.agarre[1]]
            self.setNeedsDisplay_(True)

    def mouseUp_(self, evento):
        self.agarre = None


class _VistaTeclas(NSView):
    """Contenido que anota cualquier tecla que le llegue (para ver que NO se escribio nada fuera de un campo)."""

    def initWithFrame_(self, marco):
        self = objc.super(_VistaTeclas, self).initWithFrame_(marco)
        if self is None:
            return None
        self.teclas = []
        return self

    def isFlipped(self):
        return True

    def acceptsFirstResponder(self):
        return True

    def keyDown_(self, evento):
        self.teclas.append(str(evento.characters() or ""))


class _BotonContador(NSView):
    """Un 'boton' que solo anota si le dan clic."""

    def initWithFrame_(self, marco):
        self = objc.super(_BotonContador, self).initWithFrame_(marco)
        if self is None:
            return None
        self.clics = 0
        self.imagen = None
        return self

    def isFlipped(self):
        return True

    def acceptsFirstMouse_(self, evento):
        return True

    def drawRect_(self, rect):
        from AppKit import NSCompositingOperationCopy
        from Foundation import NSZeroRect
        if self.imagen is not None:
            self.imagen.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
                self.bounds(), NSZeroRect, NSCompositingOperationCopy, 1.0, True, None)

    def mouseDown_(self, evento):
        self.clics += 1


def _texto_img(texto, w, h, tam=24, fondo=(255, 255, 255), color=(30, 30, 30), borde=None):
    from PIL import ImageDraw
    from .. import muestras
    im = Image.new("RGBA", (w, h), fondo + (255,))
    d = ImageDraw.Draw(im)
    if borde:
        d.rectangle((0, 0, w - 1, h - 1), outline=borde, width=2)
    f = muestras._f(tam, 500)
    caja = d.textbbox((0, 0), texto, font=f)
    d.text(((w - (caja[2] - caja[0])) / 2, (h - (caja[3] - caja[1])) / 2 - caja[1]), texto, font=f, fill=color)
    return im


def _nsimagen(im):
    return NSImage.alloc().initWithCGImage_size_(_cgimagen(im.convert("RGBA")), NSMakeSize(im.width, im.height))


# ---------------------------------------------------------------- la prueba

def ventana_y_e2e(salida, RESULTADOS, IA, buscar, ESPERADO, fases=None, id_de=None, lineas=None):
    import queue

    from .. import config, motor, muestras
    from ..bot import Bot
    from .ventana import VentanaMac

    d = tempfile.mkdtemp()
    os.environ["CLW_DATOS"] = d
    c = config.Config(os.path.join(d, "ajustes.json"))
    c.poner_clave("claude", "sk-ant-prueba")
    bot = Bot(c, queue.Queue())
    v = VentanaMac(c, bot)
    root = v.root
    estado = {"fin": False}
    pruebas = {}
    cpu = {}
    extra = {"ventanas": []}

    def guardar(nombre, im):
        try:
            im.save(os.path.join(salida, nombre + ".png"))
        except Exception:
            pass

    def copiar_revision(nombre):
        for f in ("ultima_captura.png", "ultima_revision.png"):
            origen = os.path.join(d, "revision", f)
            if os.path.exists(origen):
                shutil.copy(origen, os.path.join(salida, f"{nombre}_{f}"))

    def medir_cpu(nombre, seg, despues):
        t0, c0 = time.time(), time.process_time()

        def fin():
            cpu[nombre] = round(100 * (time.process_time() - c0) / max(0.001, time.time() - t0), 2)
            despues()
        root.after(int(seg * 1000), fin)

    # -------- la ventana se ve (nitida y derecha)
    def paso_ventana():
        try:
            im = foto_ventana(v.hwnd())
            guardar("ventana_inicio", im)
            ref = v.ui.render().convert("RGB")
            det = {"tam": im.size, "escala": v.e, "render": ref.size, "bandeja": v.en_bandeja(),
                   "permisos": permisos.estado()}
            # el contenido queda abajo (arriba esta la barra del titulo): se compara con lo que dibujo la Interfaz
            k = im.width / ref.width
            alto = int(round(ref.height * k))
            contenido = im.crop((0, im.height - alto, im.width, im.height)).resize(ref.size, Image.LANCZOS)
            guardar("ventana_contenido", contenido)
            from PIL import ImageChops, ImageStat
            dif = ImageStat.Stat(ImageChops.difference(contenido, ref).convert("L")).mean[0]
            al_reves = ImageStat.Stat(ImageChops.difference(contenido.transpose(Image.FLIP_TOP_BOTTOM),
                                                            ref).convert("L")).mean[0]
            pantalla = v.ventana.screen()
            escala_pantalla = float(pantalla.backingScaleFactor()) if pantalla is not None else 1.0
            det.update({"diferencia": round(dif, 2), "diferencia_al_reves": round(al_reves, 2),
                        "escala_pantalla": escala_pantalla,
                        "nitida": im.width >= 380 * escala_pantalla * 0.98})   # usa todos los pixeles de la pantalla
            RESULTADOS["ventana"] = {"ok": dif < 25 and dif < al_reves * 0.7, "detalle": det}
        except Exception as e:
            RESULTADOS["ventana"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
        medir_cpu("ventana_al_frente", 2.0, paso_rendimiento)

    # -------- que no se trabe
    def paso_rendimiento():
        tiempos = {}

        def cuadro(accion=None):
            t0 = time.perf_counter()
            if accion:
                accion()
            else:
                v._pintar()
            return (time.perf_counter() - t0) * 1000

        def anotar(nombre, ts):
            ts = sorted(ts) or [0.0]
            tiempos[nombre] = {"prom": round(sum(ts) / len(ts), 2), "p90": round(ts[max(0, int(len(ts) * .9) - 1)], 2),
                               "max": round(ts[-1], 2), "n": len(ts)}

        def durante(seg):
            ts, fin = [], time.time() + seg
            while time.time() < fin:
                ts.append(cuadro())
            return ts

        try:
            puntos = [(190, 295), (190, 204), (60, 566), (190, 120), (320, 470), (300, 204), (190, 295), (20, 590)]
            anotar("mouse_principal", [cuadro(lambda p=p: v._mouse("mover", p[0] + i % 3, p[1]))
                                       for i in range(6) for p in puntos])
            v._mouse("salir")
            anotar("quieta_animada", durante(0.6))
            v.ui._accion("ajustes")
            anotar("transicion_ajustes", durante(0.35))
            v.ui._accion("volver")
            durante(0.35)
            v.ui._accion("modelo")
            anotar("hoja_abriendo", durante(0.3))
            v.ui._accion("cerrar_capa")
            durante(0.2)
            peor = max(t["p90"] for t in tiempos.values())
            RESULTADOS["rendimiento"] = {"ok": peor < 33, "detalle": {"escala": v.e, "ms": tiempos}}
        except Exception as e:
            RESULTADOS["rendimiento"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
        root.after(200, paso_permisos)

    # -------- la pantalla de permisos (y luego seguir aunque falten, para probar lo demas)
    def paso_permisos():
        faltan = permisos.faltan()
        extra["permisos_faltan"] = faltan
        if faltan:
            v.ui.inyectar()                  # sin permisos: debe pedirlos en vez de arrancar
            root.after(500, lambda: _foto_permisos(faltan))
        else:
            root.after(100, paso_inyectar)

    def _foto_permisos(faltan):
        try:
            extra["pantalla_sin_permisos"] = v.ui.pantalla
            guardar("ventana_permisos", foto_ventana(v.hwnd()))
        except Exception:
            pass
        v.ui._ir("principal", -1)
        v.faltan_permisos = lambda: []       # (para seguir probando el resto en la maquina de pruebas)
        root.after(600, paso_inyectar)

    def paso_inyectar():
        v.ui.inyectar()
        root.after(300, lambda: guardar("ventana_encendiendo", foto_ventana(v.hwnd())))
        root.after(2400, paso_escondida)

    def paso_escondida():
        try:
            det = {"activo": bot.activo, "visible": v.visible, "estado": root.state(), "bandeja": v.en_bandeja(),
                   "escucha": bot.escucha.corriendo, "sin_permiso": getattr(bot.escucha, "sin_permiso", None),
                   "actividad": list(v.ui.actividad)[:2]}
            RESULTADOS["bandeja"] = {"ok": bool(bot.activo and not v.visible and det["estado"] == "withdrawn"
                                                and det["bandeja"]), "detalle": det}
        except Exception as e:
            RESULTADOS["bandeja"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
        medir_cpu("escondida_y_activa", 3.0, e2e_opcion)

    # -------- E2E 1: opcion multiple
    def e2e_opcion():
        try:
            img, tarjetas, (qx, qy) = muestras.quiz_oscuro()
            w = _ventana_prueba(30, 60, img.width, img.height, "Prueba opcion")
            vista = _VistaClics.alloc().initWithFrame_(NSMakeRect(0, 0, img.width, img.height))
            vista.imagen = NSImage.alloc().initWithCGImage_size_(_cgimagen(img.convert("RGBA")),
                                                                 NSMakeSize(img.width, img.height))
            w.setContentView_(vista)
            w.makeKeyAndOrderFront_(None)
            w.orderFrontRegardless()
            extra["ventanas"].append(w)
            IA.elegir = lambda t: json.dumps({"tipo": "opcion", "ids": [int(buscar(t, "París") or 0)]})
            ox, oy = _origen_contenido(w)
            threading.Thread(target=option_clic, args=(ox + qx, oy + qy), daemon=True).start()
            inicio = time.time()

            def revisar():
                c_ = tarjetas["París"]
                buenos = [p for p in vista.clics if c_[0] <= p[0] <= c_[2] and c_[1] <= p[1] <= c_[3]]
                if (buenos and not bot._ocupado.locked()) or time.time() - inicio > 40:
                    pruebas["opcion"] = {"ok": bool(buenos), "clics": list(vista.clics), "esperado": c_,
                                         "actividad": list(v.ui.actividad)[:3], "pedidos_ia": IA.pedidos,
                                         "escala": motor.factor_zoom()}
                    copiar_revision("opcion")
                    try:
                        guardar("e2e_opcion", foto_ventana(int(w.windowNumber())))
                    except Exception:
                        pass
                    w.orderOut_(None)
                    root.after(300, e2e_escribir)
                else:
                    root.after(200, revisar)
            root.after(500, revisar)
        except Exception as e:
            pruebas["opcion"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            root.after(100, e2e_escribir)

    # -------- E2E 2: escribir en un campo de texto nativo (con acentos)
    def e2e_escribir():
        try:
            w = _ventana_prueba(30, 60, 820, 300, "Prueba escribir")
            contenido = w.contentView()
            etiqueta = NSTextField.labelWithString_("1. ¿Cuánto es dos más dos?")
            etiqueta.setFont_(NSFont.systemFontOfSize_(22))
            etiqueta.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.13, 1.0))
            etiqueta.setFrame_(NSMakeRect(40, 300 - 40 - 34, 600, 34))
            contenido.addSubview_(etiqueta)
            campo = NSTextField.alloc().initWithFrame_(NSMakeRect(40, 300 - 110 - 44, 600, 44))
            campo.setFont_(NSFont.systemFontOfSize_(20))
            campo.setPlaceholderString_("Escriba su respuesta")
            contenido.addSubview_(campo)
            w.makeKeyAndOrderFront_(None)
            w.orderFrontRegardless()
            extra["ventanas"].append(w)
            diag = {}

            def elegir(t):
                campo_ = buscar(t, "", campos=True) or buscar(t, "Escriba")
                obj = campo_ if (campo_ or "").startswith("C") else int(campo_ or 0)
                diag["ia_campo"] = obj
                return json.dumps({"tipo": "abierta", "respuestas": [{"campo": obj, "texto": ESPERADO}]})
            IA.elegir = elegir
            ox, oy = _origen_contenido(w)
            threading.Thread(target=option_clic, args=(ox + 120, oy + 57), daemon=True).start()
            inicio = time.time()

            def revisar():
                texto = str(campo.stringValue() or "")
                if (ESPERADO in texto and not bot._ocupado.locked()) or time.time() - inicio > 40:
                    pruebas["escribir"] = {"ok": ESPERADO in texto, "exacto": texto == ESPERADO, "texto": texto,
                                           "diag": diag, "actividad": list(v.ui.actividad)[:2]}
                    copiar_revision("escribir")
                    try:
                        guardar("e2e_escribir", foto_ventana(int(w.windowNumber())))
                    except Exception:
                        pass
                    w.orderOut_(None)
                    root.after(300, e2e_casillas)
                else:
                    root.after(200, revisar)
            root.after(500, revisar)
        except Exception as e:
            pruebas["escribir"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            root.after(100, e2e_casillas)

    def esperar(nombre, w, listo, detalle, despues, limite=45, minimo=2.0):
        inicio = time.time()

        def revisar():
            t = time.time() - inicio
            if (t >= minimo and listo() and not bot._ocupado.locked()) or t > limite:
                det = detalle()
                det["actividad"] = list(v.ui.actividad)[:3]
                det["seg"] = round(t, 1)
                pruebas[nombre] = det
                copiar_revision(nombre)
                try:
                    guardar("e2e_" + nombre, foto_ventana(int(w.windowNumber())))
                except Exception:
                    pass
                w.orderOut_(None)
                root.after(300, despues)
            else:
                root.after(250, revisar)
        root.after(800, revisar)

    def etiqueta(contenido, texto, x, y, w=700, h=34, tam=22):
        e = NSTextField.labelWithString_(texto)
        e.setFont_(NSFont.systemFontOfSize_(tam))
        e.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.13, 1.0))
        alto = contenido.frame().size.height
        e.setFrame_(NSMakeRect(x, y if contenido.isFlipped() else alto - y - h, w, h))
        contenido.addSubview_(e)
        return e

    # -------- E2E 3: casillas (seleccion multiple): las dos correctas, ninguna de mas
    def e2e_casillas():
        try:
            from AppKit import NSButton, NSButtonTypeSwitch
            w = _ventana_prueba(30, 60, 820, 420, "Prueba casillas")
            contenido = w.contentView()
            etiqueta(contenido, "4. Selecciona los colores primarios", 40, 30)
            botones = {}
            for i, t in enumerate(["Rojo", "Verde", "Azul", "Gato"]):
                b = NSButton.alloc().initWithFrame_(NSMakeRect(60, 420 - (90 + i * 60) - 36, 300, 36))
                b.setButtonType_(NSButtonTypeSwitch)
                b.setTitle_(t)
                b.setFont_(NSFont.systemFontOfSize_(22))
                contenido.addSubview_(b)
                botones[t] = b
            w.makeKeyAndOrderFront_(None)
            w.orderFrontRegardless()
            extra["ventanas"].append(w)
            IA.elegir = fases(lambda t: {"tipo": "opcion_multiple", "respuesta": "Rojo | Azul", "acciones": [
                {"hacer": "clic", "en": id_de(t, "Rojo"), "texto": "Rojo"},
                {"hacer": "clic", "en": id_de(t, "Azul"), "texto": "Azul"}]}, "opcion_multiple")
            ox, oy = _origen_contenido(w)
            threading.Thread(target=option_clic, args=(ox + 200, oy + 47), daemon=True).start()

            def valores():
                return {k: int(b.state()) for k, b in botones.items()}

            def listo():
                return valores() == {"Rojo": 1, "Verde": 0, "Azul": 1, "Gato": 0}
            esperar("casillas", w, listo, lambda: {"ok": listo(), "valores": valores()}, e2e_menu)
        except Exception as e:
            pruebas["casillas"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            root.after(100, e2e_menu)

    # -------- E2E 4: menu desplegable nativo (NSPopUpButton)
    def e2e_menu():
        try:
            from AppKit import NSPopUpButton
            w = _ventana_prueba(30, 60, 820, 420, "Prueba menu")
            contenido = w.contentView()
            etiqueta(contenido, "5. ¿Dónde se produce la energía de la célula?", 40, 30)
            pb = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(60, 420 - 100 - 40, 320, 40), False)
            pb.addItemsWithTitles_(["Elige una", "Núcleo", "Mitocondria", "Ribosoma"])
            pb.setFont_(NSFont.systemFontOfSize_(20))
            contenido.addSubview_(pb)
            w.makeKeyAndOrderFront_(None)
            w.orderFrontRegardless()
            extra["ventanas"].append(w)
            IA.elegir = fases(lambda t: {"tipo": "desplegable", "respuesta": "Mitocondria", "acciones": [
                {"hacer": "elegir", "en": id_de(t, "Elige"), "opcion": "Mitocondria"}]}, "desplegable")
            ox, oy = _origen_contenido(w)
            threading.Thread(target=option_clic, args=(ox + 200, oy + 47), daemon=True).start()

            def valor():
                return str(pb.titleOfSelectedItem() or "")
            esperar("menu", w, lambda: valor() == "Mitocondria", lambda: {"ok": valor() == "Mitocondria",
                                                                          "valor": valor()}, e2e_arrastrar)
        except Exception as e:
            pruebas["menu"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            root.after(100, e2e_arrastrar)

    # -------- E2E 5: arrastrar una etiqueta hasta su lugar
    def e2e_arrastrar():
        try:
            from PIL import ImageDraw
            W_, H_ = 820, 420
            w = _ventana_prueba(30, 60, W_, H_, "Prueba arrastrar")
            fondo = Image.new("RGBA", (W_, H_), (255, 255, 255, 255))
            d_ = ImageDraw.Draw(fondo)
            from .. import muestras
            d_.text((40, 30), "6. Arrastra la etiqueta a su lugar", font=muestras._f(24, 600), fill=(30, 30, 30))
            d_.rectangle((450, 140, 720, 320), outline=(130, 130, 130), width=2)
            d_.text((535, 215), "Aquí va", font=muestras._f(22, 500), fill=(90, 90, 90))
            vista = _VistaArrastre.alloc().initWithFrame_(NSMakeRect(0, 0, W_, H_))
            vista.fondo = _nsimagen(fondo)
            vista.pieza = _nsimagen(_texto_img("Corazón", 200, 60, 22, (221, 228, 255), (20, 20, 40), (80, 80, 120)))
            w.setContentView_(vista)
            w.makeKeyAndOrderFront_(None)
            w.orderFrontRegardless()
            extra["ventanas"].append(w)
            IA.elegir = fases(lambda t: {"tipo": "arrastrar", "acciones": [
                {"hacer": "arrastrar", "desde": id_de(t, "Coraz"), "hasta": id_de(t, "Aqu")}]}, "arrastrar")
            ox, oy = _origen_contenido(w)
            threading.Thread(target=option_clic, args=(ox + 200, oy + 45), daemon=True).start()

            def centro():
                return vista.pos[0] + vista.tam[0] / 2, vista.pos[1] + vista.tam[1] / 2

            def listo():
                x, y = centro()
                return 450 <= x <= 720 and 140 <= y <= 320
            esperar("arrastrar", w, listo, lambda: {"ok": listo(), "centro": centro()}, e2e_seguro)
        except Exception as e:
            pruebas["arrastrar"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            root.after(100, e2e_seguro)

    # -------- E2E 6: el candado: aunque la IA lo pida, NO pica "Siguiente" ni escribe fuera de un campo
    def e2e_seguro():
        try:
            W_, H_ = 820, 420
            w = _ventana_prueba(30, 60, W_, H_, "Prueba candado")
            vista = _VistaTeclas.alloc().initWithFrame_(NSMakeRect(0, 0, W_, H_))
            w.setContentView_(vista)
            etiqueta(vista, "7. Escribe el nombre del autor", 40, 30)
            boton = _BotonContador.alloc().initWithFrame_(NSMakeRect(560, 300, 180, 50))
            boton.imagen = _nsimagen(_texto_img("Siguiente", 180, 50, 22, (235, 235, 240), (20, 20, 20), (120, 120, 120)))
            vista.addSubview_(boton)
            w.makeKeyAndOrderFront_(None)
            w.makeFirstResponder_(vista)
            w.orderFrontRegardless()
            extra["ventanas"].append(w)

            def contestar(t):
                ident = buscar(t, "nombre del autor")
                x = y = 0
                for i, cx, cy, _txt in lineas(t):
                    if i == ident:
                        x, y = cx, cy + 120
                return {"tipo": "abierta", "respuesta": "Cervantes", "acciones": [
                    {"hacer": "clic", "en": id_de(t, "Siguiente")},
                    {"hacer": "escribir", "en": {"x": x, "y": y}, "texto": "zzz"}]}
            IA.elegir = fases(contestar, "abierta")
            ox, oy = _origen_contenido(w)
            threading.Thread(target=option_clic, args=(ox + 200, oy + 47), daemon=True).start()

            def listo():
                return any("Cervantes" in str(a) for a in list(v.ui.actividad)[:2])
            esperar("candado", w, listo, lambda: {"ok": listo() and boton.clics == 0 and not vista.teclas,
                                                  "clics_siguiente": boton.clics, "teclas": vista.teclas[:10]}, reabrir)
        except Exception as e:
            pruebas["candado"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            root.after(100, reabrir)

    # -------- abrir NO LIMIT otra vez (Dock / Launchpad): la ventana escondida vuelve
    def reabrir():
        try:
            v._delegado.applicationShouldHandleReopen_hasVisibleWindows_(v.nsapp, False)

            def revisar():
                det = {"visible": v.visible, "estado": root.state(), "activo": bot.activo}
                RESULTADOS["reabrir"] = {"ok": bool(v.visible and det["estado"] == "normal"), "detalle": det}
                try:
                    guardar("ventana_reabierta", foto_ventana(v.hwnd()))
                except Exception:
                    pass
                root.after(200, terminar)
            root.after(1500, revisar)
        except Exception as e:
            RESULTADOS["reabrir"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
            root.after(100, terminar)

    def terminar():
        if estado["fin"]:
            return
        estado["fin"] = True
        RESULTADOS["e2e"] = {"ok": all(p.get("ok") for p in pruebas.values()) and len(pruebas) == 6,
                             "detalle": pruebas}
        RESULTADOS["cpu"] = {"ok": cpu.get("escondida_y_activa", 99) < 5, "detalle": cpu}
        RESULTADOS["permisos"] = {"ok": not extra.get("permisos_faltan"),
                                  "detalle": {"faltaban": extra.get("permisos_faltan"),
                                              "pantalla_sin_permisos": extra.get("pantalla_sin_permisos")}}
        try:
            for f in os.listdir(os.path.join(d, "revision")):
                Image.open(os.path.join(d, "revision", f)).save(os.path.join(salida, "revision_" + f))
        except Exception:
            pass
        root.after(100, v.salir)

    root.after(1200, paso_ventana)
    root.after(260000, terminar)
    root.mainloop()
