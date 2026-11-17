"""Accesibilidad de Mac (AX): lo que la pagina SI dice que es cada cosa.

Con la vista (captura + IA) a veces no se sabe si un recuadro es un campo o un adorno. La accesibilidad de macOS
dice exactamente donde estan los campos para escribir, las casillas, los circulos y los menus, con su texto y si
estan marcados. Y antes de Cmd+A / escribir se pregunta aqui si el cursor de verdad quedo dentro de un campo:
si no, NO se escribe (asi nunca se selecciona toda la pagina ni se mandan teclas a lo loco).

Todo en puntos de pantalla (los mismos que usa Quartz). Si algo falla, se devuelve None / [] y se sigue sin esto.
"""

import logging
import re
import time

try:
    import HIServices as AX
except Exception:            # (Linux en pruebas)
    AX = None

log = logging.getLogger("clw.ax")

TIEMPO = 0.6                  # segundos maximo por cada pregunta a otra app (si la app esta trabada no nos traba)
EDITABLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}
NO_EDITABLES = {"AXWebArea", "AXWindow", "AXApplication", "AXScrollArea", "AXButton", "AXLink", "AXRadioButton",
                "AXCheckBox", "AXStaticText", "AXImage", "AXPopUpButton", "AXMenuButton", "AXList", "AXRow",
                "AXCell", "AXTable", "AXToolbar", "AXTabGroup", "AXSplitGroup", "AXMenuBar", "AXMenuItem"}
INTERACTIVOS = {"AXTextField": "campo", "AXTextArea": "campo", "AXSearchField": "campo", "AXComboBox": "menu",
                "AXPopUpButton": "menu", "AXMenuButton": "menu", "AXRadioButton": "circulo", "AXCheckBox": "casilla",
                "AXButton": "boton", "AXSlider": "deslizador", "AXIncrementor": "numero"}
_activadas = {}


def disponible():
    return AX is not None


def _attr(el, nombre):
    try:
        err, val = AX.AXUIElementCopyAttributeValue(el, nombre, None)
    except Exception:
        return None
    return val if err == 0 else None


def _numeros(v):
    """De un AXValue (punto o tamano) saca los numeros. Se intenta con la funcion y si no, leyendo su texto."""
    for tipo in (getattr(AX, "kAXValueCGPointType", 1), getattr(AX, "kAXValueCGSizeType", 2)):
        try:
            r = AX.AXValueGetValue(v, tipo, None)
        except Exception:
            continue
        if isinstance(r, tuple) and len(r) >= 2 and r[0]:
            p = r[1]
            if hasattr(p, "x"):
                return float(p.x), float(p.y)
            if hasattr(p, "width"):
                return float(p.width), float(p.height)
    texto = str(v)
    m = re.search(r"x:\s*(-?[\d.]+)\s+y:\s*(-?[\d.]+)", texto)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"w:\s*(-?[\d.]+)\s+h:\s*(-?[\d.]+)", texto)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def _marco(el):
    """(x, y, w, h) en puntos, o None."""
    p, t = _attr(el, "AXPosition"), _attr(el, "AXSize")
    if p is None or t is None:
        return None
    a, b = _numeros(p), _numeros(t)
    if not a or not b or b[0] <= 0 or b[1] <= 0:
        return None
    return a[0], a[1], b[0], b[1]


def _texto(v, largo=60):
    if v is None:
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(int(v)) if float(v).is_integer() else str(v)
    try:
        t = str(v)
    except Exception:
        return ""
    if t.startswith("<") and "AXUIElement" in t:
        return ""
    return " ".join(t.split())[:largo]


def _etiqueta(el):
    for nombre in ("AXTitle", "AXDescription", "AXPlaceholderValue", "AXHelp"):
        t = _texto(_attr(el, nombre))
        if t:
            return t
    titulo = _attr(el, "AXTitleUIElement")
    if titulo is not None:
        t = _texto(_attr(titulo, "AXValue")) or _texto(_attr(titulo, "AXTitle"))
        if t:
            return t
    return ""


def _pid(el):
    try:
        err, pid = AX.AXUIElementGetPid(el, None)
        return int(pid) if err == 0 else None
    except Exception:
        return None


def _con_tiempo(el):
    try:
        AX.AXUIElementSetMessagingTimeout(el, TIEMPO)
    except Exception:
        pass
    return el


def elemento_en(x, y):
    """El elemento que esta en ese punto (puntos de pantalla), o None."""
    if AX is None:
        return None
    try:
        sistema = _con_tiempo(AX.AXUIElementCreateSystemWide())
        err, el = AX.AXUIElementCopyElementAtPosition(sistema, float(x), float(y), None)
        return el if err == 0 else None
    except Exception:
        return None


def preparar(x, y):
    """Le pide a la app que esta en ese punto que prenda su accesibilidad web (Chrome, Edge, Brave, Opera, Arc...).
    Sin esto Chrome no dice que hay adentro de la pagina. Se hace una vez por app."""
    if AX is None:
        return False
    el = elemento_en(x, y)
    pid = _pid(el) if el is not None else None
    if not pid:
        return False
    if _activadas.get(pid, 0) > time.time() - 600:
        return True
    try:
        app = _con_tiempo(AX.AXUIElementCreateApplication(pid))
        AX.AXUIElementSetAttributeValue(app, "AXManualAccessibility", True)
    except Exception:
        pass
    _activadas[pid] = time.time()
    return True


def foco():
    """Lo que tiene el cursor del teclado: {'rol', 'editable', 'marco'} o None si no se puede saber."""
    if AX is None:
        return None
    try:
        sistema = _con_tiempo(AX.AXUIElementCreateSystemWide())
    except Exception:
        return None
    el = _attr(sistema, "AXFocusedUIElement")
    if el is None:
        app = _attr(sistema, "AXFocusedApplication")
        el = _attr(app, "AXFocusedUIElement") if app is not None else None
    if el is None:
        return None
    _con_tiempo(el)
    rol = _texto(_attr(el, "AXRole"))
    editable = rol in EDITABLES
    if not editable and rol not in NO_EDITABLES:
        try:
            err, se_puede = AX.AXUIElementIsAttributeSettable(el, "AXValue", None)
            editable = bool(err == 0 and se_puede)
        except Exception:
            editable = False
    if not editable and _attr(el, "AXEditableAncestor") is not None and rol not in ("AXWebArea", "AXWindow"):
        editable = True                      # texto dentro de un editor (contenteditable)
    return {"rol": rol, "editable": editable, "marco": _marco(el)}


AMBIGUOS = {"AXGroup", "AXWebArea", "AXUnknown", "AXScrollArea", "AXLayoutArea", "AXLayoutItem", "AXSplitGroup",
            "AXWindow", "AXApplication", ""}


def que_hay_en(x, y):
    """Que hay en ese punto (puntos): {'rol', 'campo': True/False/None, 'enlace': bool} o None si no se sabe.
    campo=True: ahi se puede escribir. False: seguro que no (texto, boton, imagen...). None: no se sabe."""
    el = elemento_en(x, y)
    if el is None:
        return None
    _con_tiempo(el)
    rol0 = _texto(_attr(el, "AXRole"))
    enlace = False
    actual, campo = el, None
    for nivel in range(5):
        rol = _texto(_attr(actual, "AXRole"))
        if rol == "AXLink":
            enlace = True
        if rol in EDITABLES:
            campo = True
            break
        if nivel == 0 and _attr(actual, "AXEditableAncestor") is not None and rol not in ("AXWebArea", "AXWindow"):
            campo = True
            break
        if rol in ("AXWebArea", "AXWindow", "AXApplication"):
            break
        actual = _attr(actual, "AXParent")
        if actual is None:
            break
    if campo is None and rol0 not in AMBIGUOS:
        campo = False                        # texto, imagen, boton, casilla, enlace...: ahi no se escribe
    return {"rol": rol0, "campo": campo, "enlace": enlace}


def foco_editable():
    """True si el cursor esta en un campo para escribir, False si seguro que no, None si no se puede saber."""
    f = foco()
    if f is None or not f["rol"]:
        return None
    if f["editable"]:
        return True
    if f["rol"] in AMBIGUOS:
        return None                          # (Chrome sin su arbol de accesibilidad: no se sabe)
    return False


def _ventana_de(el):
    w = _attr(el, "AXWindow")
    if w is not None:
        return w
    actual = el
    for _ in range(40):
        rol = _texto(_attr(actual, "AXRole"))
        if rol == "AXWindow":
            return actual
        padre = _attr(actual, "AXParent")
        if padre is None:
            return actual
        actual = padre
    return actual


def _se_tocan(a, b, margen=0):
    return not (a[0] + a[2] < b[0] - margen or b[0] + b[2] < a[0] - margen or
                a[1] + a[3] < b[1] - margen or b[1] + b[3] < a[1] - margen)


def controles(zona, punto=None, limite_nodos=4000, limite_seg=1.6):
    """Controles (campos, casillas, circulos, menus, botones) que caen en 'zona' (x, y, w, h en puntos).
    Devuelve [{'rol', 'tipo', 'etiqueta', 'valor', 'marco'}]."""
    if AX is None:
        return []
    x, y, w, h = zona
    punto = punto or (x + w / 2, y + h / 2)
    el = elemento_en(*punto)
    if el is None:
        return []
    raiz = _con_tiempo(_ventana_de(el))
    inicio = time.time()
    out, pila, vistos = [], [raiz], 0
    while pila and vistos < limite_nodos and time.time() - inicio < limite_seg:
        nodo = pila.pop()
        vistos += 1
        rol = _texto(_attr(nodo, "AXRole"))
        marco = _marco(nodo)
        if marco is not None and not _se_tocan(marco, zona, 4) and rol not in ("AXWindow", "AXScrollArea", "AXWebArea"):
            continue                         # fuera de la pregunta (y todo lo de adentro tambien)
        if rol in INTERACTIVOS and marco is not None and _se_tocan(marco, zona):
            habilitado = _attr(nodo, "AXEnabled")
            if habilitado is not False:
                out.append({"rol": rol, "tipo": INTERACTIVOS[rol], "etiqueta": _etiqueta(nodo),
                            "valor": _texto(_attr(nodo, "AXValue"), 50), "marco": marco})
            if rol not in ("AXComboBox", "AXGroup"):
                continue                     # (no hace falta ver lo de adentro de un boton o casilla)
        hijos = _attr(nodo, "AXChildren")
        if hijos:
            try:
                pila.extend(reversed(list(hijos)))
            except TypeError:
                pass
    log.info("ax: %d controles en %d nodos (%.2fs)", len(out), vistos, time.time() - inicio)
    return out[:80]


def valor_en(x, y):
    """Valor del control que esta en ese punto (para ver si una casilla quedo marcada): texto o None."""
    el = elemento_en(x, y)
    if el is None:
        return None
    for _ in range(4):
        rol = _texto(_attr(el, "AXRole"))
        if rol in INTERACTIVOS:
            return _texto(_attr(el, "AXValue"), 50)
        el = _attr(el, "AXParent")
        if el is None:
            break
    return None
