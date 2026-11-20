"""2.5: varias casillas (ALEKS, juegos de preguntas): cada respuesta en SU casilla, nunca todo en la ultima.

Reproduce lo que pasaba en ALEKS: el usuario hace Ctrl + clic sobre la ultima casilla (el cursor del teclado se
queda ahi) y los clics rapidos en las casillas angostas no mueven el cursor. Antes NO LIMIT escribia la primera
respuesta en la ultima casilla, la borraba con Ctrl + A, escribia la segunda... y las dos primeras quedaban vacias.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from clw import cerebro, motor  # noqa: E402


def _fuente(t):
    for f in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(f, t)
        except OSError:
            pass
    return ImageFont.load_default()


class Aleks:
    """Una pagina con casillas angostas que crecen al escribir. El cursor del teclado se queda donde el usuario dio
    el ultimo clic; los clics RAPIDOS en las casillas 'necias' no lo mueven (como pasaba en ALEKS)."""
    VK_ESCAPE = 0x1B
    Cancelado = type("Cancelado", (Exception,), {})

    def __init__(self, necias=(0, 1), con_foco=None, sabe_foco=False):
        self.casillas = [[120, 60, 131, 84, ""], [250, 60, 261, 84, ""], [380, 60, 391, 84, ""]]
        self.necias = set(necias)
        self.cursor = con_foco                 # indice de la casilla con el cursor del teclado
        self.sabe_foco = sabe_foco             # (como Windows con UI Automation o la Mac)
        self.log = []
        self.seleccion = False
        self.historial = []

    # ---- lo que ve la pantalla
    def img(self):
        im = Image.new("RGB", (560, 160), "white")
        d = ImageDraw.Draw(im)
        f = _fuente(16)
        for i, (x0, y0, x1, y1, t) in enumerate(self.casillas):
            d.text((x0 - 46, y0 + 3), ("A =", "b =", "c =")[i], fill=(20, 20, 20), font=f)
            ancho = max(11, 6 + 9 * len(t))
            borde = (40, 90, 220) if self.cursor == i else (120, 140, 230)
            d.rectangle((x0, y0, x0 + ancho, y1), outline=borde, width=2 if self.cursor == i else 1)
            if t:
                d.text((x0 + 3, y0 + 3), t, fill=(0, 0, 0), font=f)
        return im

    def foto(self, left, top, w, h):
        return self.img().crop((left, top, left + w, top + h))

    def _en(self, x, y):
        for i, (x0, y0, x1, y1, t) in enumerate(self.casillas):
            ancho = max(11, 6 + 9 * len(t))
            if x0 - 1 <= x <= x0 + ancho + 1 and y0 - 1 <= y <= y1 + 1:
                return i
        return None

    # ---- mouse y teclado
    def tecla_abajo(self, vk):
        return False

    def mover(self, x, y):
        pass

    def clic(self, x, y, lento=False):
        self.log.append(("clic", round(x), round(y), lento))
        i = self._en(x, y)
        if i is None:
            return
        if i in self.necias and not lento:
            return                              # el clic rapido no entra
        self.cursor = i
        self.seleccion = False

    def seleccionar_todo(self):
        self.log.append(("ctrl+a",))
        self.seleccion = True

    def escribir(self, texto, cancelar=None):
        self.log.append(("escribe", texto, self.cursor))
        if self.cursor is None:
            return True
        c = self.casillas[self.cursor]
        self.historial.append((self.cursor, c[4]))
        c[4] = texto if self.seleccion else c[4] + texto
        self.seleccion = False
        return True

    def deshacer(self):
        self.log.append(("deshacer",))
        if self.historial:
            i, antes = self.historial.pop()
            self.casillas[i][4] = antes

    def foco_caja(self):
        if not self.sabe_foco:
            return None
        if self.cursor is None:
            return {"editable": None, "caja": None}
        x0, y0, x1, y1, t = self.casillas[self.cursor]
        return {"editable": True, "caja": (x0, y0, x0 + max(11, 6 + 9 * len(t)), y1)}

    def textos(self):
        return [c[4] for c in self.casillas]


def _plan(p):
    campos = [{"caja": (c[0], c[1], c[2], c[3]), "cx": (c[0] + c[2]) / 2, "cy": (c[1] + c[3]) / 2} for c in p.casillas]
    datos = {"tipo": "numerica", "respuesta": "39 | 41.1 | 34.6", "acciones": [
        {"hacer": "escribir", "en": "C0", "texto": "39"},
        {"hacer": "escribir", "en": "C1", "texto": "41.1"},
        {"hacer": "escribir", "en": "C2", "texto": "34.6"}]}
    cajas = [{"texto": "U", "caja": (c[0], c[1], c[2], c[3]), "cx": (c[0] + c[2]) / 2, "cy": (c[1] + c[3]) / 2}
             for c in p.casillas]                                   # el OCR lee la orilla de la cajita como "U"
    return cerebro.planear(datos, cajas, campos, 1.0, p.img())


def _correr(p):
    plan = _plan(p)
    ej = cerebro.Ejecutor(p, 0, 0, (0, 0, 560, 160), foto=lambda: p.foto(0, 0, 560, 160), pausa=0)
    ej.correr(plan.pasos)
    return plan, ej


def prueba_la_orilla_de_una_cajita_no_es_texto():
    p = Aleks()
    plan = _plan(p)
    assert all(not paso["con_texto"] for paso in plan.pasos), plan.pasos     # sin Ctrl + A en casillas vacias


def prueba_aleks_cada_respuesta_en_su_casilla_aunque_el_cursor_este_en_la_ultima():
    p = Aleks(necias=(0, 1), con_foco=2)
    plan, ej = _correr(p)
    assert p.textos() == ["39", "41.1", "34.6"], (p.textos(), p.log, ej.fallas)
    assert ("ctrl+a",) not in p.log, p.log                          # nunca se selecciono toda la pagina


def prueba_aleks_con_windows_o_mac_que_dicen_donde_esta_el_cursor():
    p = Aleks(necias=(0, 1), con_foco=2, sabe_foco=True)
    plan, ej = _correr(p)
    assert p.textos() == ["39", "41.1", "34.6"], (p.textos(), p.log, ej.fallas)
    # con el foco sabido, nunca tecleo en la casilla equivocada (ni tuvo que deshacer)
    assert ("deshacer",) not in p.log, p.log


def prueba_si_una_casilla_no_se_deja_no_ensucia_las_otras():
    p = Aleks(necias=(0, 1, 2), con_foco=2)
    p.casillas[2][4] = ""
    for c in (0, 1):
        p.necias.add(c)

    class Imposible(Aleks):
        def clic(self, x, y, lento=False):              # ninguna casilla acepta clics: el cursor no se mueve
            self.log.append(("clic", round(x), round(y), lento))
    q = Imposible(necias=(0, 1, 2), con_foco=2)
    plan, ej = _correr(q)
    # lo que se haya escrito en la ultima por error se deshizo; las respuestas se avisan
    assert q.textos()[0] == "" and q.textos()[1] == "", q.textos()
    assert q.textos()[2] in ("", "34.6"), q.textos()
    assert len(ej.no_escritos) >= 2, ej.no_escritos


def prueba_se_llenan_de_la_ultima_a_la_primera():
    pasos = [{"hacer": "escribir", "p": (125, 72), "caja": (120, 60, 131, 84), "texto": "a"},
             {"hacer": "escribir", "p": (255, 72), "caja": (250, 60, 261, 84), "texto": "b"},
             {"hacer": "clic", "p": (40, 140)},
             {"hacer": "escribir", "p": (125, 120), "caja": (120, 108, 131, 132), "texto": "c"},
             {"hacer": "escribir", "p": (255, 120), "caja": (250, 108, 261, 132), "texto": "d"}]
    orden = [p.get("texto", "clic") for p in cerebro.orden_de_escritura(pasos)]
    assert orden == ["b", "a", "clic", "d", "c"], orden


def prueba_detecta_cajitas_angostas_como_campos():
    p = Aleks()
    im = p.img()
    rects = motor.rectangulos(im, 1.0)
    for c in p.casillas:
        assert any(abs(r[0] - c[0]) <= 2 and abs(r[1] - c[1]) <= 2 for r in rects), (c, rects)
    # pero un cuadrito (una casilla de marcar) NO es campo para escribir
    im2 = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(im2).rectangle((40, 40, 56, 56), outline=(60, 60, 60), width=2)
    assert not motor.rectangulos(im2, 1.0), motor.rectangulos(im2, 1.0)


# ---------------------------------------------------------------- menus "Seleccionar", flechas y graficas

def _c(x0, y0, x1, y1, t):
    return {"texto": t, "caja": (x0, y0, x1, y1), "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2}


def prueba_opciones_de_dos_renglones_se_juntan():
    cajas = [_c(80, 405, 260, 422, "Democracia ateniense y"), _c(80, 428, 210, 445, "filosofia clasica"),
             _c(80, 480, 200, 497, "Construccion de"), _c(80, 503, 250, 520, "acueductos y derecho"),
             _c(80, 526, 150, 543, "romano"), _c(80, 580, 270, 597, "Invencion de la imprenta de"),
             _c(80, 603, 190, 620, "tipos moviles")]
    ops = cerebro.opciones_del_menu(cajas)
    mejor = max(ops, key=lambda o: motor.parecido("Democracia ateniense y filosofía clásica", o[0]))
    assert mejor[0] == "Democracia ateniense y filosofia clasica", ops
    assert abs(mejor[1][1] - 413.5) < 1, mejor                    # se pica el primer renglon de la opcion
    mejor = max(ops, key=lambda o: motor.parecido("Construcción de acueductos y derecho romano", o[0]))
    assert mejor[0] == "Construccion de acueductos y derecho romano", mejor


def prueba_ordenar_con_flechas_sin_arrastrar():
    lista = ["Caida del Imperio romano", "Invencion de la escritura cuneiforme", "Llegada de Colon a America",
             "Inicio de la Revolucion Francesa"]
    objetivo = ["Invencion de la escritura cuneiforme", "Caida del Imperio romano", "Llegada de Colon a America",
                "Inicio de la Revolucion Francesa"]

    class Lista:
        VK_ESCAPE = 0x1B
        Cancelado = type("Cancelado", (Exception,), {})

        def __init__(self):
            self.log = []

        def tecla_abajo(self, vk):
            return False

        def img(self):
            im = Image.new("RGB", (700, 400), "white")
            d = ImageDraw.Draw(im)
            for k, t in enumerate(lista):
                d.text((60, 40 + 80 * k), t, fill=(0, 0, 0), font=_fuente(16))
            return im

        def foto(self):
            return self.img()

        def clic(self, x, y, lento=False):
            self.log.append(("clic", round(x), round(y)))
            k = int((y - 20) // 80)
            if 600 <= x <= 640 and 1 <= k < len(lista):            # la flecha de subir de ese renglon
                lista[k - 1], lista[k] = lista[k], lista[k - 1]

        def arrastrar(self, *a, **k):
            self.log.append(("arrastrar",))

    p = Lista()

    def detectar(img, px, py, zoom, ocr):
        return [_c(60, 40 + 80 * k, 400, 58 + 80 * k, t) for k, t in enumerate(lista)]
    viejo = motor.detectar_cajas
    motor.detectar_cajas = detectar
    try:
        plan = cerebro.planear({"tipo": "ordenar", "acciones": [
            {"hacer": "ordenar", "orden": objetivo, "flechas": {"arriba": {"x": 620, "y": 129}}}]},
            [], [], 1.0, p.img())
        ej = cerebro.Ejecutor(p, 0, 0, (0, 0, 700, 400), foto=p.foto, ocr=object(), pausa=0)
        ej.correr(plan.pasos)
    finally:
        motor.detectar_cajas = viejo
    assert lista == objetivo, (lista, p.log, ej.fallas)
    assert not any(a[0] == "arrastrar" for a in p.log), p.log      # nunca arrastra si hay flechas


def prueba_en_graficas_no_toca_la_barra_de_herramientas():
    im = Image.new("RGB", (600, 600), "white")
    cajas = [_c(20, 20, 80, 40, "Recta")]
    plano = {"x": (25.0, 300.0), "y": (-25.0, 300.0)}
    plan = cerebro.planear({"tipo": "graficar", "acciones": [
        {"hacer": "clic", "en": 0, "texto": "Recta"},
        {"hacer": "clic", "en": {"gx": 0, "gy": 2}}, {"hacer": "clic", "en": {"gx": -1, "gy": 0}}]},
        cajas, [], 1.0, im, plano=plano)
    puntos = [p["p"] for p in plan.pasos]
    assert puntos == [(300.0, 250.0), (275.0, 300.0)], (puntos, plan.rechazadas)
    assert any("solo se pican los puntos" in m for _, m in plan.rechazadas), plan.rechazadas


def prueba_las_instrucciones_nuevas():
    t = cerebro.SISTEMA_CONTESTAR
    for frase in ("NO toques la barra de herramientas", "Seleccionar", "flechas", "VARIAS CASILLAS",
                  "ARRASTRAR Y SOLTAR"):
        assert frase in t, frase


# ---------------------------------------------------------------- lo que salio de probar en Chrome de verdad

def prueba_letras_no_son_casillas_pero_casillas_vacias_si():
    """Una letra (8, B, D) en medio del texto no es una casilla; una casilla vacia (o con el cursor) si."""
    from PIL import Image, ImageDraw, ImageFont
    from clw import motor
    try:
        f = ImageFont.truetype("DejaVuSans.ttf", 26)
    except OSError:
        f = ImageFont.load_default()
    im = Image.new("RGB", (420, 60), "white")
    ImageDraw.Draw(im).text((10, 10), "x = 8 B 0 D [ ] H #", font=f, fill="black")
    assert motor.rectangulos(im, 1.0) == [], motor.rectangulos(im, 1.0)
    im = Image.new("RGB", (200, 60), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((50, 15, 60, 37), outline=(80, 90, 200))                   # vacia (ALEKS)
    d.rectangle((100, 15, 116, 38), outline=(30, 60, 210), width=2)         # con el cursor adentro
    d.line((105, 19, 105, 34), fill=(0, 0, 0))
    assert len(motor.rectangulos(im, 1.0)) == 2, motor.rectangulos(im, 1.0)


def prueba_caja_blanca_en_fondo_morado():
    """La caja para escribir de un juego (blanca, sin orilla) sobre un fondo de color si se ve como campo."""
    from PIL import Image, ImageDraw
    from clw import motor
    im = Image.new("RGB", (700, 300), (70, 23, 143))
    ImageDraw.Draw(im).rounded_rectangle((120, 150, 640, 208), radius=6, fill="white")
    rs = motor.rectangulos(im, 1.0)
    assert any(abs(r[0] - 120) <= 3 and abs(r[2] - 640) <= 3 for r in rs), rs


def prueba_ocr_tolerante_al_comparar():
    from clw import motor
    assert motor.parecido("Llegada de Cristóbal Colón a América (1492)", "Llegada de Crist6bal Col6n a América (1492)") > 0.9
    assert motor.parecido("Sus raíces o ceros son x = 1 y x = 3.", "(_) Sus raices 0 ceros son x =1yx=3.") > 0.6
    assert motor.parecido("La respuesta es 6", "La respuesta es 0") <= 0.3          # los numeros siguen mandando
    assert motor.parecido("H2O", "H2O2") <= 0.3


def prueba_texto_cuadra_si_el_ocr_se_comio_un_numero():
    from clw import cerebro

    def caja(t):
        return {"texto": t, "cx": 0, "cy": 0, "caja": (0, 0, 1, 1)}
    cs = [caja("() Susraíces o ceros son x = 1 y x="), caja("Abre hacia abajo porque el coeficiente principal es positivo."),
          caja("Su vértice se encuentra en x = 2.")]
    assert cerebro._texto_cuadra("Sus raíces o ceros son x = 1 y x = 3.", 0, cs)
    assert not cerebro._texto_cuadra("x = 1 y x = 3", 0, [caja("x = 1 y x = 5"), caja("x = 1 y x = 3")])
    assert not cerebro._texto_cuadra("x = 13", 0, [caja("x = 1"), caja("x = 13")])


def prueba_ordenar_ignora_el_numero_de_lugar():
    from clw import cerebro
    assert cerebro._parecido_renglon("Caída del Imperio romano de Occidente (476 d. C.)",
                                     "1 Caida del Imperio romano de Occidente (476 d. C.)") > 0.9
    assert cerebro._parecido_renglon("Llegada de Cristóbal Colón a América (1492)",
                                     "2 Inicio de la Revolución Francesa (1789)") < 0.6


def prueba_texto_de_ayuda_no_necesita_seleccionar():
    from clw import cerebro

    def caja(t, x, y):
        return {"texto": t, "cx": x, "cy": y, "caja": (x - 40, y - 8, x + 40, y + 8)}
    campo = (100, 100, 500, 150)
    assert cerebro._solo_ayuda(campo, [caja("Escribe tu respuesta", 200, 125)])
    assert not cerebro._solo_ayuda(campo, [caja("Paris", 200, 125)])


def prueba_texto_claro_en_consola_no_es_campo():
    """Un pedazo de consola (texto claro sobre negro) no tiene 'cajas para escribir' (antes salia una falsa)."""
    from PIL import Image
    from clw import motor
    im = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos", "consola_oscura.png")).convert("RGB")
    assert motor.rectangulos(im, 1.0) == [], motor.rectangulos(im, 1.0)


def _celda_con_cajitas(zoom=1.25):
    """Como ALEKS (ley de los cosenos): la celda de una tabla con su titulo y una formula con 3 cajitas de una letra
    (9 x 16 css: 11 x 20 a 125%), amarillas con orilla azul, con exponentes pegados."""
    from PIL import Image, ImageDraw, ImageFont
    z = lambda v: int(round(v * zoom))
    im = Image.new("RGB", (z(560), z(150)), "white")
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("DejaVuSans.ttf", z(13))
        fm = ImageFont.truetype("DejaVuSerif-Italic.ttf", z(15))
    except OSError:
        f = fm = ImageFont.load_default()
    d.rectangle((z(10), z(10), z(540), z(140)), outline=(30, 30, 30))                 # la celda de la tabla
    d.text((z(24), z(22)), "Parte 2: Utilizar la respuesta obtenida en la Parte 1 para llenar los", font=f, fill="black")
    d.text((z(24), z(42)), "espacios vacios.", font=f, fill="black")
    y = z(84)
    d.text((z(40), y), "b  =  x  + h  +", font=fm, fill="black")
    for xx in (z(52), z(82), z(110)):
        d.text((xx, y - z(8)), "2", font=f, fill="black")                             # exponentes
    cajas = []
    for x0, txt in ((z(160), "2 - 2 ·"), (z(222), "·"), (z(240), "")):
        c = (x0, y - z(2), x0 + z(9) - 1, y - z(2) + z(16) - 1)
        d.rectangle(c, fill=(255, 244, 194), outline=(58, 79, 224))
        if txt:
            d.text((c[2] + z(4), y), txt, font=fm, fill="black")
        cajas.append(c)
    return im, cajas


def prueba_cajitas_de_una_letra_dentro_de_una_formula():
    """Las cajitas de ALEKS entre una formula (11 x 20 a 125%) SI son campos; la celda de la tabla NO, aunque la IA
    pique un poquito fuera de la cajita."""
    from clw import motor, cerebro
    for zoom in (1.0, 1.25, 1.5):
        im, cajas = _celda_con_cajitas(zoom)
        rs = motor.rectangulos(im, zoom)
        for c in cajas:
            assert any(abs(r[0] - c[0]) <= 2 and abs(r[1] - c[1]) <= 2 and abs(r[2] - c[2]) <= 2 for r in rs), (zoom, c, rs)
        for c in cajas:
            x, y = c[2] + 3 * zoom, c[1] - 2 * zoom                     # la IA pico un poco arriba a la derecha
            fino = cerebro.refinar_campo(im, x, y, zoom)
            assert fino and abs(fino[0] - (c[0] + c[2]) / 2) <= 2, (zoom, c, fino)


def prueba_dos_respuestas_a_la_misma_casilla_no_se_escriben_encima():
    from PIL import Image
    from clw import cerebro
    im, cajas = _celda_con_cajitas(1.0)
    campos = [{"caja": c, "cx": (c[0] + c[2]) / 2, "cy": (c[1] + c[3]) / 2} for c in cajas]
    datos = {"tipo": "completar", "acciones": [{"hacer": "escribir", "en": "C0", "texto": "a"},
                                               {"hacer": "escribir", "en": "C0", "texto": "a"},
                                               {"hacer": "escribir", "en": "C2", "texto": "x"}]}
    plan = cerebro.planear(datos, [], campos, 1.0, im, 1.0)
    assert [p["texto"] for p in plan.pasos] == ["a", "x"], plan.pasos
    assert plan.rechazadas and "ya lleva" in plan.rechazadas[0][1], plan.rechazadas


def prueba_opciones_que_son_formulas_aunque_el_ocr_las_lea_mal():
    """Lo que leyo el OCR en ALEKS de verdad: 'Ob =(a-X +h' es b² = (a − x)² + h²; una formula partida en pedacitos
    ('Oc', 'x', '+h') tambien cuadra; y si la IA se equivoca de id por uno, se corrige a la que si es."""
    from clw import cerebro

    def caja(x0, y0, x1, y1, t):
        return {"caja": (x0, y0, x1, y1), "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2, "texto": t}
    p1 = [caja(375, 128, 486, 150, "Ob =x +h"), caja(615, 128, 700, 150, "Ob =a -"), caja(709, 128, 719, 150, "c"),
          caja(375, 175, 450, 197, "Ob = a"), caja(456, 175, 478, 197, "-x"), caja(615, 172, 768, 197, "Ob =(a-X +h")]
    assert cerebro._texto_cuadra("b² = (a − x)² + h²", 5, p1)
    assert not cerebro._texto_cuadra("b² = (a − x)² + h²", 3, p1)
    assert cerebro._corregir_id(3, "b² = (a − x)² + h²", p1) == 5
    p3 = [caja(375, 430, 397, 452, "Oc"), caja(405, 430, 430, 452, "x"), caja(455, 430, 484, 452, "+h"),
          caja(375, 388, 525, 410, "Oc =(a-x) +h"), caja(615, 430, 720, 452, "Oc =a -x")]
    assert cerebro._texto_cuadra("c^2 = x^2 + h^2", 0, p3)
    # (lo que no es formula sigue igual de estricto)
    assert not cerebro._es_formula("Sus raíces o ceros son x = 1 y x = 3.")
