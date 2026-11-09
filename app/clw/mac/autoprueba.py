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


# ---------------------------------------------------------------- la prueba

def ventana_y_e2e(salida, RESULTADOS, IA, buscar, ESPERADO):
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
                if buenos or time.time() - inicio > 25:
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
                if ESPERADO in texto or time.time() - inicio > 25:
                    pruebas["escribir"] = {"ok": ESPERADO in texto, "exacto": texto == ESPERADO, "texto": texto,
                                           "diag": diag, "actividad": list(v.ui.actividad)[:2]}
                    copiar_revision("escribir")
                    try:
                        guardar("e2e_escribir", foto_ventana(int(w.windowNumber())))
                    except Exception:
                        pass
                    w.orderOut_(None)
                    root.after(300, reabrir)
                else:
                    root.after(200, revisar)
            root.after(500, revisar)
        except Exception as e:
            pruebas["escribir"] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}
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
        RESULTADOS["e2e"] = {"ok": all(p.get("ok") for p in pruebas.values()) and len(pruebas) == 2,
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
    root.after(170000, terminar)
    root.mainloop()
