// Servidor de NO LIMIT (Cloudflare Worker).
//
// La app ya no lleva clave de IA: manda la captura y el codigo NO LIMIT aqui. El servidor:
//   1. revisa que el codigo exista, este pagado y no este bloqueado (licencias.json de la pagina),
//   2. revisa que no se use en mas compus de las del plan (asi no se comparte),
//   3. cuenta las preguntas del mes (y del dia) contra el limite del plan,
//   4. llama a Gemini con la clave del dueno (secreto GEMINI_KEY, nunca sale de aqui) y regresa la respuesta.
//
// Todo lo que se guarda (uso, compus) vive en un Durable Object con SQLite ("Cuentas").

import { HUELLAS } from "./huellas.js";

const LISTA = "https://santiagoliftss-svj.github.io/NOT-LIMIT/licencias.json";
const GEMINI = "https://generativelanguage.googleapis.com";
const SAL_RAPIDA = "NO-LIMIT-SRV-1";
const VUELTAS_RAPIDA = 2000;

// Lo que trae cada plan (licencias.json puede cambiarlo con "limites", "por_dia" y "equipos")
const LIMITES = { basico: 300, pro: 600, premium: 1200 };
const POR_DIA = { basico: 60, pro: 120, premium: 250 };
const EQUIPOS = { basico: 1, pro: 1, premium: 2 };
const PLAN_NORMAL = "pro";
const NOMBRES = { basico: "Básico", pro: "Pro", premium: "Premium" };

const LLAMADAS_POR_PREGUNTA = 12;      // una pregunta son ~3 llamadas (ubicar, contestar, revisar); mas que esto cuenta otra
const LIBRE_TRAS_HORAS = 72;           // una compu que no se usa en 3 dias deja su lugar (cambio de compu)
const MAX_CUERPO = 8 * 1024 * 1024;

const MODELOS = { lite: "gemini-flash-lite-latest", flash: "gemini-flash-latest", pro: "gemini-pro-latest" };
// dolares por millon de tokens (entrada, salida), para saber cuanto cuesta cada cliente
const PRECIOS = { lite: [0.30, 2.50], flash: [1.50, 7.50], pro: [2.00, 12.00] };

// ---------------------------------------------------------------- utilidades

function json(status, obj, extra = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra },
  });
}

function error(status, tipo, mensaje) {
  return json(status, { error: { tipo, message: mensaje } });
}

export function normalizar(texto) {
  let t = String(texto || "").toUpperCase().replace(/[^0-9A-Z]/g, "");
  if (t.startsWith("NL") && t.length === 14) t = t.slice(2);
  return t.replace(/O/g, "0").replace(/I/g, "1").replace(/L/g, "1");
}

const _rapidas = new Map();
export async function rapida(normal) {
  if (_rapidas.has(normal)) return _rapidas.get(normal);
  const llave = await crypto.subtle.importKey("raw", new TextEncoder().encode(normal), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: new TextEncoder().encode(SAL_RAPIDA), iterations: VUELTAS_RAPIDA },
    llave, 256);
  const hex = [...new Uint8Array(bits)].map((b) => b.toString(16).padStart(2, "0")).join("");
  if (_rapidas.size < 2000) _rapidas.set(normal, hex);
  return hex;
}

export function fechaMx(ms = Date.now()) {
  // AAAA-MM-DD en la hora de Mexico
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Mexico_City", year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date(ms));
}

// ---------------------------------------------------------------- la lista de la pagina (licencias.json)

let _lista = null;
let _listaHasta = 0;

async function obtenerLista(env) {
  const ahora = Date.now();
  if (_lista && ahora < _listaHasta) return _lista;
  try {
    const r = await fetch(`${env.LISTA_URL || LISTA}?t=${Math.floor(ahora / 60000)}`, { headers: { "user-agent": "no-limit-servidor" } });
    if (!r.ok) throw new Error(`lista ${r.status}`);
    const datos = await r.json();
    if (!datos || typeof datos !== "object") throw new Error("lista rara");
    _lista = datos;
    _listaHasta = ahora + 60 * 1000;
  } catch (e) {
    if (!_lista) throw e;
    _listaHasta = ahora + 15 * 1000;   // se usa la ultima que si bajo
  }
  return _lista;
}

function deLista(lista, campo, plan, normal) {
  const v = (lista[campo] || {})[plan];
  return Number.isFinite(v) ? v : normal[plan];
}

export function estadoDe(num, huella, lista, hoy) {
  const plan = String((lista.planes || {})[String(num)] || PLAN_NORMAL).toLowerCase();
  const p = NOMBRES[plan] ? plan : PLAN_NORMAL;
  const duenos = (lista.duenos || []).map(Number);
  const sinLimite = duenos.includes(num) || (lista.sin_limite || []).map(Number).includes(num);
  const base = {
    num, plan: p, nombre: NOMBRES[p], dueno: duenos.includes(num), sinLimite,
    limite: deLista(lista, "limites", p, LIMITES),
    porDia: deLista(lista, "por_dia", p, POR_DIA),
    equipos: deLista(lista, "equipos", p, EQUIPOS),
    reinicio: String((lista.reiniciar_equipos || {})[String(num)] || ""),
    vence: (lista.vencen || {})[String(num)] || null,
  };
  if ((lista.bloqueadas || []).map((h) => String(h).toLowerCase()).includes(huella)) {
    return { ...base, activa: false, motivo: "bloqueado", mensaje: "Ese código está bloqueado. Pídele uno nuevo a quien te vendió NO LIMIT." };
  }
  if (!base.vence) {
    return { ...base, activa: false, motivo: "sin_activar", mensaje: "Tu código todavía no está activado. Paga tu plan y pídele a tu vendedor que lo active." };
  }
  if (String(base.vence) < hoy) {
    return { ...base, activa: false, motivo: "vencido", mensaje: `Tu plan venció el ${base.vence}. Renuévalo para seguir.` };
  }
  return { ...base, activa: true, motivo: "ok" };
}

export function elegirModelo(pedido, estado) {
  const p = String(pedido || "").toLowerCase();
  if (estado.plan === "basico") return "lite";
  if (p.includes("lite")) return "lite";
  if (p.includes("pro")) return estado.dueno ? "pro" : "flash";
  return "flash";
}

export function usoDe(texto) {
  try {
    const u = JSON.parse(texto).usageMetadata || {};
    return { tin: u.promptTokenCount || 0, tout: (u.candidatesTokenCount || 0) + (u.thoughtsTokenCount || 0) };
  } catch {
    return { tin: 0, tout: 0 };
  }
}

async function alCuaderno(env, ruta, datos) {
  const stub = env.CUENTAS.get(env.CUENTAS.idFromName("todas"));
  const r = await stub.fetch(`https://cuentas${ruta}`, { method: "POST", body: JSON.stringify(datos) });
  return r.json();
}

// ---------------------------------------------------------------- el worker

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    if (url.pathname === "/" || url.pathname === "/salud") {
      return json(200, { ok: true, servicio: "NO LIMIT", ia: Boolean(env.GEMINI_KEY) });
    }

    // 1) el codigo
    const normal = normalizar(req.headers.get("x-nl-codigo"));
    if (normal.length !== 12) return error(401, "codigo", "Pega tu código de NO LIMIT (NL-XXXX-XXXX-XXXX).");
    const r0 = await rapida(normal);
    const fila = HUELLAS[r0] || (env.HUELLAS_PRUEBA ? JSON.parse(env.HUELLAS_PRUEBA)[r0] : undefined);   // (solo pruebas)
    if (!fila) return error(401, "codigo", "Ese código no sirve. Revisa que esté completo o pídele uno a quien te vendió NO LIMIT.");
    const [num, huella] = fila;

    let lista;
    try {
      lista = await obtenerLista(env);
    } catch {
      return error(503, "servidor", "No pude revisar tu plan ahorita. Intenta en un momento.");
    }
    const hoy = fechaMx();
    const estado = estadoDe(num, huella, lista, hoy);
    const equipo = String(req.headers.get("x-nl-equipo") || "").slice(0, 80);
    const base = { num, equipo, mes: hoy.slice(0, 7), dia: hoy, ahora: Date.now(),
                   limite: estado.limite, porDia: estado.porDia, maxEquipos: estado.equipos,
                   reinicio: estado.reinicio, sinLimite: estado.sinLimite };

    // 2) consultas sin IA
    if (url.pathname === "/estado") {
      if (!estado.activa) return error(401, estado.motivo, estado.mensaje);
      const r = await alCuaderno(env, "/estado", base);
      if (!r.ok) return error(r.status, r.tipo, r.mensaje);
      return json(200, { ok: true, numero: num, plan: estado.plan, nombre: estado.nombre, vence: estado.vence,
                         limite: estado.sinLimite ? null : estado.limite, usadas: r.usadas,
                         restantes: estado.sinLimite ? null : Math.max(0, estado.limite - r.usadas) });
    }
    if (url.pathname === "/admin") {
      if (!estado.dueno) return error(403, "codigo", "Solo el dueño puede ver esto.");
      return json(200, await alCuaderno(env, "/admin", base));
    }

    // 3) la pregunta a la IA
    const m = url.pathname.match(/^\/v1beta\/models\/([\w.\-]+):generateContent$/);
    if (!m || req.method !== "POST") return error(404, "otro", "No existe.");
    if (!estado.activa) return error(401, estado.motivo, estado.mensaje);
    if (!env.GEMINI_KEY) return error(503, "servidor", "El servidor de NO LIMIT no tiene IA configurada. Avísale a tu vendedor.");
    const cuerpo = await req.text();
    if (cuerpo.length > MAX_CUERPO) return error(413, "peticion", "La captura está demasiado grande.");

    const pid = String(req.headers.get("x-nl-pregunta") || crypto.randomUUID()).slice(0, 64);
    const permiso = await alCuaderno(env, "/permiso", { ...base, pid });
    if (!permiso.ok) return error(permiso.status, permiso.tipo, permiso.mensaje);

    const clase = elegirModelo(m[1], estado);
    const modelo = MODELOS[clase];
    let r;
    try {
      r = await fetch(`${env.GEMINI_URL || GEMINI}/v1beta/models/${modelo}:generateContent`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-goog-api-key": env.GEMINI_KEY },
        body: cuerpo,
      });
    } catch {
      return error(502, "servidor", "La IA no contestó. Intenta otra vez.");
    }
    const texto = await r.text();
    const extra = { "x-nl-modelo": modelo };
    if (permiso.restantes !== null && permiso.restantes !== undefined) extra["x-nl-restantes"] = String(permiso.restantes);

    if (r.ok) {
      const u = usoDe(texto);
      const [pin, pout] = PRECIOS[clase];
      const centavos = (u.tin * pin + u.tout * pout) / 1e6 * 100;
      ctx.waitUntil(alCuaderno(env, "/gasto", { num, mes: base.mes, tin: u.tin, tout: u.tout, centavos }).catch(() => {}));
      return new Response(texto, { status: 200, headers: { "content-type": "application/json; charset=utf-8", ...extra } });
    }
    // errores de Gemini: nunca se pasa nada de la clave del dueno
    if (r.status === 401 || r.status === 403 || /api key|api_key|billing|permission/i.test(texto)) {
      return error(502, "servidor", "El servidor de NO LIMIT tiene un problema con la IA. Avísale a tu vendedor.");
    }
    if (r.status === 429) return error(429, "limite", "La IA está saturada ahorita. Intenta en un momento.");
    if (r.status >= 500) return error(503, "servidor", "La IA está saturada ahorita. Intenta en un momento.");
    // 400 y demas: se pasa tal cual (la app prueba otra variante de "pensar" si el modelo no la acepta)
    return new Response(texto, { status: r.status, headers: { "content-type": "application/json; charset=utf-8", ...extra } });
  },
};

// ---------------------------------------------------------------- el cuaderno (Durable Object con SQLite)

export class Cuentas {
  constructor(state, env) {
    this.sql = state.storage.sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS uso (num INTEGER, mes TEXT, preguntas INTEGER DEFAULT 0, llamadas INTEGER DEFAULT 0, tin INTEGER DEFAULT 0, tout INTEGER DEFAULT 0, centavos REAL DEFAULT 0, PRIMARY KEY (num, mes))");
    this.sql.exec("CREATE TABLE IF NOT EXISTS dia (num INTEGER, dia TEXT, preguntas INTEGER DEFAULT 0, PRIMARY KEY (num, dia))");
    this.sql.exec("CREATE TABLE IF NOT EXISTS preguntas (num INTEGER, mes TEXT, pid TEXT, llamadas INTEGER DEFAULT 0, PRIMARY KEY (num, mes, pid))");
    this.sql.exec("CREATE TABLE IF NOT EXISTS equipos (num INTEGER, equipo TEXT, primero INTEGER, ultimo INTEGER, PRIMARY KEY (num, equipo))");
    this.sql.exec("CREATE TABLE IF NOT EXISTS reinicios (num INTEGER PRIMARY KEY, marca TEXT)");
  }

  uno(q, ...v) {
    const filas = this.sql.exec(q, ...v).toArray();
    return filas.length ? filas[0] : null;
  }

  async fetch(req) {
    const ruta = new URL(req.url).pathname;
    const b = await req.json();
    if (ruta === "/permiso") return Response.json(this.permiso(b));
    if (ruta === "/estado") return Response.json(this.estado(b));
    if (ruta === "/gasto") return Response.json(this.gasto(b));
    if (ruta === "/admin") return Response.json(this.admin(b));
    return Response.json({ ok: false, status: 404, tipo: "otro", mensaje: "No existe." });
  }

  equipo(b) {
    if (b.sinLimite) return null;
    if (b.reinicio) {
      const r = this.uno("SELECT marca FROM reinicios WHERE num = ?", b.num);
      if (!r || r.marca < b.reinicio) {
        this.sql.exec("DELETE FROM equipos WHERE num = ?", b.num);
        this.sql.exec("INSERT OR REPLACE INTO reinicios (num, marca) VALUES (?, ?)", b.num, b.reinicio);
      }
    }
    if (!b.equipo) return { ok: false, status: 400, tipo: "equipo", mensaje: "Actualiza NO LIMIT a la versión nueva." };
    const ya = this.uno("SELECT ultimo FROM equipos WHERE num = ? AND equipo = ?", b.num, b.equipo);
    if (ya) {
      this.sql.exec("UPDATE equipos SET ultimo = ? WHERE num = ? AND equipo = ?", b.ahora, b.num, b.equipo);
      return null;
    }
    const otros = this.sql.exec("SELECT equipo, ultimo FROM equipos WHERE num = ? ORDER BY ultimo ASC", b.num).toArray();
    if (otros.length >= b.maxEquipos) {
      const viejo = otros[0];
      if (b.ahora - viejo.ultimo < LIBRE_TRAS_HORAS * 3600 * 1000) {
        const n = b.maxEquipos === 1 ? "otra compu" : `otras ${b.maxEquipos} compus`;
        return { ok: false, status: 403, tipo: "equipo",
                 mensaje: `Tu código ya se está usando en ${n}. Cada código es para ${b.maxEquipos === 1 ? "una compu" : `${b.maxEquipos} compus`}. Si cambiaste de compu, pídele a tu vendedor que la libere.` };
      }
      this.sql.exec("DELETE FROM equipos WHERE num = ? AND equipo = ?", b.num, viejo.equipo);
    }
    this.sql.exec("INSERT INTO equipos (num, equipo, primero, ultimo) VALUES (?, ?, ?, ?)", b.num, b.equipo, b.ahora, b.ahora);
    return null;
  }

  usadas(b) {
    const u = this.uno("SELECT preguntas FROM uso WHERE num = ? AND mes = ?", b.num, b.mes);
    return u ? u.preguntas : 0;
  }

  estado(b) {
    const malo = this.equipo(b);
    if (malo) return malo;
    return { ok: true, usadas: this.usadas(b) };
  }

  permiso(b) {
    const malo = this.equipo(b);
    if (malo) return malo;
    let usadas = this.usadas(b);
    const p = this.uno("SELECT llamadas FROM preguntas WHERE num = ? AND mes = ? AND pid = ?", b.num, b.mes, b.pid);
    const nueva = !p || p.llamadas >= LLAMADAS_POR_PREGUNTA;
    if (nueva) {
      if (!b.sinLimite && usadas >= b.limite) {
        return { ok: false, status: 402, tipo: "cupo", restantes: 0,
                 mensaje: `Ya usaste tus ${b.limite} preguntas de este mes. Sube de plan o espera al próximo mes.` };
      }
      const d = this.uno("SELECT preguntas FROM dia WHERE num = ? AND dia = ?", b.num, b.dia);
      if (!b.sinLimite && d && d.preguntas >= b.porDia) {
        return { ok: false, status: 402, tipo: "dia",
                 mensaje: `Llegaste al máximo de ${b.porDia} preguntas por hoy. Mañana sigues.` };
      }
      this.sql.exec("INSERT OR REPLACE INTO preguntas (num, mes, pid, llamadas) VALUES (?, ?, ?, 1)", b.num, b.mes, b.pid);
      this.sql.exec("INSERT INTO dia (num, dia, preguntas) VALUES (?, ?, 1) ON CONFLICT (num, dia) DO UPDATE SET preguntas = preguntas + 1", b.num, b.dia);
      this.sql.exec("INSERT INTO uso (num, mes, preguntas, llamadas) VALUES (?, ?, 1, 1) ON CONFLICT (num, mes) DO UPDATE SET preguntas = preguntas + 1, llamadas = llamadas + 1", b.num, b.mes);
      usadas += 1;
      if (Math.random() < 0.01) this.limpiar(b);
    } else {
      this.sql.exec("UPDATE preguntas SET llamadas = llamadas + 1 WHERE num = ? AND mes = ? AND pid = ?", b.num, b.mes, b.pid);
      this.sql.exec("UPDATE uso SET llamadas = llamadas + 1 WHERE num = ? AND mes = ?", b.num, b.mes);
    }
    return { ok: true, usadas, restantes: b.sinLimite ? null : Math.max(0, b.limite - usadas) };
  }

  gasto(b) {
    this.sql.exec("INSERT INTO uso (num, mes, tin, tout, centavos) VALUES (?, ?, ?, ?, ?) ON CONFLICT (num, mes) DO UPDATE SET tin = tin + excluded.tin, tout = tout + excluded.tout, centavos = centavos + excluded.centavos",
                  b.num, b.mes, b.tin, b.tout, b.centavos);
    return { ok: true };
  }

  limpiar(b) {
    this.sql.exec("DELETE FROM preguntas WHERE mes < ?", b.mes);
    this.sql.exec("DELETE FROM dia WHERE dia < ?", b.mes + "-01");
  }

  admin(b) {
    const filas = this.sql.exec("SELECT num, preguntas, llamadas, tin, tout, centavos FROM uso WHERE mes = ? ORDER BY num", b.mes).toArray();
    const compus = {};
    for (const e of this.sql.exec("SELECT num, COUNT(*) AS n FROM equipos GROUP BY num").toArray()) compus[e.num] = e.n;
    const dolares = filas.reduce((s, f) => s + f.centavos, 0) / 100;
    return { ok: true, mes: b.mes, gasto_dolares: Math.round(dolares * 100) / 100,
             clientes: filas.map((f) => ({ ...f, dolares: Math.round(f.centavos) / 100, compus: compus[f.num] || 0 })) };
  }
}
