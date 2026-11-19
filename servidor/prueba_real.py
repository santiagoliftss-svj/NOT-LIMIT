"""Prueba el servidor en el motor real de Cloudflare (wrangler dev, en la maquina) con Gemini y la pagina de mentiras.

    cd servidor && python prueba_real.py        (necesita wrangler: npm i -g wrangler)
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AQUI = os.path.dirname(os.path.abspath(__file__))
PUERTO = 8787
CLAVE = "CLAVE-SECRETA-DE-PRUEBA"

CODIGOS = {"pro": ("NL-TEST-PRO0-0001", 901), "bas": ("NL-TEST-BAS0-0002", 902), "ven": ("NL-TEST-VEN0-0004", 904)}
LISTA = {"vencen": {"901": "2099-12-31", "902": "2099-12-31", "904": "2020-01-01"},
         "planes": {"902": "basico"}, "limites": {"pro": 3}, "bloqueadas": []}
GEMINI = []


def rapida(codigo):
    n = "".join(ch for ch in codigo.upper() if ch.isalnum())
    n = n[2:] if n.startswith("NL") and len(n) == 14 else n
    n = n.replace("O", "0").replace("I", "1").replace("L", "1")
    return hashlib.pbkdf2_hmac("sha256", n.encode(), b"NO-LIMIT-SRV-1", 2000).hex()


class Falso(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _mandar(self, estado, datos):
        crudo = json.dumps(datos).encode()
        self.send_response(estado)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    def do_GET(self):
        if self.path.startswith("/licencias.json"):
            return self._mandar(200, LISTA)
        self._mandar(404, {})

    def do_POST(self):
        largo = int(self.headers.get("content-length") or 0)
        cuerpo = self.rfile.read(largo)
        GEMINI.append((self.path, self.headers.get("x-goog-api-key"), cuerpo))
        self._mandar(200, {"candidates": [{"content": {"parts": [{"text": "hola"}]}}],
                           "usageMetadata": {"promptTokenCount": 3000, "candidatesTokenCount": 200}})


def pedir(ruta, codigo, equipo="compu-A", pid="p1", metodo="GET", cuerpo=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PUERTO}{ruta}", data=datos, method=metodo, headers={
        "x-nl-codigo": codigo, "x-nl-equipo": equipo, "x-nl-pregunta": pid, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def main():
    falso = ThreadingHTTPServer(("127.0.0.1", 0), Falso)
    threading.Thread(target=falso.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{falso.server_address[1]}"
    huellas = {rapida(c): [n, f"huella{n}"] for c, n in CODIGOS.values()}
    with open(os.path.join(AQUI, ".dev.vars"), "w") as f:
        f.write(f"GEMINI_KEY={CLAVE}\nGEMINI_URL={base}\nLISTA_URL={base}/licencias.json\n")
        f.write(f"HUELLAS_PRUEBA='{json.dumps(huellas)}'\n")
    wr = subprocess.Popen(["wrangler", "dev", "--port", str(PUERTO), "--ip", "127.0.0.1"], cwd=AQUI,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    salida = []
    threading.Thread(target=lambda: [salida.append(l) for l in wr.stdout], daemon=True).start()
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PUERTO}/salud", timeout=2)
                break
            except Exception:
                time.sleep(1)
        else:
            print("".join(salida)[-3000:])
            raise SystemExit("wrangler dev no arranco")

        fallas = []

        def ver(nombre, cond, extra=""):
            print(("ok    " if cond else "FALLA ") + nombre + ("" if cond else f"  {extra}"))
            if not cond:
                fallas.append(nombre)

        pro, bas, ven = CODIGOS["pro"][0], CODIGOS["bas"][0], CODIGOS["ven"][0]
        e, t, _ = pedir("/salud", "")
        ver("salud", e == 200 and json.loads(t)["ia"] is True and CLAVE not in t, t)
        e, t, _ = pedir("/estado", "NL-XXXX-XXXX-XXXX")
        ver("codigo falso -> 401", e == 401, t)
        e, t, _ = pedir("/estado", ven)
        ver("vencido -> 401", e == 401 and "venció" in t, t)
        e, t, _ = pedir("/estado", pro)
        ver("estado del Pro", e == 200 and json.loads(t)["limite"] == 3, t)
        url = "/v1beta/models/gemini-flash-latest:generateContent"
        e, t, h = pedir(url, pro, pid="a", metodo="POST", cuerpo={"contents": []})
        ver("pregunta llega a Gemini con la clave del dueno", e == 200 and GEMINI and GEMINI[-1][1] == CLAVE
            and "gemini-flash-latest" in GEMINI[-1][0], (e, t, GEMINI[-1:]))
        ver("responde y dice cuantas quedan", json.loads(t)["candidates"] and h.get("x-nl-restantes") == "2", h)
        pedir(url, pro, pid="a", metodo="POST", cuerpo={"contents": []})
        pedir(url, pro, pid="b", metodo="POST", cuerpo={"contents": []})
        e, t, h = pedir(url, pro, pid="c", metodo="POST", cuerpo={"contents": []})
        ver("cuenta preguntas (no llamadas) y guarda entre pedidos", e == 200 and h.get("x-nl-restantes") == "0", (e, h))
        e, t, _ = pedir(url, pro, pid="d", metodo="POST", cuerpo={"contents": []})
        ver("se acaba el cupo -> 402", e == 402 and "3 preguntas" in t, t)
        e, t, _ = pedir("/estado", pro, equipo="compu-B")
        ver("otra compu -> 403", e == 403 and "otra compu" in t, t)
        e, t, _ = pedir(url, bas, pid="x", metodo="POST", cuerpo={"contents": []})
        ver("Basico usa el ligero", e == 200 and "gemini-flash-lite-latest" in GEMINI[-1][0], GEMINI[-1][0])
        e, t, _ = pedir("/admin", pro)
        ver("admin solo dueno", e == 403, t)
        print(f"{len(fallas)} fallas")
        return 1 if fallas else 0
    finally:
        wr.terminate()
        try:
            wr.wait(10)
        except Exception:
            wr.kill()
        try:
            os.remove(os.path.join(AQUI, ".dev.vars"))
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
