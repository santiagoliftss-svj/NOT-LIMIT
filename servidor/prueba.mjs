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
let otrosPedidos = [];
let geminiResp = () => new Response(JSON.stringify({ candidates: [{ content: { parts: [{ text: "ok" }] } }],
                                                       usageMetadata: { promptTokenCount: 4000, candidatesTokenCount: 300, thoughtsTokenCount: 100 } }), { status: 200 });

const fetchReal = globalThis.fetch;
globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  if (url.startsWith("https://lista.prueba/")) return new Response(JSON.stringify(lista));
  if (url.startsWith("https://claude.prueba/") || url.startsWith("https://openai.prueba/")) {
    otrosPedidos.push({ url, h: init.headers, body: JSON.parse(init.body) });
    if (url.includes("claude")) return new Response(JSON.stringify({ content: [{ type: "text", text: "hola" }], usage: { input_tokens: 3000, output_tokens: 200 } }));
    return new Response(JSON.stringify({ choices: [{ message: { content: "hola" } }], usage: { prompt_tokens: 3000, completion_tokens: 200 } }));
  }
  if (url.startsWith("https://gemini.prueba/")) {
    geminiPedidos.push({ url, key: init.headers["x-goog-api-key"], body: init.body });
    return geminiResp();
  }
  return fetchReal(url, init);
};

const env = {
  GEMINI_KEY: "CLAVE-SECRETA-DEL-DUENO",
  GEMINI_URL: "https://gemini.prueba",
  CLAUDE_KEY: "sk-ant-SECRETA-CLAUDE",
  CLAUDE_URL: "https://claude.prueba",
  OPENAI_URL: "https://openai.prueba",
  LISTA_URL: "https://lista.prueba/licencias.json",
  HUELLAS_PRUEBA: JSON.stringify(prueba),
  CUENTAS: { idFromName: () => "todas", get: () => ({ fetch: (u, i) => cuaderno.fetch(new Request(u, i)) }) },
};

async function pedir(ruta, { codigo, equipo = "compu-A", pid = "p1", modelo = "gemini-flash-latest", metodo, peso } = {}) {
  const h = { "x-nl-codigo": codigo || "", "x-nl-equipo": equipo, "x-nl-pregunta": pid };
  if (peso) h["x-nl-peso"] = String(peso);
  const esIA = ruta === "ia";
  let url = `https://srv${ruta}`, cuerpo;
  if (esIA && modelo.startsWith("claude")) { url = "https://srv/v1/messages"; cuerpo = { model: modelo, messages: [] }; }
  else if (esIA && modelo.startsWith("gpt")) { url = "https://srv/v1/chat/completions"; cuerpo = { model: modelo, messages: [] }; }
  else if (esIA) { url = `https://srv/v1beta/models/${modelo}:generateContent`; cuerpo = { contents: [] }; }
  const r = await worker.fetch(new Request(url, { method: metodo || (esIA ? "POST" : "GET"), headers: h,
                                                   body: esIA && !metodo ? JSON.stringify(cuerpo) : undefined }), env, ctx);
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

// --- IAs por plan
geminiPedidos = [];
r = await pedir("ia", { codigo: C.bas, pid: "x", modelo: "gemini-flash-latest" });
ver("Basico pidiendo Gemini Flash -> 403 es del Pro", r.status === 403 && r.j.error.tipo === "plan" && /plan Pro/.test(r.j.error.message) && geminiPedidos.length === 0, r.t);
r = await pedir("ia", { codigo: C.bas, pid: "x", modelo: "gemini-flash-lite-latest" });
ver("Basico con Gemini Flash Lite si", r.status === 200 && geminiPedidos[0].url.includes("gemini-flash-lite-latest"), r.t);
r = await pedir("ia", { codigo: C.bas, pid: "x2", modelo: "claude-haiku-5-5" });
ver("Basico pidiendo Claude -> 403", r.status === 403, r.t);
r = await pedir("ia", { codigo: C.pre, pid: "c1", modelo: "claude-opus-5-5" });
ver("Premium con Claude Opus va a Claude con la clave del dueno", r.status === 200 && otrosPedidos.length === 1 &&
    otrosPedidos[0].url === "https://claude.prueba/v1/messages" && otrosPedidos[0].h["x-api-key"] === "sk-ant-SECRETA-CLAUDE" &&
    otrosPedidos[0].h["anthropic-version"] && r.j.content[0].text === "hola", r.t);
r = await pedir("/estado", { codigo: C.pre });
ver("Opus cuenta por 5", r.j.usadas === 5, r.t);
r = await pedir("ia", { codigo: C.pre, pid: "c1", modelo: "claude-haiku-5-5" });
r = await pedir("/estado", { codigo: C.pre });
ver("la misma pregunta con la ligera no suma", r.j.usadas === 5, r.t);
await pedir("ia", { codigo: C.pre, pid: "c2", modelo: "claude-haiku-5-5", peso: 2 });
await pedir("ia", { codigo: C.pre, pid: "c2", modelo: "claude-sonnet-5-5" });
r = await pedir("/estado", { codigo: C.pre });
ver("ubicar con la ligera + contestar con Sonnet cuenta 2 (no 3)", r.j.usadas === 7, r.t);
await pedir("ia", { codigo: C.pre, pid: "c3", modelo: "gemini-flash-lite-latest", peso: 1 });
await pedir("ia", { codigo: C.pre, pid: "c3", modelo: "claude-opus-5-5" });
r = await pedir("/estado", { codigo: C.pre });
ver("si la app no avisa el peso, Opus igual cobra su 5", r.j.usadas === 12, r.t);
r = await pedir("ia", { codigo: C.pro, pid: "o1", modelo: "claude-opus-5-5" });
ver("Pro pidiendo Opus -> 403 es del Premium", r.status === 403 && /plan Premium/.test(r.j.error.message), r.t);
r = await pedir("ia", { codigo: C.pre, pid: "g1", modelo: "gpt-6-luna" });
ver("ChatGPT sin clave del dueno -> 503 'elige otra IA'", r.status === 503 && r.j.error.tipo === "ia" && /ChatGPT/.test(r.j.error.message), r.t);
env.OPENAI_KEY = "sk-SECRETA-OPENAI";
r = await pedir("ia", { codigo: C.pre, pid: "g1", modelo: "gpt-6-luna" });
ver("ChatGPT con clave va a OpenAI con Bearer", r.status === 200 && otrosPedidos.at(-1).url === "https://openai.prueba/v1/chat/completions" &&
    otrosPedidos.at(-1).h.authorization === "Bearer sk-SECRETA-OPENAI", r.t);
r = await pedir("ia", { codigo: C.due, pid: "z", modelo: "gpt-6.1-terra" });
ver("el dueno puede todas", r.status === 200, r.t);
r = await pedir("ia", { codigo: C.pre, pid: "q", modelo: "claude-mythos-9" });
ver("modelo que no existe -> 404", r.status === 404 && r.j.error.tipo === "modelo", r.t);
geminiPedidos = [];

// --- compus
r = await pedir("/estado", { codigo: C.bas, equipo: "compu-B" });
ver("Basico en una 2a compu -> 403", r.status === 403 && r.j.error.tipo === "equipo", r.t);
r = await pedir("/estado", { codigo: C.pre, equipo: "compu-B" });
ver("Premium deja 2 compus", r.status === 200, r.t);
r = await pedir("/estado", { codigo: C.pre, equipo: "compu-C" });
ver("Premium en una 3a -> 403", r.status === 403, r.t);
r = await pedir("/estado", { codigo: C.due, equipo: "compu-Z" });
ver("el dueno en cualquier compu", r.status === 200 && r.j.limite === null, r.t);
r = await pedir("ia", { codigo: C.bas, equipo: "", modelo: "gemini-flash-lite-latest" });
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

// --- una cara cuando ya casi no quedan
r = await pedir("/estado", { codigo: C.pre });
lista = { ...lista, limites: { pro: 5, premium: r.j.usadas + 2 }, por_dia: {} };
avanzar(61 * 1000);
r = await pedir("ia", { codigo: C.pre, pid: "w1", modelo: "claude-opus-5-5" });
ver("le quedan 2 y Opus cuenta 5 -> 402 con explicacion", r.status === 402 && /cuenta por 5/.test(r.j.error.message), r.t);
r = await pedir("ia", { codigo: C.pre, pid: "w2", modelo: "claude-haiku-5-5" });
ver("con una ligera si pasa", r.status === 200, r.t);

// --- errores de Gemini
geminiResp = () => new Response(JSON.stringify({ error: { code: 400, message: "API key not valid. Please pass a valid API key.", status: "INVALID_ARGUMENT" } }), { status: 400 });
r = await pedir("ia", { codigo: C.due, pid: "g1" });
ver("clave del dueno mala -> 503 'elige otra' sin decir nada de la clave", r.status === 503 && !/API key not valid/.test(r.t), r.t);
geminiResp = () => new Response(JSON.stringify({ type: "error", error: { type: "invalid_request_error", message: "Your credit balance is too low to access the API." } }), { status: 400 });
r = await pedir("ia", { codigo: C.due, pid: "g1b" });
ver("sin saldo del dueno -> 503 sin decir del saldo", r.status === 503 && !/credit/.test(r.t), r.t);
geminiResp = () => new Response(JSON.stringify({ error: { code: 400, message: "Unknown name \"thinkingLevel\"", status: "INVALID_ARGUMENT" } }), { status: 400 });
r = await pedir("ia", { codigo: C.due, pid: "g2" });
ver("400 de variante pasa tal cual (la app prueba otra)", r.status === 400 && /thinkingLevel/.test(r.t), r.t);
geminiResp = () => new Response("{}", { status: 429 });
r = await pedir("ia", { codigo: C.due, pid: "g3" });
ver("429 de Gemini -> 429 limite", r.status === 429 && r.j.error.tipo === "limite", r.t);
delete env.GEMINI_KEY;
r = await pedir("ia", { codigo: C.due, pid: "g4" });
ver("sin GEMINI_KEY -> 503 claro", r.status === 503 && /Gemini/.test(r.t), r.t);
env.GEMINI_KEY = "CLAVE-SECRETA-DEL-DUENO";

// --- dueno
r = await pedir("/admin", { codigo: C.pro });
ver("admin solo para el dueno", r.status === 403, r.t);
r = await pedir("/admin", { codigo: C.due });
const pro = (r.j.clientes || []).find((c) => c.num === 901);
ver("admin muestra preguntas y gasto", r.status === 200 && pro && pro.preguntas === 5 && pro.tin > 0 && r.j.gasto_dolares > 0, r.t);
r = await pedir("/salud");
ver("salud dice que IAs hay (sin claves)", r.status === 200 && r.j.ias.gemini && r.j.ias.claude && !r.t.includes("SECRETA"), r.t);
r = await pedir("ia", { codigo: C.pro, metodo: "GET" });
ver("GET a la IA -> 404", r.status === 404);

// --- limite propio de un codigo (los que pagaron antes del cambio de precios lo conservan)
lista = { ...lista, limite_codigo: { 902: 777 } };
avanzar(61 * 1000);
r = await pedir("/estado", { codigo: C.bas });
ver("limite_codigo le gana al del plan", r.status === 200 && r.j.limite === 777, r.t);
lista = { ...lista, limite_codigo: {}, limites: {} };
avanzar(61 * 1000);
r = await pedir("/estado", { codigo: C.bas });
ver("sin limite_codigo: el del plan (Basico 300)", r.status === 200 && r.j.limite === 300, r.t);

console.log(fallas ? `${fallas} fallas` : "0 fallas");
process.exit(fallas ? 1 : 0);
