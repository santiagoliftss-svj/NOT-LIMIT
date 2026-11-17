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

    def tecla_abajo(self, vk):
        return False

    def clic(self, x, y):
        self.log.append(("clic", round(x), round(y)))
        if self.perder > 0:
            self.perder -= 1
            return
        ImageDraw.Draw(self.img).ellipse((x - 6, y - 6, x + 6, y + 6), fill=(255, 0, 0))

    def seleccionar_todo(self):
        self.log.append(("ctrl+a",))

    def escribir(self, texto, cancelar=None):
        self.log.append(("escribe", texto))
        ImageDraw.Draw(self.img).rectangle((2, 2, 40, 12), fill=(0, 200, 0))
        return True

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
            m = {"cerebro": cerebro, "motor": motor}[mod]
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
    assert p.log == [("clic", 300, 200), ("ctrl+a",), ("escribe", "x^2"), ("tecla", "derecha"), ("escribe", "+3/4"),
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
    assert len(p.clics()) == 2 and ej.no_escritos == ["hola"]                 # lo intento 2 veces y no tecleo


def prueba_mac_con_cursor_en_campo_si_escribe():
    p = PantallaMac(que={"rol": "AXTextField", "campo": True, "enlace": False}, foco=True)
    _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola"})
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
    assert p.log == [("clic", 300, 200), ("ctrl+a",), ("escribe", "hola")], p.log


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
    _escribe(p, {"hacer": "escribir", "p": (300, 200), "texto": "hola", "verificar_campo": True})
    assert p.log == [("clic", 300, 200), ("ctrl+a",), ("escribe", "hola")], p.log


def prueba_las_instrucciones_piden_respuesta_y_luego_donde():
    t = cerebro.SISTEMA_CONTESTAR
    assert t.index('"respuesta"') < t.index('"donde"') < t.index('"acciones"')
    for palabra in ("raya", "angosta", "fondo oscuro", "A#", "AZULES", "NARANJAS", "enlaces"):
        assert palabra in t, palabra
