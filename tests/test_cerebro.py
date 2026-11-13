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
    assert [(p["hacer"], p["texto"]) for p in plan.pasos] == [("escribir", "1910")], plan.pasos
    assert len(plan.rechazadas) == 2


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
    s = cerebro._escala(1600, 900, 1280, 1200)
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
    s = cerebro._escala(1000, 600, 1280, 1200)
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
    ev = _eventos(b)
    assert ("estado", "revisando") in ev and any(e[0] == "actividad" and e[1].startswith("Marcó") for e in ev), ev
    assert os.path.exists(os.path.join(os.environ["CLW_DATOS"], "revision", "ultima_revision.png"))


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
