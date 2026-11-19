// Pruebas del servidor sin Cloudflare: node --experimental-sqlite servidor/prueba.mjs
// (Gemini y la pagina son de mentiras; el Durable Object corre sobre node:sqlite)
import { DatabaseSync } from "node:sqlite";
import { webcrypto } from "node:crypto";
import worker, { Cuentas, normalizar, rapida } from "./worker.js";

let reloj = Date.parse("2026-11-20T18:00:00Z");
Date.now = () => reloj;

function sqlFalso() {
  const db = new DatabaseSync(":memory:");
  return {
    exec(q, ...v) {
      const st = db.prepare(q);
      const filas = /^\s*select/i.test(q) ? st.all(...v) : (st.run(...v), []);
      return { toArray: () => filas.map((f) => ({ ...f })) };
    },
  };
}

const cuaderno = new Cuentas({ storage: { sql: sqlFalso() } }, {});
const pendientes = [];
const ctx = { waitUntil: (p) => pendientes.push(p) };

// codigos de prueba (no son de clientes)
const C = { pro: "NL-TEST-PRO0-0001", bas: "NL-TEST-BAS0-0002", pre: "NL-TEST-PRE0-0003", ven: "NL-TEST-VEN0-0004",
            nue: "NL-TEST-NUE0-0005", blo: "NL-TEST-BL00-0006", due: "NL-TEST-DUE0-0007" };
const NUM = { pro: 901, bas: 902, pre: 903, ven: 904, nue: 905, blo: 906, due: 907 };
const prueba = {};
for (const k of Object.keys(C)) prueba[await rapida(normalizar(C[k]))] = [NUM[k], `huella${NUM[k]}`];

let lista = {
  vencen: { 901: "2026-12-31", 902: "2026-12-31", 903: "2026-12-31", 904: "2026-11-01", 906: "2026-12-31", 907: "2099-12-31" },
  planes: { 902: "basico", 903: "premium", 907: "premium" },
  bloqueadas: ["huella906"],
  duenos: [907],
  limites: { pro: 5 },
};
let geminiPedidos = [];
let geminiResp = () => new Response(JSON.stringify({ candidates: [{ content: { parts: [{ text: "ok" }] } }],
                                                       usageMetadata: { promptTokenCount: 4000, candidatesTokenCount: 300, thoughtsTokenCount: 100 } }), { status: 200 });

const fetchReal = globalThis.fetch;
globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  if (url.startsWith("https://lista.prueba/")) return new Response(JSON.stringify(lista));
  if (url.startsWith("https://gemini.prueba/")) {
    geminiPedidos.push({ url, key: init.headers["x-goog-api-key"], body: init.body });
    return geminiResp();
  }
  return fetchReal(url, init);
};

const env = {
  GEMINI_KEY: "CLAVE-SECRETA-DEL-DUENO",
  GEMINI_URL: "https://gemini.prueba",
  LISTA_URL: "https://lista.prueba/licencias.json",
  HUELLAS_PRUEBA: JSON.stringify(prueba),
  CUENTAS: { idFromName: () => "todas", get: () => ({ fetch: (u, i) => cuaderno.fetch(new Request(u, i)) }) },
};

async function pedir(ruta, { codigo, equipo = "compu-A", pid = "p1", modelo = "gemini-flash-latest", metodo } = {}) {
  const h = { "x-nl-codigo": codigo || "", "x-nl-equipo": equipo, "x-nl-pregunta": pid };
  const esIA = ruta === "ia";
  const url = esIA ? `https://srv/v1beta/models/${modelo}:generateContent` : `https://srv${ruta}`;
  const r = await worker.fetch(new Request(url, { method: metodo || (esIA ? "POST" : "GET"), headers: h,
                                                   body: esIA && !metodo ? JSON.stringify({ contents: [] }) : undefined }), env, ctx);
  await Promise.all(pendientes.splice(0));
  const t = await r.text();
  let j = null;
  try { j = JSON.parse(t); } catch {}
  return { status: r.status, j, t, h: r.headers };
}

let fallas = 0;
function ver(nombre, cond, extra = "") {
  console.log(`${cond ? "ok   " : "FALLA"} ${nombre}${cond ? "" : "  " + extra}`);
  if (!cond) fallas++;
}
const avanzar = (ms) => { reloj += ms; };

// --- codigos
let r = await pedir("/estado", { codigo: "NL-XXXX-XXXX-XXXX" });
ver("codigo falso -> 401", r.status === 401 && r.j.error.tipo === "codigo", r.t);
r = await pedir("/estado", { codigo: "" });
ver("sin codigo -> 401", r.status === 401);
r = await pedir("/estado", { codigo: C.pro.toLowerCase().replace(/0/g, "o") });
ver("codigo con minusculas y O en vez de 0 sirve", r.status === 200 && r.j.plan === "pro" && r.j.limite === 5, r.t);
r = await pedir("/estado", { codigo: C.ven });
ver("vencido -> 401 vencido", r.status === 401 && r.j.error.tipo === "vencido", r.t);
r = await pedir("/estado", { codigo: C.nue });
ver("sin activar -> 401", r.status === 401 && r.j.error.tipo === "sin_activar", r.t);
r = await pedir("/estado", { codigo: C.blo });
ver("bloqueado -> 401", r.status === 401 && r.j.error.tipo === "bloqueado", r.t);
r = await pedir("ia", { codigo: C.ven });
ver("vencido no pregunta a la IA", r.status === 401 && geminiPedidos.length === 0, r.t);

// --- preguntas
r = await pedir("ia", { codigo: C.pro, pid: "a" });
ver("pregunta pasa a Gemini con la clave del dueno", r.status === 200 && geminiPedidos.length === 1 &&
    geminiPedidos[0].key === "CLAVE-SECRETA-DEL-DUENO" && geminiPedidos[0].url.includes("gemini-flash-latest"), r.t);
ver("regresa la respuesta de Gemini y cuantas quedan", r.j.candidates && r.h.get("x-nl-restantes") === "4", r.h.get("x-nl-restantes"));
ver("la respuesta no trae la clave", !r.t.includes("CLAVE-SECRETA"));
await pedir("ia", { codigo: C.pro, pid: "a" });
await pedir("ia", { codigo: C.pro, pid: "a" });
r = await pedir("/estado", { codigo: C.pro });
ver("3 llamadas de la misma pregunta cuentan 1", r.j.usadas === 1, r.t);
for (const p of ["b", "c", "d", "e"]) r = await pedir("ia", { codigo: C.pro, pid: p });
ver("5 preguntas: le quedan 0", r.status === 200 && r.h.get("x-nl-restantes") === "0", r.t);
r = await pedir("ia", { codigo: C.pro, pid: "f" });
ver("la 6 (limite 5) -> 402 cupo", r.status === 402 && r.j.error.tipo === "cupo" && /5 preguntas/.test(r.j.error.message), r.t);
r = await pedir("ia", { codigo: C.pro, pid: "e" });
ver("la misma pregunta que ya iba si termina", r.status === 200, r.t);
for (let i = 0; i < 12; i++) await pedir("ia", { codigo: C.pro, pid: "e" });
r = await pedir("ia", { codigo: C.pro, pid: "e" });
ver("repetir el mismo id para siempre no burla el limite", r.status === 402, r.t);

// --- modelos por plan
geminiPedidos = [];
await pedir("ia", { codigo: C.bas, pid: "x", modelo: "gemini-flash-latest" });
ver("Basico usa el modelo ligero", geminiPedidos[0].url.includes("gemini-flash-lite-latest"), geminiPedidos[0].url);
await pedir("ia", { codigo: C.pre, pid: "x", modelo: "gemini-pro-latest" });
ver("Premium pidiendo Pro usa Flash (Pro es caro)", geminiPedidos[1].url.includes("/gemini-flash-latest"), geminiPedidos[1].url);
await pedir("ia", { codigo: C.due, pid: "x", modelo: "gemini-pro-latest" });
ver("el dueno si puede Pro", geminiPedidos[2].url.includes("gemini-pro-latest"), geminiPedidos[2].url);
await pedir("ia", { codigo: C.pre, pid: "y", modelo: "gemini-flash-lite-latest" });
ver("ligero se respeta", geminiPedidos[3].url.includes("gemini-flash-lite-latest"));

// --- compus
r = await pedir("/estado", { codigo: C.bas, equipo: "compu-B" });
ver("Basico en una 2a compu -> 403", r.status === 403 && r.j.error.tipo === "equipo", r.t);
r = await pedir("/estado", { codigo: C.pre, equipo: "compu-B" });
ver("Premium deja 2 compus", r.status === 200, r.t);
r = await pedir("/estado", { codigo: C.pre, equipo: "compu-C" });
ver("Premium en una 3a -> 403", r.status === 403, r.t);
r = await pedir("/estado", { codigo: C.due, equipo: "compu-Z" });
ver("el dueno en cualquier compu", r.status === 200 && r.j.limite === null, r.t);
r = await pedir("ia", { codigo: C.bas, equipo: "" });
ver("sin id de compu (app vieja) -> pide actualizar", r.status === 400 && r.j.error.tipo === "equipo", r.t);
avanzar(73 * 3600 * 1000);
r = await pedir("/estado", { codigo: C.bas, equipo: "compu-B" });
ver("tras 3 dias sin usar la vieja, la compu nueva entra", r.status === 200, r.t);
r = await pedir("/estado", { codigo: C.bas, equipo: "compu-A" });
ver("y la vieja ya no", r.status === 403, r.t);
lista = { ...lista, reiniciar_equipos: { 902: "2026-11-23T10" } };
avanzar(61 * 1000);
r = await pedir("/estado", { codigo: C.bas, equipo: "compu-A" });
ver("reiniciar_equipos libera el codigo", r.status === 200, r.t);
r = await pedir("/estado", { codigo: C.bas, equipo: "compu-B" });
ver("(y solo una vez: luego vuelve el limite)", r.status === 403, r.t);

// --- limite por dia
lista = { ...lista, por_dia: { premium: 2 } };
avanzar(61 * 1000);
await pedir("ia", { codigo: C.pre, pid: "d1" });
r = await pedir("ia", { codigo: C.pre, pid: "d2" });
ver("limite del dia: la 2 pasa", r.status === 200, r.t);
r = await pedir("ia", { codigo: C.pre, pid: "d3" });
ver("limite del dia: la 3 -> 402 dia", r.status === 402 && r.j.error.tipo === "dia", r.t);
avanzar(24 * 3600 * 1000);
r = await pedir("ia", { codigo: C.pre, pid: "d4" });
ver("al otro dia sigue", r.status === 200, r.t);

// --- errores de Gemini
geminiResp = () => new Response(JSON.stringify({ error: { code: 400, message: "API key not valid. Please pass a valid API key.", status: "INVALID_ARGUMENT" } }), { status: 400 });
r = await pedir("ia", { codigo: C.due, pid: "g1" });
ver("clave del dueno mala -> 502 sin decir nada de la clave", r.status === 502 && !/API key not valid/.test(r.t), r.t);
geminiResp = () => new Response(JSON.stringify({ error: { code: 400, message: "Unknown name \"thinkingLevel\"", status: "INVALID_ARGUMENT" } }), { status: 400 });
r = await pedir("ia", { codigo: C.due, pid: "g2" });
ver("400 de variante pasa tal cual (la app prueba otra)", r.status === 400 && /thinkingLevel/.test(r.t), r.t);
geminiResp = () => new Response("{}", { status: 429 });
r = await pedir("ia", { codigo: C.due, pid: "g3" });
ver("429 de Gemini -> 429 limite", r.status === 429 && r.j.error.tipo === "limite", r.t);
delete env.GEMINI_KEY;
r = await pedir("ia", { codigo: C.due, pid: "g4" });
ver("sin GEMINI_KEY -> 503 claro", r.status === 503, r.t);
env.GEMINI_KEY = "CLAVE-SECRETA-DEL-DUENO";

// --- dueno
r = await pedir("/admin", { codigo: C.pro });
ver("admin solo para el dueno", r.status === 403, r.t);
r = await pedir("/admin", { codigo: C.due });
const pro = (r.j.clientes || []).find((c) => c.num === 901);
ver("admin muestra preguntas y gasto", r.status === 200 && pro && pro.preguntas === 5 && pro.tin > 0 && r.j.gasto_dolares > 0, r.t);
r = await pedir("/salud");
ver("salud", r.status === 200 && r.j.ia === true && !r.t.includes("CLAVE"));
r = await pedir("ia", { codigo: C.pro, metodo: "GET" });
ver("GET a la IA -> 404", r.status === 404);

console.log(fallas ? `${fallas} fallas` : "0 fallas");
process.exit(fallas ? 1 : 0);
