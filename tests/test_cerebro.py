"""NO LIMIT 2.0: ubicar, contestar, candado de seguridad, acciones (clic, escribir, menus, arrastrar, ordenar)
y revision. Con una pantalla falsa que si cambia cuando se le da clic (asi se prueba que se confirme cada clic)."""
import json
import os
import queue
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from PIL import Image, ImageDraw  # noqa: E402

from clw import cerebro, config, motor  # noqa: E402
from clw.bot import Bot  # noqa: E402

cerebro.PAUSA = 0.0


def caja(x0, y0, x1, y1, t):
    return {"texto": t, "caja": (x0, y0, x1, y1), "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2}


def campo(x0, y0, x1, y1):
    return {"caja": (x0, y0, x1, y1), "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2}


class Pantalla:
    """Pantalla + mouse + teclado falsos. Un clic deja una marca (la pagina cambia), salvo los que se 'pierden'."""
    VK_ESCAPE = 0x1B
    Cancelado = type("Cancelado", (Exception,), {})

    def __init__(self, w=1000, h=700, perder=0):
        self.img = Image.new("RGB", (w, h), (250, 250, 250))
        self.log = []
        self.perder = perder
        self.cursor_en = None              # donde quedo el cursor del teclado (el ultimo clic que si se registro)
        self.deshechos = []

    def tecla_abajo(self, vk):
        return False

    def clic(self, x, y):
        self.log.append(("clic", round(x), round(y)))
        if self.perder > 0:
            self.perder -= 1
            return
        self.cursor_en = (x, y)
        ImageDraw.Draw(self.img).ellipse((x - 6, y - 6, x + 6, y + 6), fill=(255, 0, 0))

    def seleccionar_todo(self):
        self.log.append(("ctrl+a",))

    def escribir(self, texto, cancelar=None):
        """Lo escrito aparece donde esta el cursor del teclado (como en una pagina de verdad)."""
        self.log.append(("escribe", texto))
        self.deshechos.append(self.img.copy())
        if self.cursor_en is not None:
            x, y = self.cursor_en
            ImageDraw.Draw(self.img).rectangle((x + 8, y - 5, x + 8 + 7 * len(texto), y + 5), fill=(0, 120, 0))
        return True

    def deshacer(self):
        self.log.append(("deshacer",))
        if self.deshechos:
            self.img = self.deshechos.pop()

    def tecla(self, nombre, veces=1):
        self.log.append(("tecla", nombre))

    def mover(self, x, y):                 # pasar el mouse encima pinta un 'hover' (no cuenta como clic)
        ImageDraw.Draw(self.img).rectangle((x - 40, y - 12, x - 30, y - 2), fill=(200, 200, 210))

    def arrastrar(self, x0, y0, x1, y1, pasos=24, cancelar=None):
        self.log.append(("arrastrar", round(x0), round(y0), round(x1), round(y1)))
        ImageDraw.Draw(self.img).rectangle((x1 - 6, y1 - 6, x1 + 6, y1 + 6), fill=(0, 0, 255))

    def foto(self, left, top, w, h):
        return self.img.crop((left, top, left + w, top + h))

    def clics(self):
        return [a for a in self.log if a[0] == "clic"]


class Parche:
    """Cambia funciones de modulos durante una prueba y las regresa al final."""
    def __init__(self, **cambios):
        self.cambios = cambios

    def __enter__(self):
        self.antes = {}
        for nombre, valor in self.cambios.items():
            mod, attr = nombre.split("__")
            m = {"cerebro": cerebro, "motor": motor, "licencia": __import__("clw.licencia", fromlist=["x"])}[mod]
            self.antes[(m, attr)] = getattr(m, attr)
            setattr(m, attr, valor)
        return self

    def __exit__(self, *a):
        for (m, attr), v in self.antes.items():
            setattr(m, attr, v)


class ClienteFases:
    """IA falsa: responde segun la fase (UBICAR / CONTESTAR / REVISAR)."""
    def __init__(self, ubicar, contestar, revisar=None):
        self.f = {"UBICAR": ubicar, "CONTESTAR": contestar, "REVISAR": revisar or (lambda t: {"ok": True})}
        self.llamadas = []

    def preguntar(self, prov, modelo, clave, sistema, b64, mime, texto, preciso=False):
        fase = texto.split("\n", 1)[0].replace("FASE: ", "").strip()
        self.llamadas.append((fase, preciso, sistema[:30]))
        self.modelos = getattr(self, "modelos", []) + [(fase, modelo)]
        r = self.f[fase](texto)
        return (r if isinstance(r, str) else json.dumps(r)), False


def _bot(cliente, acciones):
    d = tempfile.mkdtemp()
    os.environ["CLW_DATOS"] = d
    c = config.Config(os.path.join(d, "a.json"))
    c.poner_clave("claude", "sk-ant-x")
    b = Bot(c, queue.Queue(), ocr=None, cliente=cliente, acciones=acciones)
    return b, c


def _eventos(b):
    out = []
    while not b.eventos.empty():
        out.append(b.eventos.get_nowait())
    return out


# ---------------------------------------------------------------- candado (planear)

CAJAS = [caja(100, 40, 600, 70, "1. ¿Cuál es la capital de Francia?"),
         caja(140, 120, 220, 144, "Madrid"), caja(140, 180, 220, 204, "París"),
         caja(140, 240, 220, 264, "Roma"), caja(700, 600, 800, 630, "Siguiente")]


def prueba_candado_no_pica_botones_ni_fuera():
    img = Image.new("RGB", (900, 650), "white")
    datos = {"tipo": "opcion_unica", "respuesta": "París", "acciones": [
        {"hacer": "clic", "en": 2, "texto": "París"},
        {"hacer": "clic", "en": 4},                                   # Siguiente: NO
        {"hacer": "clic", "en": {"x": 5000, "y": 10}},                # fuera de la pregunta: NO
        {"hacer": "clic", "en": 2},                                   # repetido: se ignora (desmarcaria)
        {"hacer": "volar", "en": 1}]}
    plan = cerebro.planear(datos, CAJAS, [], 1.0, img)
    assert [p["hacer"] for p in plan.pasos] == ["clic"], plan.pasos
    assert plan.pasos[0]["desc"] == "París"
    motivos = " | ".join(m for _, m in plan.rechazadas)
    assert "avanzar" in motivos and "fuera" in motivos and "desconocida" in motivos, motivos


def prueba_candado_corrige_id_equivocado_por_uno():
    img = Image.new("RGB", (900, 650), "white")
    plan = cerebro.planear({"acciones": [{"hacer": "clic", "en": 1, "texto": "París"}]}, CAJAS, [], 1.0, img)
    assert plan.pasos[0]["desc"] == "París", plan.pasos


def prueba_candado_solo_escribe_en_campos():
    img = Image.new("RGB", (900, 650), "white")
    campos = [campo(150, 300, 650, 344)]
    datos = {"acciones": [
        {"hacer": "escribir", "en": "C0", "texto": "**1910**"},
        {"hacer": "escribir", "en": {"x": 400, "y": 500}, "texto": "esto no"},   # ahi no hay campo: NO escribe
        {"hacer": "escribir", "en": 0, "texto": "tampoco"}]}                     # el enunciado no es un campo
    plan = cerebro.planear(datos, CAJAS, campos, 1.0, img)
    # el punto sin campo queda "por confirmar": solo se escribe si al momento la compu confirma que hay un campo
    assert [(p["hacer"], p["texto"], p["verificar_campo"]) for p in plan.pasos] == [
        ("escribir", "1910", False), ("escribir", "esto no", True)], plan.pasos
    assert len(plan.rechazadas) == 1 and "campo" in plan.rechazadas[0][1], plan.rechazadas


def prueba_candado_escribe_en_campo_cercano_o_dibujado():
    img = Image.new("RGB", (900, 650), "white")
    ImageDraw.Draw(img).rectangle((150, 400, 650, 444), outline=(120, 120, 120), width=1)   # campo sin detectar
    plan = cerebro.planear({"acciones": [{"hacer": "escribir", "en": {"x": 300, "y": 422}, "texto": "hola"}]},
                           [], [], 1.0, img)
    assert len(plan.pasos) == 1 and abs(plan.pasos[0]["p"][1] - 422) < 5, (plan.pasos, plan.rechazadas)


def prueba_candado_seguro_bajo_no_toca_nada():
    img = Image.new("RGB", (900, 650), "white")
    plan = cerebro.planear({"respuesta": "París", "seguro": "bajo", "acciones": [{"hacer": "clic", "en": 2}]},
                           CAJAS, [], 1.0, img)
    assert plan.pasos == [] and plan.respuesta == "París" and plan.rechazadas


def prueba_formato_viejo_sigue_sirviendo():
    img = Image.new("RGB", (900, 650), "white")
    plan = cerebro.planear({"tipo": "opcion", "ids": [2], "respuesta": "París"}, CAJAS, [], 1.0, img)
    assert [p["desc"] for p in plan.pasos] == ["París"]
    plan = cerebro.planear({"tipo": "abierta", "respuestas": [{"campo": "C0", "texto": "x"}]}, CAJAS,
                           [campo(150, 300, 650, 344)], 1.0, img)
    assert plan.pasos[0]["hacer"] == "escribir"


def prueba_matriz_menu_arrastrar_ordenar():
    img = Image.new("RGB", (900, 650), "white")
    cajas = [caja(300, 20, 360, 40, "Siempre"), caja(420, 20, 480, 40, "Nunca"),
             caja(20, 80, 200, 100, "Fila uno"), caja(20, 140, 200, 160, "Fila dos"),
             caja(20, 300, 120, 320, "Corazón"), caja(600, 300, 700, 320, "Menu 1")]
    datos = {"acciones": [
        {"hacer": "clic", "en": {"fila": 2, "columna": 1}},
        {"hacer": "clic", "en": {"fila": 3, "columna": 0}},
        {"hacer": "elegir", "en": 5, "opcion": "Mitocondria"},
        {"hacer": "arrastrar", "desde": 4, "hasta": {"x": 500, "y": 500}},
        {"hacer": "arrastrar", "desde": 4, "hasta": 4},                    # de cero: no
        {"hacer": "ordenar", "orden": ["a", "b", "c"]}]}
    plan = cerebro.planear(datos, cajas, [], 1.0, img)
    hechos = [p["hacer"] for p in plan.pasos]
    assert hechos == ["clic", "clic", "elegir", "arrastrar", "ordenar"], (hechos, plan.rechazadas)
    assert plan.pasos[0]["p"] == (450, 90) and plan.pasos[1]["p"] == (330, 150)
    assert plan.pasos[3]["p2"] == (500, 500)


def _plano():
    # eje x: -4..4 cada 50 px empezando en x=100 (0 en x=300), a la altura y=520
    # eje y: -4..4 cada 50 px (0 en y=300), alineados a la derecha en x=290
    cajas = [caja(100 + 50 * i - 6, 512, 100 + 50 * i + 6, 528, str(i - 4).replace("-", "\u2212")) for i in range(9) if i != 4]
    cajas += [caja(274, 300 - 50 * j - 8, 290, 300 - 50 * j + 8, str(j)) for j in range(-4, 5) if j != 0]
    cajas.append(caja(120, 20, 500, 40, "Grafica el punto (2, -3)"))
    return cajas


def prueba_graficar_con_coordenadas_del_plano():
    img = Image.new("RGB", (700, 600), "white")
    cajas = _plano()
    e = cerebro.ejes(cajas)
    assert e["x"] and e["y"], e
    plan = cerebro.planear({"acciones": [{"hacer": "clic", "en": {"gx": 2, "gy": -3}},
                                         {"hacer": "arrastrar", "desde": {"x": 300, "y": 300}, "hasta": {"gx": -1, "gy": 4}},
                                         {"hacer": "arrastrar", "desde": {"x": 400, "y": 300}, "hasta": {"x": 400, "gy": 2.5}}]},
                           cajas, [], 1.0, img)
    assert len(plan.pasos) == 3, plan.rechazadas
    x, y = plan.pasos[0]["p"]
    assert abs(x - 400) < 2 and abs(y - 450) < 2, (x, y)
    x, y = plan.pasos[1]["p2"]
    assert abs(x - 250) < 2 and abs(y - 100) < 2, (x, y)
    x, y = plan.pasos[2]["p2"]
    assert abs(x - 400) < 2 and abs(y - 175) < 2, (x, y)
    # sin numeros en los ejes no adivina
    plan = cerebro.planear({"acciones": [{"hacer": "clic", "en": {"gx": 2, "gy": -3}}]}, cajas[-1:], [], 1.0, img)
    assert plan.pasos == [] and plan.rechazadas


def prueba_coordenadas_con_escala():
    img = Image.new("RGB", (2000, 1000), "white")
    plan = cerebro.planear({"acciones": [{"hacer": "clic", "en": {"x": 300, "y": 100}}]}, [], [], 0.5, img)
    assert plan.pasos[0]["p"] == (600, 200)


def prueba_navegacion():
    for t in ("Siguiente", "SIGUIENTE >", "Next", "Submit", "Enviar", "Comprobar", "Check answer", "Terminar intento"):
        assert cerebro.es_navegacion(t), t
    for t in ("Cerrar el archivo", "El siguiente paso es la mitosis", "París", "Verdadero", "Falso", "Ninguna"):
        assert not cerebro.es_navegacion(t), t


# ---------------------------------------------------------------- ubicar

def prueba_ubicar_caja_y_respaldo():
    img = Image.new("RGB", (1600, 900), "white")
    s = cerebro._escala(1600, 900, 1568, 1560)
    u = cerebro.ubicar(img, 800, 300, lambda b, m, t: (json.dumps(
        {"hay_pregunta": True, "caja": [int(400 * s), int(200 * s), int(1000 * s), int(500 * s)], "tipo": "opcion_unica"}),
        False), 1.0)
    assert u.hay and not u.respaldo and u.tipo == "opcion_unica"
    x0, y0, x1, y1 = u.region
    assert x0 < 400 and y0 < 200 and x1 > 1000 and y1 > 500 and x1 - x0 < 1000, u.region
    u = cerebro.ubicar(img, 800, 300, lambda b, m, t: ('{"hay_pregunta": false}', False), 1.0)
    assert not u.hay
    u = cerebro.ubicar(img, 800, 300, lambda b, m, t: ('{"tipo":"opcion","ids":[3]}', False), 1.0)
    assert u.hay and u.respaldo and u.region == (0, 0, 1600, 900)
    # la imagen lleva reglas y el texto dice la fase
    vistos = {}
    cerebro.ubicar(img, 800, 300, lambda b, m, t: (vistos.setdefault("t", t) and '{}', False), 1.0)
    assert vistos["t"].startswith("FASE: UBICAR")


def prueba_ubicar_entiende_cajas_en_mil():
    img = Image.new("RGB", (1000, 600), "white")
    s = cerebro._escala(1000, 600, 1568, 1560)
    W, H = int(1000 * s), int(600 * s)
    # Gemini a veces manda [y0, x0, y1, x1] en 0..1000: la pregunta esta alrededor del puntero (800, 450)
    caja = [int(650), int(700), int(850), int(900)]
    u = cerebro.ubicar(img, 800, 450, lambda b, m, t: (json.dumps({"hay_pregunta": True, "caja": caja}), False), 1.0)
    x0, y0, x1, y1 = u.region
    assert x0 <= 800 <= x1 and y0 <= 450 <= y1, (u.region, W, H)


def prueba_reglas():
    im = cerebro.con_reglas(Image.new("RGB", (300, 200), "white"))
    assert im.size == (300 + cerebro.REGLA, 200 + cerebro.REGLA)


# ---------------------------------------------------------------- ejecutar

def prueba_clic_perdido_se_repite_una_vez():
    p = Pantalla(perder=1)
    ej = cerebro.Ejecutor(p, 0, 0, (0, 0, 1000, 700), foto=lambda: p.foto(0, 0, 1000, 700), pausa=0)
    ej.correr([{"hacer": "clic", "p": (300, 200), "desc": "París"}])
    assert len(p.clics()) == 2 and ej.hecho["clic"] == 1 and not ej.fallas, (p.log, ej.fallas)
    p = Pantalla()
    ej = cerebro.Ejecutor(p, 0, 0, (0, 0, 1000, 700), foto=lambda: p.foto(0, 0, 1000, 700), pausa=0)
    ej.correr([{"hacer": "clic", "p": (300, 200)}, {"hacer": "clic", "p": (300, 260)}, {"hacer": "clic", "p": (300, 320)}])
    assert len(p.clics()) == 3, p.log                     # casillas: cada una una sola vez


def prueba_region_se_suma_a_la_pantalla():
    p = Pantalla()
    ej = cerebro.Ejecutor(p, 100, 50, (200, 300, 700, 600), foto=lambda: None, pausa=0)
    ej.correr([{"hacer": "clic", "p": (10, 20)}])
    assert p.clics()[0] == ("clic", 310, 370)


def prueba_escribir_con_teclas_de_ecuacion():
    p = Pantalla()
    ej = cerebro.Ejecutor(p, 0, 0, (0, 0, 1000, 700), foto=lambda: p.foto(0, 0, 1000, 700), pausa=0)
    ej.correr([{"hacer": "escribir", "p": (300, 200), "texto": "x^2{derecha}+3/4{derecha}"}])
    assert p.log == [("clic", 300, 200), ("escribe", "x^2"), ("tecla", "derecha"), ("escribe", "+3/4"),
                     ("tecla", "derecha")], p.log


def prueba_menu_desplegable_elige_la_opcion_que_aparecio():
    p = Pantalla()
    d = ImageDraw.Draw(p.img)
    d.text((400, 100), "Mitocondria", fill=(0, 0, 0))              # el mismo texto ya estaba en la pregunta

    def clic(x, y):
        p.log.append(("clic", round(x), round(y)))
        if len(p.clics()) == 1:                                   # el primer clic abre el menu
            d2 = ImageDraw.Draw(p.img)
            d2.rectangle((300, 330, 520, 460), fill=(255, 255, 255), outline=(90, 90, 90))
            for k, t in enumerate(("Núcleo", "Mitocondria", "Ribosoma")):
                d2.text((312, 345 + 40 * k), t, fill=(0, 0, 0))
    p.clic = clic

    def leer(img, px, py, zoom, ocr):
        # el OCR del menu: lo que haya en el recorte (coordenadas del recorte)
        out = []
        for t, (x0, y0) in (("Núcleo", (310, 340)), ("Mitocondria", (310, 380)), ("Ribosoma", (310, 420))):
            out.append(caja(x0 - ocr_off[0], y0 - ocr_off[1], x0 + 120 - ocr_off[0], y0 + 24 - ocr_off[1], t))
        out.append(caja(400 - ocr_off[0], 100 - ocr_off[1], 480 - ocr_off[0], 115 - ocr_off[1], "Mitocondria"))
        return out
    ocr_off = [0, 0]

    def detectar(img, px, py, zoom, ocr):
        return leer(img, px, py, zoom, ocr)
    with Parche(motor__detectar_cajas=detectar):
        ej = cerebro.Ejecutor(p, 0, 0, (0, 0, 1000, 700), foto=lambda: p.foto(0, 0, 1000, 700),
                              foto_todo=lambda: p.foto(0, 0, 1000, 700), ocr=object(), pausa=0)
        # el recorte del menu empieza en la zona que cambio (menos el margen): el OCR falso usa ese corrimiento
        zona = (300, 330, 521, 461)
        ocr_off[0], ocr_off[1] = zona[0] - 12, zona[1] - 12
        ej.correr([{"hacer": "elegir", "p": (320, 300), "opcion": "Mitocondria", "desc": "menu"}])
    clics = p.clics()
    assert len(clics) == 2 and clics[0] == ("clic", 320, 300), clics
    assert 300 <= clics[1][1] <= 440 and 375 <= clics[1][2] <= 410, clics       # la del menu, no la de la pregunta
    assert ej.hecho["elegir"] == 1 and not ej.fallas, ej.fallas


def prueba_menu_sin_la_opcion_se_cierra_y_avisa():
    p = Pantalla()

    def clic(x, y):
        p.log.append(("clic", round(x), round(y)))
        if len(p.clics()) == 1:
            ImageDraw.Draw(p.img).rectangle((300, 330, 520, 460), fill=(255, 255, 255), outline=(90, 90, 90))
    p.clic = clic
    with Parche(motor__detectar_cajas=lambda img, px, py, z, o: [caja(10, 10, 100, 30, "Otra cosa")]):
        ej = cerebro.Ejecutor(p, 0, 0, (0, 0, 1000, 700), foto=lambda: p.foto(0, 0, 1000, 700),
                              foto_todo=lambda: p.foto(0, 0, 1000, 700), ocr=object(), pausa=0)
        ej.correr([{"hacer": "elegir", "p": (320, 300), "opcion": "Mitocondria"}])
    assert [c[1:] for c in p.clics()] == [(320, 300), (320, 300)], p.log    # abrio y lo volvio a cerrar
    assert ej.hecho["elegir"] == 0 and ej.fallas


def prueba_ordenar_arrastrando():
    p = Pantalla()
    lista = ["Edad Media", "Prehistoria", "Edad Moderna", "Edad Antigua"]       # como esta en pantalla

    def arrastrar(x0, y0, x1, y1, pasos=24, cancelar=None):
        p.log.append(("arrastrar", round(x0), round(y0), round(x1), round(y1)))
        i = int((y0 - 100) // 60)
        j = int((y1 - 100) // 60)
        item = lista.pop(i)
        lista.insert(j, item)
        ImageDraw.Draw(p.img).rectangle((0, 0, 10, 10), fill=(len(p.log) * 40 % 255, 0, 0))
    p.arrastrar = arrastrar

    def detectar(img, px, py, zoom, ocr):
        return [caja(50, 100 + 60 * k, 300, 130 + 60 * k, t) for k, t in enumerate(lista)]
    with Parche(motor__detectar_cajas=detectar):
        ej = cerebro.Ejecutor(p, 0, 0, (0, 0, 1000, 700), foto=lambda: p.foto(0, 0, 1000, 700), ocr=object(), pausa=0)
        ej.correr([{"hacer": "ordenar", "orden": ["Prehistoria", "Edad Antigua", "Edad Media", "Edad Moderna"]}])
    assert lista == ["Prehistoria", "Edad Antigua", "Edad Media", "Edad Moderna"], (lista, p.log)
    assert ej.hecho["ordenar"] == 1 and not ej.fallas


# ---------------------------------------------------------------- todo junto (bot)

def _quiz(p):
    d = ImageDraw.Draw(p.img)
    d.text((100, 40), "1. Selecciona TODOS los numeros primos", fill=(0, 0, 0))
    opciones = {"2": 120, "4": 180, "7": 240, "9": 300}
    cajas = [caja(100, 40, 500, 60, "1. Selecciona TODOS los numeros primos")]
    for t, y in opciones.items():
        d.rectangle((100, y, 116, y + 16), outline=(0, 0, 0))
        d.text((130, y), t, fill=(0, 0, 0))
        cajas.append(caja(126, y, 160, y + 18, t))
    cajas.append(caja(700, 600, 800, 630, "Siguiente"))
    return cajas


def prueba_bot_casillas_y_revision_corrige_la_que_falto():
    p = Pantalla()
    cajas = _quiz(p)
    revisiones = []

    def revisar(t):
        revisiones.append(t)
        if len(revisiones) == 1:                                       # la IA ve que falto el 7
            return {"ok": False, "falta": "el 7", "acciones": [{"hacer": "clic", "en": 3, "texto": "7"}]}
        return {"ok": True}
    cli = ClienteFases(
        ubicar=lambda t: {"hay_pregunta": True, "caja": [60, 20, 900, 660], "tipo": "opcion_multiple"},
        contestar=lambda t: {"tipo": "opcion_multiple", "respuesta": "2 | 7", "acciones": [
            {"hacer": "clic", "en": 1, "texto": "2"}, {"hacer": "clic", "en": 5}]},   # 5 = Siguiente: NO
        revisar=revisar)
    b, c = _bot(cli, p)
    with Parche(cerebro__leer=lambda img, px, py, zoom, ocr: (cajas, []), motor__capturar_zona=p.foto):
        b.contestar(p.img.copy(), 0, 0, 150, 125, 1.0)
    ys = [c[2] for c in p.clics()]
    assert any(115 <= y <= 140 for y in ys) and any(235 <= y <= 260 for y in ys), p.log      # el 2 y el 7
    assert not any(y > 500 for y in ys), p.log                                             # nunca Siguiente
    assert [f for f, _, _ in cli.llamadas] == ["UBICAR", "CONTESTAR", "REVISAR", "REVISAR"], cli.llamadas
    assert cli.llamadas[1][1] is True and cli.llamadas[0][1] is False      # piensa al contestar, no al ubicar
    assert cli.modelos[0] == ("UBICAR", "claude-haiku-5-5") and cli.modelos[1] == ("CONTESTAR", "claude-haiku-5-5")
    ev = _eventos(b)
    assert ("estado", "revisando") in ev and any(e[0] == "actividad" and e[1].startswith("Marcó") for e in ev), ev
    assert os.path.exists(os.path.join(os.environ["CLW_DATOS"], "revision", "ultima_revision.png"))


def prueba_gemini_ubica_y_revisa_con_el_ligero():
    p = Pantalla()
    cajas = _quiz(p)
    cli = ClienteFases(
        ubicar=lambda t: {"hay_pregunta": True, "caja": [60, 20, 900, 660], "tipo": "opcion_multiple"},
        contestar=lambda t: {"tipo": "opcion_multiple", "acciones": [{"hacer": "clic", "en": 1}, {"hacer": "clic", "en": 3}]})
    b, c = _bot(cli, p)
    c.poner_clave("gemini", "AIza-x")
    c["modelo"] = "gemini-flash-latest"
    with Parche(cerebro__leer=lambda img, px, py, zoom, ocr: (cajas, []), motor__capturar_zona=p.foto):
        b.contestar(p.img.copy(), 0, 0, 150, 125, 1.0)
    assert cli.modelos == [("UBICAR", "gemini-flash-lite-latest"), ("CONTESTAR", "gemini-flash-latest"),
                           ("REVISAR", "gemini-flash-lite-latest")], cli.modelos


def prueba_bot_numerica_piensa_mas_y_escribe():
    p = Pantalla()
    cajas = [caja(100, 40, 600, 60, "Un tren recorre 150 km en 2 h. ¿Velocidad en km/h?")]
    campos = [campo(100, 100, 400, 140)]
    cli = ClienteFases(
        ubicar=lambda t: {"hay_pregunta": True, "caja": [60, 20, 700, 300], "tipo": "numerica"},
        contestar=lambda t: {"tipo": "numerica", "pasos": "150/2=75", "respuesta": "75",
                             "acciones": [{"hacer": "escribir", "en": "C0", "texto": "75"}]})
    b, c = _bot(cli, p)
    with Parche(cerebro__leer=lambda img, px, py, zoom, ocr: (cajas, campos), motor__capturar_zona=p.foto):
        b.contestar(p.img.copy(), 0, 0, 150, 50, 1.0)
    assert ("escribe", "75") in p.log, p.log
    assert cli.llamadas[1][1] == "alto", cli.llamadas
    ev = _eventos(b)
    assert any(e[0] == "actividad" and "Escribió: 75" in e[1] for e in ev), ev


def prueba_si_se_lee_lo_escrito_no_gasta_otra_pregunta():
    p = Pantalla()
    cajas = [caja(100, 40, 600, 60, "¿En qué año inició la Revolución Mexicana?")]
    campos = [campo(100, 100, 400, 140)]
    cli = ClienteFases(
        ubicar=lambda t: {"hay_pregunta": True, "caja": [60, 20, 700, 300], "tipo": "abierta"},
        contestar=lambda t: {"tipo": "abierta", "respuesta": "1910",
                             "acciones": [{"hacer": "escribir", "en": "C0", "texto": "1910"}]})
    b, c = _bot(cli, p)
    b.ocr = object()

    def ocr_falso(img, px, py, zoom, ocr):        # despues de escribir, en el campo se lee "1910"
        return [caja(5, 5, 80, 30, "1910")] if img.width < 500 else cajas
    with Parche(cerebro__leer=lambda img, px, py, zoom, ocr: (cajas, campos), motor__capturar_zona=p.foto,
                motor__detectar_cajas=ocr_falso):
        b.contestar(p.img.copy(), 0, 0, 150, 50, 1.0)
    assert ("escribe", "1910") in p.log
    assert [f for f, _, _ in cli.llamadas] == ["UBICAR", "CONTESTAR"], cli.llamadas     # sin REVISAR


def prueba_bot_sin_pregunta_no_toca_nada():
    p = Pantalla()
    cli = ClienteFases(ubicar=lambda t: {"hay_pregunta": False}, contestar=lambda t: {"tipo": "ninguna"})
    b, c = _bot(cli, p)
    with Parche(motor__capturar_zona=p.foto):
        b.contestar(p.img.copy(), 0, 0, 150, 50, 1.0)
    assert p.log == [] and [f for f, _, _ in cli.llamadas] == ["UBICAR"]
    assert ("actividad", "No vi ninguna pregunta ahí", "info") in _eventos(b)


def prueba_bot_audio_no_inventa():
    p = Pantalla()
    cli = ClienteFases(
        ubicar=lambda t: {"hay_pregunta": True, "caja": [60, 20, 700, 300], "tipo": "audio_video"},
        contestar=lambda t: {"tipo": "audio_video", "acciones": [], "no_se_puede": "es de audio"})
    b, c = _bot(cli, p)
    with Parche(cerebro__leer=lambda img, px, py, zoom, ocr: ([], []), motor__capturar_zona=p.foto):
        b.contestar(p.img.copy(), 0, 0, 150, 50, 1.0)
    assert p.log == []
    ev = _eventos(b)
    assert any(e[0] == "actividad" and "No pude con esta" in e[1] for e in ev), ev


def prueba_bot_si_todo_era_peligroso_solo_avisa_la_respuesta():
    p = Pantalla()
    cajas = _quiz(p)
    cli = ClienteFases(
        ubicar=lambda t: {"hay_pregunta": True, "caja": [60, 20, 900, 660], "tipo": "abierta"},
        contestar=lambda t: {"tipo": "abierta", "respuesta": "Porque si",
                             "acciones": [{"hacer": "escribir", "en": {"x": 600, "y": 400}, "texto": "Porque si"}]})
    b, c = _bot(cli, p)
    with Parche(cerebro__leer=lambda img, px, py, zoom, ocr: (cajas, []), motor__capturar_zona=p.foto):
        b.contestar(p.img.copy(), 0, 0, 150, 125, 1.0)
    assert p.log == [], p.log                      # no escribio en la pagina a lo loco
    ev = _eventos(b)
    assert any(e[0] == "actividad" and "Respuesta: Porque si" in e[1] for e in ev), ev


# ---------------------------------------------------------------- 2.1: controles de la pagina (Mac) y candado al escribir

def control(x0, y0, x1, y1, tipo, etiqueta="", valor="", rol=""):
    return {"rol": rol or {"campo": "AXTextField", "casilla": "AXCheckBox", "circulo": "AXRadioButton",
                           "menu": "AXPopUpButton", "boton": "AXButton"}[tipo],
            "tipo": tipo, "etiqueta": etiqueta, "valor": valor, "caja": (x0, y0, x1, y1)}


CONTROLES = [control(100, 100, 130, 130, "casilla", "Rojo"), control(100, 160, 130, 190, "casilla", "Verde"),
             control(150, 300, 650, 340, "campo", "Tu respuesta"), control(400, 400, 600, 440, "menu", "Elige una"),
             control(700, 600, 800, 630, "boton", "Siguiente")]


def prueba_controles_de_la_pagina():
    img = Image.new("RGB", (900, 650), "white")
    datos = {"acciones": [
        {"hacer": "clic", "en": "A0"},                                   # casilla Rojo
        {"hacer": "clic", "en": "A4"},                                   # boton Siguiente: NO
        {"hacer": "escribir", "en": {"x": 300, "y": 330}, "texto": "1910"},  # cae en el campo de la pagina
        {"hacer": "escribir", "en": "A1", "texto": "no"},                # una casilla no es campo: NO
        {"hacer": "elegir", "en": "A3", "opcion": "Mitocondria"}]}
    plan = cerebro.planear(datos, [], [], 1.0, img, 1.0, CONTROLES)
    hechos = [(p["hacer"], p.get("desc") or p.get("texto")) for p in plan.pasos]
    assert hechos == [("clic", "Rojo"), ("escribir", "1910"), ("elegir", "Elige una")], (hechos, plan.rechazadas)
    assert plan.pasos[1]["p"] == (400, 320) and plan.pasos[1]["seguro_campo"]          # el centro del campo real
    motivos = " | ".join(m for _, m in plan.rechazadas)
    assert "avanzar" in motivos and "casilla" in motivos, motivos
    b64, mime, s, tam = cerebro.preparar_imagen(img, [campo(150, 300, 650, 340)], cajas=CAJAS, controles=CONTROLES)
    t = cerebro.texto_cajas(CAJAS, [], s, tam, None, CONTROLES)
    assert "[A0]" in t and "casilla 'Rojo' (sin marcar)" in t and "campo 'Tu respuesta' (vacio)" in t, t


def prueba_no_pica_si_el_texto_no_cuadra():
    img = Image.new("RGB", (900, 650), "white")
    plan = cerebro.planear({"acciones": [{"hacer": "clic", "en": 3, "texto": "Lisboa"}]}, CAJAS, [], 1.0, img)
    assert plan.pasos == [] and "no cuadra" in plan.rechazadas[0][1], plan.rechazadas


class PantallaMac(Pantalla):
    """Como en Mac: la pagina dice que hay en cada punto y si el cursor quedo en un campo."""
    def __init__(self, que=None, foco=None):
        super().__init__()
        self.que, self.foco_val = que, foco

    def que_hay_en(self, x, y):
        return self.que(x, y) if callable(self.que) else self.que

    def foco_editable(self):
        return self.foco_val() if callable(self.foco_val) else self.foco_val


def _escribe(p, paso):
    ej = cerebro.Ejecutor(p, 0, 0, (0, 0, 1000, 700), foto=lambda: p.foto(0, 0, 1000, 700), pausa=0)
    ej.correr([paso])
    return ej


def prueba_mac_no_escribe_donde_la_pagina_dice_que_no_hay_campo():
    p = PantallaMac(que={"rol": "AXStaticText", "campo": False, "enlace": False})
    ej = _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola"})
    assert p.log == [] and ej.no_escritos == ["hola"] and ej.fallas, p.log      # ni clic, ni Cmd+A, ni teclas


def prueba_mac_si_el_cursor_no_queda_en_un_campo_no_teclea():
    p = PantallaMac(que={"rol": "AXGroup", "campo": None, "enlace": False}, foco=False)
    ej = _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola"})
    assert ("ctrl+a",) not in p.log and not any(a[0] == "escribe" for a in p.log), p.log
    assert len(p.clics()) == 3 and ej.no_escritos == ["hola"]                 # lo intento 3 veces y no tecleo


def prueba_mac_con_cursor_en_campo_si_escribe():
    p = PantallaMac(que={"rol": "AXTextField", "campo": True, "enlace": False}, foco=True)
    _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola", "con_texto": True})
    assert p.log == [("clic", 300, 200), ("ctrl+a",), ("escribe", "hola")], p.log


def prueba_mac_sin_saber_escribe_sin_seleccionar_todo():
    p = PantallaMac(que={"rol": "AXGroup", "campo": None, "enlace": False}, foco=None)
    _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola"})
    assert ("ctrl+a",) not in p.log and ("escribe", "hola") in p.log, p.log


def prueba_juego_en_canvas_si_escribe_en_su_campo():
    p = PantallaMac(que={"rol": "AXImage", "campo": False, "enlace": False}, foco=None)
    _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola", "seguro_campo": True})
    assert ("escribe", "hola") in p.log and ("ctrl+a",) not in p.log, p.log


def prueba_windows_escribe_como_antes():
    p = Pantalla()
    _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola"})
    assert p.log == [("clic", 300, 200), ("escribe", "hola")], p.log             # vacia: sin Ctrl + A
    p = Pantalla()
    _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola", "con_texto": True})
    assert p.log == [("clic", 300, 200), ("ctrl+a",), ("escribe", "hola")], p.log   # se vio que el clic si entro


def prueba_nunca_pica_un_enlace():
    p = PantallaMac(que={"rol": "AXStaticText", "campo": False, "enlace": True})
    ej = cerebro.Ejecutor(p, 0, 0, (0, 0, 1000, 700), foto=lambda: p.foto(0, 0, 1000, 700), pausa=0)
    ej.correr([{"hacer": "clic", "p": (300, 200), "desc": "Ver más en Microsoft"}])
    assert p.clics() == [] and ej.fallas, p.log


def prueba_bot_con_controles_de_la_pagina():
    class PantallaControles(PantallaMac):
        def controles_en(self, left, top, w, h, punto=None):
            # (en pixeles de pantalla)
            return [dict(c, caja=(c["caja"][0] + left, c["caja"][1] + top, c["caja"][2] + left, c["caja"][3] + top))
                    for c in CONTROLES]

        def preparar_accesibilidad(self, x, y):
            self.log.append(("preparar",))
    p = PantallaControles(que={"rol": "AXCheckBox", "campo": False, "enlace": False}, foco=None)
    vistos = {}

    def contestar(t):
        vistos["t"] = t
        return {"tipo": "opcion_multiple", "respuesta": "Rojo", "acciones": [{"hacer": "clic", "en": "A0"}]}
    cli = ClienteFases(ubicar=lambda t: {"hay_pregunta": True, "caja": [0, 0, 1000, 700], "tipo": "opcion_multiple"},
                       contestar=contestar)
    b, c = _bot(cli, p)
    with Parche(cerebro__leer=lambda img, px, py, zoom, ocr: ([], []), motor__capturar_zona=p.foto):
        b.contestar(p.img.copy(), 0, 0, 150, 125, 1.0)
    assert ("preparar",) in p.log
    assert "[A0]" in vistos["t"] and "casilla 'Rojo'" in vistos["t"], vistos["t"][-400:]
    assert any(c[0] == "clic" and 100 <= c[1] <= 130 and 100 <= c[2] <= 130 for c in p.clics()), p.log


# ---------------------------------------------------------------- 2.1: campos raros y confirmar antes de escribir

def _escena_campos(zoom=1.0):
    from PIL import ImageFont
    z = lambda v: int(v * zoom)                       # noqa: E731
    try:
        f = ImageFont.load_default(size=z(15))      # (la misma letra en Windows, Mac y Linux)
    except Exception:
        f = ImageFont.load_default()
    img = Image.new("RGB", (z(900), z(700)), "white")
    d = ImageDraw.Draw(img)
    d.text((z(55), z(112)), "Tu respuesta", fill=(112, 117, 122), font=f)                       # Google Forms
    d.line([z(55), z(136), z(380), z(136)], fill=(224, 224, 224), width=max(1, z(1)))
    d.text((z(55), z(200)), "Consulta la guía oficial aquí", fill=(26, 13, 171), font=f)     # enlace subrayado
    d.line([z(55), z(219), z(262), z(219)], fill=(26, 13, 171), width=max(1, z(1)))
    d.rectangle([z(55), z(250), z(400), z(290)], outline=(120, 120, 120), width=max(1, z(1)))  # caja normal
    d.text((z(55), z(330)), "La capital de Francia es", fill=(20, 20, 20), font=f)            # ______ en un renglon
    d.line([z(250), z(347), z(360), z(347)], fill=(20, 20, 20), width=max(1, z(1)))
    d.rounded_rectangle([z(55), z(390), z(200), z(426)], radius=z(10), fill=(26, 115, 232))  # boton relleno
    d.line([z(0), z(460), z(900), z(460)], fill=(220, 220, 220), width=1)                     # separador
    for yy in (490, 525, 560):                                                                   # tabla
        d.line([z(55), z(yy), z(455), z(yy)], fill=(150, 150, 150), width=max(1, z(1)))
    for xx in (55, 255, 455):
        d.line([z(xx), z(490), z(xx), z(560)], fill=(150, 150, 150), width=max(1, z(1)))
    d.rectangle([z(500), z(600), z(880), z(690)], fill=(40, 40, 40))                           # zona oscura
    d.line([z(55), z(640), z(380), z(640)], fill=(103, 58, 183), width=max(2, z(2)))          # raya con foco
    return img


def prueba_campos_que_son_solo_una_raya():
    for zoom in (1.0, 2.0):
        img = _escena_campos(zoom)
        subs = motor.quitar_orillas(motor.subrayados(img, zoom), motor.rectangulos(img, zoom), zoom)
        rayas = sorted((round(r[0] / zoom), round((r[3] - 1) / zoom)) for r in subs)
        # Google Forms, el ______ del renglon y la raya con foco; NO el enlace, la caja, el boton, el separador,
        # la tabla ni la orilla de la zona oscura
        assert len(rayas) == 3, (zoom, rayas)
        for x, y in ((55, 136), (250, 347), (55, 640)):
            assert any(abs(rx - x) <= 3 and abs(ry - y) <= 4 for rx, ry in rayas), (zoom, rayas)


def prueba_leer_junta_cajas_y_rayas():
    img = _escena_campos(1.0)
    _, campos = cerebro.leer(img, 450, 350, 1.0, None)
    centros = [(round(c["cx"]), round(c["cy"])) for c in campos]
    assert any(abs(y - 124) < 14 and 150 < x < 300 for x, y in centros), centros      # Tu respuesta
    assert any(abs(y - 270) < 6 for x, y in centros), centros                          # la caja normal


def prueba_no_escribe_en_una_caja_que_es_boton():
    img = Image.new("RGB", (900, 650), "white")
    campos = [campo(680, 590, 820, 640)]                       # un boton con orilla parece caja
    plan = cerebro.planear({"acciones": [{"hacer": "escribir", "en": "C0", "texto": "1910"}]}, CAJAS, campos, 1.0, img)
    assert plan.pasos == [] and "boton" in plan.rechazadas[0][1], plan.rechazadas


def prueba_no_escribe_encima_del_enunciado_aunque_no_haya_campo():
    img = Image.new("RGB", (900, 650), "white")
    plan = cerebro.planear({"acciones": [{"hacer": "escribir", "en": {"x": 300, "y": 55}, "texto": "x"}]},
                           CAJAS, [], 1.0, img)
    assert plan.pasos == [] and plan.rechazadas, plan.pasos


def prueba_texto_de_ayuda_sin_caja_queda_por_confirmar():
    img = Image.new("RGB", (900, 650), "white")
    cajas = CAJAS + [caja(150, 420, 380, 444, "Escribe tu respuesta")]
    plan = cerebro.planear({"acciones": [{"hacer": "escribir", "en": 5, "texto": "París"}]}, cajas, [], 1.0, img)
    assert len(plan.pasos) == 1 and plan.pasos[0]["verificar_campo"], (plan.pasos, plan.rechazadas)


class PantallaWin(Pantalla):
    def __init__(self, cursor):
        super().__init__()
        self.cursor = cursor

    def forma_cursor(self):
        return self.cursor


def prueba_windows_por_confirmar_sin_cursor_de_texto_no_toca():
    p = PantallaWin("flecha")
    ej = _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola", "verificar_campo": True})
    assert p.clics() == [] and ej.no_escritos == ["hola"], p.log


def prueba_windows_por_confirmar_con_cursor_de_texto_escribe_sin_seleccionar_todo():
    p = PantallaWin("texto")
    _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola", "verificar_campo": True})
    assert p.log == [("clic", 300, 200), ("escribe", "hola")], p.log


def prueba_mac_por_confirmar_solo_si_el_foco_queda_en_un_campo():
    p = PantallaMac(que={"rol": "AXGroup", "campo": None, "enlace": False}, foco=None)
    ej = _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola", "verificar_campo": True})
    assert not any(a[0] == "escribe" for a in p.log) and ej.no_escritos == ["hola"], p.log
    p = PantallaMac(que={"rol": "AXGroup", "campo": None, "enlace": False}, foco=True)
    _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola", "verificar_campo": True})
    assert ("escribe", "hola") in p.log, p.log
    p = PantallaMac(que={"rol": "AXTextField", "campo": True, "enlace": False}, foco=True)
    _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola", "verificar_campo": True, "con_texto": True})
    assert p.log == [("clic", 300, 200), ("ctrl+a",), ("escribe", "hola")], p.log


def prueba_las_instrucciones_piden_respuesta_y_luego_donde():
    t = cerebro.SISTEMA_CONTESTAR
    assert t.index('"respuesta"') < t.index('"donde"') < t.index('"acciones"')
    for palabra in ("raya", "angosta", "fondo oscuro", "A#", "AZULES", "NARANJAS", "enlaces"):
        assert palabra in t, palabra


def prueba_si_no_escribio_avisa_la_respuesta_de_la_ia():
    p = PantallaWin("flecha")
    cajas = _quiz(p)
    cli = ClienteFases(
        ubicar=lambda t: {"hay_pregunta": True, "caja": [60, 20, 900, 660], "tipo": "abierta"},
        contestar=lambda t: {"tipo": "abierta", "respuesta": "Cervantes",
                             "acciones": [{"hacer": "escribir", "en": {"x": 600, "y": 400}, "texto": "zzz"}]})
    b, c = _bot(cli, p)
    with Parche(cerebro__leer=lambda img, px, py, zoom, ocr: (cajas, []), motor__capturar_zona=p.foto):
        b.contestar(p.img.copy(), 0, 0, 150, 125, 1.0)
    assert p.log == [], p.log
    ev = _eventos(b)
    assert any(e[0] == "actividad" and "Respuesta: Cervantes" in e[1] for e in ev), ev


def prueba_si_la_ia_senala_algo_que_no_es_campo_usa_el_campo_de_la_pagina():
    img = Image.new("RGB", (900, 650), "white")
    campos = [campo(20, 0, 880, 28)]                                       # (la barra de titulo parece caja)
    ctl = [control(150, 300, 650, 344, "campo", "Escriba su respuesta")]
    plan = cerebro.planear({"acciones": [{"hacer": "escribir", "en": "C0", "texto": "4"}]}, CAJAS, campos, 1.0, img, controles=ctl)
    assert len(plan.pasos) == 1 and plan.pasos[0]["seguro_campo"], (plan.pasos, plan.rechazadas)
    assert abs(plan.pasos[0]["p"][1] - 322) < 3, plan.pasos
    # dos campos y dos respuestas: cada una al suyo (y no repite campo)
    ctl2 = [control(150, 300, 650, 344, "campo"), control(150, 420, 650, 464, "campo")]
    plan = cerebro.planear({"acciones": [{"hacer": "escribir", "en": {"x": 400, "y": 330}, "texto": "a"},
                                         {"hacer": "escribir", "en": "C0", "texto": "b"}]}, CAJAS, campos, 1.0, img, controles=ctl2)
    assert [round(p["p"][1]) for p in plan.pasos] == [322, 442], plan.pasos


# ---------------------------------------------------------------- 2.1.1: graficas tipo MyLab y Cmd/Ctrl + A

def _mylab(zoom=1.0, cruz=(0, 5)):
    """Plano como el de MyLab / Pearson: cuadricula punteada, rayitas, numeros de 2 en 2 y la cruz del mouse."""
    from PIL import ImageFont
    z = lambda v: int(round(v * zoom))                       # noqa: E731
    img = Image.new("RGB", (z(700), z(640)), "white")
    d = ImageDraw.Draw(img)
    x0, y0, paso = z(40), z(20), z(28)
    f = ImageFont.load_default(size=z(15))
    px = lambda g: x0 + (g + 10) * paso                       # noqa: E731
    py = lambda g: y0 + (10 - g) * paso                       # noqa: E731
    d.rectangle([x0 - z(6), y0 - z(6), px(10) + z(6), py(-10) + z(6)], outline=(0, 0, 0), width=max(1, z(1)))
    for k in range(-10, 11):
        for t in range(int(y0), int(py(-10)), z(4)):
            d.point((px(k), t), fill=(60, 60, 60))
            d.point((t - y0 + x0, py(k)), fill=(60, 60, 60))
    d.line([px(-10), py(0), px(10), py(0)], fill=(0, 0, 0), width=max(1, z(1)))
    d.line([px(0), py(10), px(0), py(-10)], fill=(0, 0, 0), width=max(1, z(1)))
    for k in range(-10, 11, 2):
        if k == 0:
            continue
        t = str(k)
        bw = d.textlength(t, font=f)
        d.text((px(k) - bw / 2, py(0) + z(14)), t, fill=(0, 0, 0), font=f)
        d.text((px(0) - bw - z(10), py(k) - z(8)), t, fill=(0, 0, 0), font=f)
        d.line([px(k), py(0) - z(5), px(k), py(0) + z(5)], fill=(0, 0, 0))
        d.line([px(0) - z(5), py(k), px(0) + z(5), py(k)], fill=(0, 0, 0))
    d.line([x0, py(cruz[1]), px(10), py(cruz[1])], fill=(0, 0, 0), width=z(2))
    d.line([px(cruz[0]), y0, px(cruz[0]), py(-10)], fill=(0, 0, 0), width=z(2))
    return img, px, py


def prueba_grafica_tipo_mylab_traza_la_recta_en_su_lugar():
    from clw.ocr import OCR
    ocr = OCR()
    if not ocr.disponible:
        print("    (sin OCR en esta maquina: se salta)")
        return
    for zoom in (1.0, 2.0):
        img, px, py = _mylab(zoom)
        cajas = motor.detectar_cajas(img, img.width / 2, img.height / 2, zoom, ocr)
        datos = {"tipo": "graficar", "respuesta": "y = 2x + 2", "acciones": [
            {"hacer": "clic", "en": {"gx": 0, "gy": 2}}, {"hacer": "clic", "en": {"gx": -1, "gy": 0}},
            {"hacer": "escribir", "en": {"x": 300, "y": 300}, "texto": "y=2x+2"}]}
        plan = cerebro.planear(datos, cajas, [], 1.0, img, zoom, ocr=ocr)
        puntos = [p["p"] for p in plan.pasos if p["hacer"] == "clic"]
        assert len(puntos) == 2, (zoom, plan.pasos, plan.rechazadas)
        for (x, y), (gx, gy) in zip(puntos, ((0, 2), (-1, 0))):
            assert abs(x - px(gx)) <= 2 and abs(y - py(gy)) <= 2, (zoom, (x, y), (px(gx), py(gy)))
        assert not any(p["hacer"] == "escribir" for p in plan.pasos), plan.pasos      # en una grafica no se escribe


def prueba_campo_vacio_no_selecciona_todo():
    img = Image.new("RGB", (900, 650), "white")
    plan = cerebro.planear({"acciones": [{"hacer": "escribir", "en": "C0", "texto": "1910"}]}, CAJAS,
                           [campo(150, 300, 650, 344)], 1.0, img)
    p = Pantalla()
    _escribe(p, plan.pasos[0])
    assert p.log == [("clic", 400, 322), ("escribe", "1910")], p.log           # sin Ctrl + A
    cajas = CAJAS + [caja(160, 310, 260, 334, "1810")]                          # ya tenia algo: si lo reemplaza
    plan = cerebro.planear({"acciones": [{"hacer": "escribir", "en": "C0", "texto": "1910"}]}, cajas,
                           [campo(150, 300, 650, 344)], 1.0, img)
    p = Pantalla()
    _escribe(p, plan.pasos[0])
    assert ("ctrl+a",) in p.log, p.log


def prueba_las_instrucciones_no_arrastran_para_trazar():
    assert "SOLO clics en los puntos: NUNCA arrastres, NUNCA traces" in cerebro.SISTEMA_CONTESTAR


# ---------------------------------------------------------------- 2.2: graficas de muchos estilos

def _plano_estilo(zoom=1.0, xr=(-10, 10), yr=(-10, 10), cada=1, etiqueta=2, unidad=28, rayitas="cruz", grilla="puntos",
          origen_borde=False, tam_letra=15, halo=False, fmt=None, cruz=None, eje=(0, 0, 0), num=(0, 0, 0),
          fondo=(255, 255, 255), col_grilla=None, solo_y=None, sin_numeros=False):
    z = lambda v: v * zoom
    nx, ny = round((xr[1] - xr[0]) / cada), round((yr[1] - yr[0]) / cada)
    u = z(unidad)
    x0, y0 = z(60), z(30)
    W, H = int(x0 + nx * u + z(60)), int(y0 + ny * u + z(60))
    img = Image.new("RGB", (W, H), fondo); d = ImageDraw.Draw(img)
    f = __import__('PIL.ImageFont', fromlist=['x']).load_default(size=int(z(tam_letra)))
    px = lambda g: x0 + (g - xr[0]) / cada * u
    py = lambda g: y0 + (yr[1] - g) / cada * u
    ax_y = 0 if xr[0] <= 0 <= xr[1] and not origen_borde else xr[0]     # columna del eje y (valor de x)
    ax_x = 0 if yr[0] <= 0 <= yr[1] and not origen_borde else yr[0]
    for k in range(nx + 1):
        g = xr[0] + k * cada; X = px(g)
        if grilla == "puntos":
            for t in range(int(y0), int(py(yr[0])), int(z(4))): d.point((X, t), fill=col_grilla or (60, 60, 60))
        elif grilla == "lineas":
            d.line([X, y0, X, py(yr[0])], fill=col_grilla or ((225, 225, 225) if round(g / cada) % 2 else (190, 190, 190)), width=max(1, int(z(1))))
    for k in range(ny + 1):
        g = yr[0] + k * cada; Y = py(g)
        if grilla == "puntos":
            for t in range(int(x0), int(px(xr[1])), int(z(4))): d.point((t, Y), fill=col_grilla or (60, 60, 60))
        elif grilla == "lineas":
            d.line([x0, Y, px(xr[1]), Y], fill=col_grilla or ((225, 225, 225) if round(g / cada) % 2 else (190, 190, 190)), width=max(1, int(z(1))))
    w = max(1, int(z(1.5)))
    d.line([px(xr[0]) - z(8), py(ax_x), px(xr[1]) + z(8), py(ax_x)], fill=eje, width=w)
    d.line([px(ax_y), py(yr[1]) - z(8), px(ax_y), py(yr[0]) + z(8)], fill=eje, width=w)
    fmt = fmt or (lambda v: str(int(v)) if float(v).is_integer() else str(v))
    for k in range(nx + 1):
        g = xr[0] + k * cada
        if rayitas == "cruz": d.line([px(g), py(ax_x) - z(5), px(g), py(ax_x) + z(5)], fill=eje, width=max(1, int(z(1))))
        elif rayitas == "abajo": d.line([px(g), py(ax_x), px(g), py(ax_x) + z(6)], fill=eje, width=max(1, int(z(1))))
        if abs(round(g / etiqueta) * etiqueta - g) < 1e-9 and g != ax_y and not sin_numeros:
            t = fmt(g); bw = d.textlength(t, font=f)
            if halo: d.rectangle([px(g) - bw / 2 - z(2), py(ax_x) + z(9), px(g) + bw / 2 + z(2), py(ax_x) + z(9) + z(tam_letra) + z(2)], fill=fondo)
            d.text((px(g) - bw / 2, py(ax_x) + z(10)), t, fill=num, font=f)
    for k in range(ny + 1):
        g = yr[0] + k * cada
        if rayitas == "cruz": d.line([px(ax_y) - z(5), py(g), px(ax_y) + z(5), py(g)], fill=eje, width=max(1, int(z(1))))
        elif rayitas == "abajo": d.line([px(ax_y) - z(6), py(g), px(ax_y), py(g)], fill=eje, width=max(1, int(z(1))))
        lleva = abs(round(g / etiqueta) * etiqueta - g) < 1e-9 if solo_y is None else g in solo_y
        if lleva and g != ax_x and not sin_numeros:
            t = fmt(g); bw = d.textlength(t, font=f)
            if halo: d.rectangle([px(ax_y) - bw - z(12), py(g) - z(tam_letra) / 2 - z(1), px(ax_y) - z(8), py(g) + z(tam_letra) / 2 + z(2)], fill=fondo)
            d.text((px(ax_y) - bw - z(10), py(g) - z(tam_letra) * 0.55), t, fill=num, font=f)
    if cruz:
        d.line([x0, py(cruz[1]), px(xr[1]), py(cruz[1])], fill=eje, width=int(z(2)))
        d.line([px(cruz[0]), y0, px(cruz[0]), py(yr[0])], fill=eje, width=int(z(2)))
    return img, px, py


ESTILOS_GRAFICA = {
    "mylab": dict(cruz=(0, 5)),
    "cada_rayita_-5a5": dict(xr=(-5, 5), yr=(-5, 5), etiqueta=1, unidad=50, grilla="lineas"),
    "de_5_en_5": dict(xr=(-20, 20), yr=(-20, 20), cada=5, etiqueta=5, unidad=30, tam_letra=16),
    "desmos": dict(rayitas="ninguna", grilla="lineas", halo=True, etiqueta=2, unidad=30),
    "primer_cuadrante": dict(xr=(0, 10), yr=(0, 10), etiqueta=1, unidad=40, rayitas="abajo", grilla="lineas", origen_borde=True),
    "y_de_10_en_10": dict(xr=(0, 10), yr=(0, 100), cada=1, etiqueta=1, unidad=36, rayitas="abajo", grilla="lineas", origen_borde=True),
    "decimales": dict(xr=(-2, 2), yr=(-2, 2), cada=0.5, etiqueta=0.5, unidad=60, grilla="lineas"),
    # 2.5.1: los que no salian (ejes grises o de color, tema oscuro, numeros chiquitos de 1 en 1, pocos numeros en y)
    "ejes_grises": dict(eje=(138, 138, 138), num=(100, 100, 100), grilla="lineas", col_grilla=(225, 228, 235)),
    "ejes_azules": dict(eje=(59, 111, 216), num=(59, 111, 216), grilla="lineas", col_grilla=(225, 228, 235)),
    "tema_oscuro": dict(fondo=(30, 30, 30), eje=(235, 235, 235), num=(235, 235, 235), grilla="lineas",
                        col_grilla=(60, 60, 60)),
    "chiquitos_de_1_en_1": dict(etiqueta=1, unidad=20, tam_letra=11, grilla="lineas", col_grilla=(213, 216, 226),
                                num=(51, 51, 51)),
    "pocos_numeros_en_y": dict(solo_y=(4, -6), grilla="lineas"),
}


def prueba_ejes_de_graficas_de_muchos_estilos():
    from clw.ocr import OCR
    ocr = OCR()
    if not ocr.disponible:
        print("    (sin OCR en esta maquina: se salta)")
        return
    malas = []
    for nombre, op in ESTILOS_GRAFICA.items():
        for zoom in (1.0, 2.0):
            img, px, py = _plano_estilo(zoom, **op)
            pl = motor.ejes_del_plano(img, zoom, ocr)
            if not (pl["x"] and pl["y"]):
                malas.append((nombre, zoom, "no leyo los ejes"))
                continue
            xr, yr = op.get("xr", (-10, 10)), op.get("yr", (-10, 10))
            for g in ((xr[0], yr[0]), (xr[1], yr[1]), ((xr[0] + xr[1]) / 2, (yr[0] + yr[1]) / 2)):
                X, Y = pl["x"][0] * g[0] + pl["x"][1], pl["y"][0] * g[1] + pl["y"][1]
                if max(abs(X - px(g[0])), abs(Y - py(g[1]))) > 2 * zoom:
                    malas.append((nombre, zoom, g, (round(X), round(Y)), (round(px(g[0])), round(py(g[1])))))
    assert not malas, malas


def prueba_sin_grafica_no_inventa_ejes():
    from clw.ocr import OCR
    ocr = OCR()
    if not ocr.disponible:
        return
    for zoom in (1.0, 2.0):
        pl = motor.ejes_del_plano(_escena_campos(zoom), zoom, ocr)
        assert not pl["x"] and not pl["y"], pl


def prueba_grafica_solo_puntos_y_no_repite_clics_del_plano():
    img = Image.new("RGB", (700, 640), "white")
    plano = {"x": (28.0, 320.0), "y": (-28.0, 300.0), "rango": {"x": (-10, 10, 1), "y": (-10, 10, 1)}}
    cajas = [caja(600, 20, 660, 44, "Recta")]
    datos = {"tipo": "graficar", "respuesta": "y = 2x + 2", "acciones": [
        {"hacer": "clic", "en": 0, "texto": "Recta"},
        {"hacer": "clic", "en": {"gx": 0, "gy": 2}}, {"hacer": "clic", "en": {"gx": -1, "gy": 0}}]}
    plan = cerebro.planear(datos, cajas, [], 1.0, img, 1.0, plano=plano)
    # 2.5: la herramienta la elige el usuario: solo se pican los puntos
    assert [p["p"] for p in plan.pasos] == [(320, 244), (292, 300)], plan.pasos
    assert [p.get("plano") for p in plan.pasos] == [True, True]
    p = Pantalla(w=700, h=640, perder=5)          # (la pagina no cambia al dar clic)
    ej = cerebro.Ejecutor(p, 0, 0, (0, 0, 700, 640), foto=lambda: p.foto(0, 0, 700, 640), pausa=0)
    ej.correr(plan.pasos)
    clics = p.clics()
    assert clics.count(("clic", 320, 244)) == 1 and clics.count(("clic", 292, 300)) == 1, clics   # sin repetir
    assert "PLANO CARTESIANO" in motor.describir_plano(plano, 1.0)


# ---------------------------------------------------------------- 2.2: la calculadora corrige cuentas mal hechas

def prueba_calculadora_segura():
    assert cerebro.calcular("6*8") == 48
    assert abs(cerebro.calcular("sqrt(3^2+4^2)") - 5) < 1e-9
    assert abs(cerebro.calcular("sind(30)") - 0.5) < 1e-9
    assert abs(cerebro.calcular("2*pi*3") - 18.849555921538759) < 1e-9
    for malo in ("__import__('os').system('x')", "open('a')", "9**9**9", "a+1", "", "1/0"):
        assert cerebro.calcular(malo) is None, malo


def prueba_si_la_cuenta_no_cuadra_escribe_la_correcta():
    img = Image.new("RGB", (900, 650), "white")
    datos = {"tipo": "numerica", "respuesta": "47", "calculo": "6*8",
             "acciones": [{"hacer": "escribir", "en": "C0", "texto": "47"}]}
    plan = cerebro.planear(datos, CAJAS, [campo(150, 300, 650, 344)], 1.0, img)
    assert plan.pasos[0]["texto"] == "48" and plan.respuesta == "48", (plan.pasos, plan.correcciones)
    # con decimales: respeta los decimales que uso la IA
    datos = {"tipo": "numerica", "calculo": "100/7", "acciones": [{"hacer": "escribir", "en": "C0", "texto": "14.82"}]}
    plan = cerebro.planear(datos, CAJAS, [campo(150, 300, 650, 344)], 1.0, img)
    assert plan.pasos[0]["texto"] == "14.29", plan.pasos
    # si solo es redondeo (la pregunta pedia redondear antes), no se toca
    datos = {"tipo": "numerica", "calculo": "100/7", "acciones": [{"hacer": "escribir", "en": "C0", "texto": "14.3"}]}
    plan = cerebro.planear(datos, CAJAS, [campo(150, 300, 650, 344)], 1.0, img)
    assert plan.pasos[0]["texto"] == "14.3" and not plan.correcciones, plan.pasos
    # varios campos: una operacion por campo, en orden
    datos = {"tipo": "numerica", "calculo": ["2+2", "3*3"], "acciones": [
        {"hacer": "escribir", "en": "C0", "texto": "4"}, {"hacer": "escribir", "en": "C1", "texto": "6"}]}
    plan = cerebro.planear(datos, CAJAS, [campo(150, 300, 650, 344), campo(150, 400, 650, 444)], 1.0, img)
    assert [p["texto"] for p in plan.pasos] == ["4", "9"], plan.pasos


def prueba_grafica_real_de_windows_con_cuadricula_encima_de_los_numeros():
    """Captura de verdad (autoprueba en Windows): las lineas punteadas pasan por encima de los numeros."""
    from clw.ocr import OCR
    ocr = OCR()
    if not ocr.disponible:
        return
    img = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos", "grafica_windows.png")).convert("RGB")
    pl = motor.ejes_del_plano(img, 1.0, ocr)
    assert pl["x"] and pl["y"], pl
    x0, y2 = pl["x"][1], pl["y"][0] * 2 + pl["y"][1]
    assert abs(x0 - 418) <= 2 and abs(y2 - 309) <= 2, pl


def prueba_si_ubicar_no_contesta_sigue_con_lo_del_puntero():
    class Lenta(Exception):
        tipo = "red"

    def preguntar(b64, mime, texto, fase=None, esfuerzo=None):
        raise Lenta("timed out")
    img = Image.new("RGB", (800, 600), "white")
    ub = cerebro.ubicar(img, 400, 300, preguntar)
    assert ub.hay and ub.respaldo and ub.region == (0, 0, 800, 600)


def prueba_plan_basico_no_contesta_graficas_solo_avisa():
    from clw import licencia
    p = Pantalla()
    cajas = _quiz(p)
    cli = ClienteFases(
        ubicar=lambda t: {"hay_pregunta": True, "caja": [60, 20, 900, 660], "tipo": "graficar"},
        contestar=lambda t: {"tipo": "graficar", "respuesta": "y = 2x + 2",
                             "acciones": [{"hacer": "clic", "en": {"x": 300, "y": 300}}]})
    b, c = _bot(cli, p)

    class Est:
        activa, plan, nombre_plan, motivo, mensaje = True, "basico", "Básico", "ok", ""
    with Parche(cerebro__leer=lambda img, px, py, zoom, ocr: (cajas, []), motor__capturar_zona=p.foto,
                licencia__estado=lambda config: Est()):
        b.contestar(p.img.copy(), 0, 0, 150, 125, 1.0)
    assert p.log == [], p.log
    act = [e[1] for e in _eventos(b) if e[0] == "actividad"]
    # avisa que es del Pro, sin decir la respuesta (y ni la resuelve: la vista ya dijo que es grafica)
    assert any("plan Pro" in a for a in act) and not any("y = 2x + 2" in a for a in act), act


def prueba_planos_de_chrome_que_no_salian():
    """2.5.1: capturas de Chrome de planos que antes no se leian: numeros chiquitos de 1 en 1 (ALEKS), cuadricula
    punteada (MyLab), tema oscuro y ejes grises. En todas el origen esta en (240, 240) y cada rayita mide 19 px."""
    from clw.ocr import OCR
    ocr = OCR()
    if not ocr.disponible:
        return
    malas = []
    for n in ("aleks_1en1", "mylab_punteada", "oscuro", "ejes_grises"):
        img = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos", f"plano_{n}.png")).convert("RGB")
        pl = motor.ejes_del_plano(img, 1.0, ocr)
        if not (pl["x"] and pl["y"]):
            malas.append((n, pl["x"], pl["y"]))
            continue
        for v in (-10, 10):
            if abs(pl["x"][0] * v + pl["x"][1] - (240 + 19 * v)) > 2 or abs(pl["y"][0] * v + pl["y"][1] - (240 - 19 * v)) > 2:
                malas.append((n, v, pl["x"], pl["y"]))
    assert not malas, malas


def prueba_grafica_sin_numeros_legibles_usa_los_ejes_de_la_ia():
    """Si NO LIMIT ve los ejes y sus rayitas pero no puede leer los numeros, la IA dice dos numeros de cada eje con
    su pixel (aunque mida con error) y se pegan a las rayitas: los puntos quedan exactos."""
    from clw.ocr import OCR
    ocr = OCR()
    if not ocr.disponible:
        return
    img, px, py = _plano_estilo(1.0, sin_numeros=True, grilla="lineas")
    pl = cerebro.plano_de(img, [], 1.0, ocr)
    assert not pl["x"] and not pl["y"] and set(pl["lineas"]) == {"x", "y"}, pl
    # la IA mide con unos pixeles de error (y la imagen que ve la IA esta a escala 0.8)
    s = 0.8
    datos = {"tipo": "graficar", "respuesta": "y = 2x + 2",
             "ejes": {"x": [[-8, (px(-8) + 4) * s], [6, (px(6) - 3) * s]], "y": [[8, (py(8) - 4) * s], [-4, (py(-4) + 3) * s]]},
             "acciones": [{"hacer": "clic", "en": {"gx": 0, "gy": 2}}, {"hacer": "clic", "en": {"gx": -1, "gy": 0}}]}
    plan = cerebro.planear(datos, [], [], s, img, 1.0, ocr=ocr, plano=pl)
    puntos = [p["p"] for p in plan.pasos]
    assert len(puntos) == 2, (plan.pasos, plan.rechazadas)
    for (x, y), (gx, gy) in zip(puntos, ((0, 2), (-1, 0))):
        assert abs(x - px(gx)) <= 1.5 and abs(y - py(gy)) <= 1.5, ((x, y), (px(gx), py(gy)))


def prueba_en_graficas_solo_se_pican_puntos_dentro_del_plano():
    img = Image.new("RGB", (700, 640), "white")
    plano = {"x": (28.0, 320.0), "y": (-28.0, 300.0), "rango": {"x": (-10, 10, 1), "y": (-10, 10, 1)}}
    cajas = [caja(600, 20, 660, 44, "Recta")]
    datos = {"tipo": "graficar", "respuesta": "y = 2x + 2", "acciones": [
        {"hacer": "arrastrar", "desde": {"gx": 0, "gy": 2}, "hasta": {"gx": -1, "gy": 0}},     # trazar: no
        {"hacer": "clic", "en": {"x": 630, "y": 32}},                                        # la herramienta: no
        {"hacer": "clic", "en": {"gx": 12, "gy": 0}},                                        # fuera del plano: no
        {"hacer": "clic", "en": {"gx": 0, "gy": 2}}, {"hacer": "clic", "en": {"gx": -1, "gy": 0}}]}
    plan = cerebro.planear(datos, cajas, [], 1.0, img, 1.0, plano=plano)
    assert [p["hacer"] for p in plan.pasos] == ["clic", "clic"], plan.pasos
    assert [p["p"] for p in plan.pasos] == [(320, 244), (292, 300)], plan.pasos
    assert [m for _, m in plan.rechazadas] == [cerebro.SOLO_PUNTOS] * 3, plan.rechazadas
    # sin plano detectado: un punto {"x","y"} encima de un texto con letras (un boton) tampoco se pica
    plan = cerebro.planear({"tipo": "graficar", "acciones": [{"hacer": "clic", "en": {"x": 630, "y": 32}}]},
                           cajas, [], 1.0, img, 1.0, plano={"x": None, "y": None})
    assert not plan.pasos and plan.rechazadas, plan.pasos


def prueba_arrastrar_etiquetas_que_el_ocr_junto_en_una_caja():
    """En Windows el OCR junta las etiquetas del banco en una caja ("Riñones , Corazón , Pulmones"): con el texto que
    da la IA se agarra la etiqueta de verdad, y los arrastres van del ultimo al primero (al quitar una del banco las
    que faltan no se recorren)."""
    img = Image.new("RGB", (900, 400), "white")
    junta = caja(60, 110, 380, 136, "Riñones , Corazón , Pulmones")
    junta["palabras"] = [("Riñones", 60, 110, 80, 26), (",", 142, 110, 6, 26), ("Corazón", 180, 110, 84, 26),
                         (",", 266, 110, 6, 26), ("Pulmones", 290, 110, 90, 26)]
    cajas = [junta, caja(100, 250, 220, 270, "Suelta aquí"), caja(400, 250, 520, 270, "Suelta aquí")]
    datos = {"tipo": "arrastrar", "acciones": [
        {"hacer": "arrastrar", "desde": 0, "texto": "Corazón", "hasta": 1},
        {"hacer": "arrastrar", "desde": 0, "texto": "Pulmones", "hasta": 2}]}
    plan = cerebro.planear(datos, cajas, [], 1.0, img)
    assert [p["p"] for p in plan.pasos] == [(222.0, 123.0), (335.0, 123.0)], plan.pasos
    assert [p["texto_desde"] for p in plan.pasos] == ["Corazón", "Pulmones"]
    # se arrastra primero la de la derecha (Pulmones) y luego Corazón
    assert [p["desc"] for p in cerebro.orden_de_escritura(plan.pasos)] == ["Pulmones", "Corazón"]


def prueba_buscar_el_plano_en_una_pantalla_sin_plano_es_rapido():
    """En cada pregunta se busca si hay plano: en una pantalla sin plano (escritorio oscuro con una ventana blanca
    llena de texto y lineas) no debe tardar ni gastar OCR de mas."""
    import time
    from clw.ocr import OCR
    ocr = OCR()
    if not ocr.disponible:
        return
    from PIL import ImageFont
    img = Image.new("RGB", (1920, 1080), (12, 12, 14))
    d = ImageDraw.Draw(img)
    d.rectangle([60, 60, 1500, 900], fill="white", outline=(180, 180, 180))
    f = ImageFont.load_default(size=16)
    for k in range(30):
        y = 90 + k * 26
        d.text((90, y), f"{k + 1}. Renglon de texto de una pregunta con numeros 12 34 56 y palabras", fill=(30, 30, 30), font=f)
        if k % 3 == 0:
            d.line([80, y + 22, 1480, y + 22], fill=(150, 150, 150))
    contadas = []
    original = motor._OCRContado.__init__

    def init(self, o, tope):
        original(self, o, tope)
        contadas.append(self)
    motor._OCRContado.__init__ = init
    try:
        t = time.time()
        pl = motor.ejes_del_plano(img, 1.0, ocr)
        dt = time.time() - t
    finally:
        motor._OCRContado.__init__ = original
    assert not pl["x"] and not pl["y"], pl
    assert contadas and contadas[0].usadas <= 10, contadas[0].usadas
    assert dt < 8, dt
