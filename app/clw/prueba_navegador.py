"""Pruebas de punta a punta en un NAVEGADOR de verdad (Chrome o Edge en Windows, Chrome en Mac).

Las preguntas que fallaban en ALEKS, en el juego de los amigos, en Kahoot y en los quizzes de Gemini se recrean
como paginas web: casillas angostas que crecen al escribir (y que ignoran el clic rapido, como ALEKS), varias
casillas en una tarjeta, menus "Seleccionar" con opciones de dos renglones, ordenar con flechas, "selecciona todas",
completar, graficas (la herramienta ya elegida, numeros chiquitos, tema oscuro: solo se pican los puntos), ordenar
arrastrando (sin flechas) y arrastrar etiquetas a su lugar.

NO LIMIT las contesta con el mouse y el teclado de verdad. La IA es de mentiras (siempre dice lo correcto): asi se
prueba que cada respuesta quede EN SU LUGAR. La pagina le dice a la prueba que quedo escrito o marcado.

Corre dentro de la autoprueba (python -m clw --autoprueba) en GitHub, en Windows y en Mac.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import logging
import unicodedata
from http.server import BaseHTTPRequestHandler

from .servidor_local import abrir as _servidor

log = logging.getLogger("clw.navegador")

COMUN = """
<style>
  body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#fff;color:#222}
  #marca{position:fixed;left:2px;top:2px;width:8px;height:8px;background:#ff00ff;z-index:99}
  .q{position:absolute;left:40px;top:30px;width:860px}
</style>
<div id="marca"></div>
<script>
  const NOMBRE = document.body.dataset.prueba;
  function mandar(ruta, datos){ fetch(ruta,{method:'POST',body:JSON.stringify(Object.assign({prueba:NOMBRE},datos))}).catch(()=>{}); }
  setInterval(()=>{ mandar('/valores', {valores: window.valores ? window.valores() : {}}); }, 300);
  setInterval(()=>{
    const r = {};
    document.querySelectorAll('[data-r]').forEach(e=>{ const b=e.getBoundingClientRect(); r[e.dataset.r]=[b.left,b.top,b.width,b.height]; });
    mandar('/layout', {r: r, dpr: devicePixelRatio, foco: (document.activeElement && document.activeElement.dataset.k) || ''});
  }, 400);
  setInterval(async()=>{ try{ const e = await (await fetch('/estado')).json();
    if (e.prueba && e.prueba !== NOMBRE) location.href = '/p/' + e.prueba; }catch(x){} }, 250);
</script>
"""

PAGINAS = {}

PAGINAS["inicio"] = """<body data-prueba="inicio"><div class="q"><h2>NO LIMIT: pruebas en el navegador</h2></div>"""

# ---- ALEKS: casillas angostas (de una letra) que crecen al escribir, en medio de un renglon de matematicas.
# Como en ALEKS, un clic RAPIDO en una casilla que no tiene el cursor no entra (el mouse tiene que llegar antes):
# asi se prueba que NO LIMIT se de cuenta y vuelva a dar el clic con calma, en vez de escribir donde estaba el cursor.
PAGINAS["aleks"] = """<body data-prueba="aleks">
<style>
 .t{font-size:15px;line-height:1.5}
 .resp{border:1px solid #333;padding:22px 18px;margin-top:20px;width:360px;font:italic 19px 'Times New Roman',serif}
 .caja{display:inline-block;min-width:9px;height:21px;border:1px solid #9aa8f0;padding:0 2px;vertical-align:middle;
       outline:none;font:normal 17px 'Times New Roman',serif;line-height:21px;white-space:nowrap}
 .caja:focus{border-color:#2348d6;box-shadow:0 0 0 1px #2348d6}
</style>
<div class="q" data-r="pregunta">
 <p class="t">Consideremos el triángulo ABC como el que se muestra adelante. Supongamos que B = 84°, C = 57°,
 y a = 26. Resolver el triángulo.</p>
 <p class="t">Redondear sus respuestas a la décima más cercana.</p>
 <div class="resp">A = <span class="caja" contenteditable="true" data-k="A" data-r="A"></span>°,&nbsp;
  b = <span class="caja" contenteditable="true" data-k="b" data-r="b"></span>,&nbsp;
  c = <span class="caja" contenteditable="true" data-k="c" data-r="c"></span></div>
</div>
<script>
 let movio = -1e9, ignorados = 0;
 document.addEventListener('mousemove', e=>{ movio = e.timeStamp; }, true);
 document.querySelectorAll('.caja').forEach(c=>{
   c.addEventListener('mousedown', e=>{
     if (document.activeElement !== c && e.timeStamp - movio < 90) { e.preventDefault(); ignorados++; }   // clic "necio"
   });
 });
 window.valores = ()=>{ const v={}; document.querySelectorAll('.caja').forEach(c=>v[c.dataset.k]=c.innerText.trim());
                        v._ignorados = ignorados; return v; };
</script>"""

# ---- juego de los amigos: varias cajas redondeadas en una tarjeta de colores, una por renglon.
PAGINAS["juego"] = """<body data-prueba="juego">
<style>
 .tarjeta{background:linear-gradient(135deg,#5b2bd6,#9b3fd8);color:#fff;border-radius:18px;padding:22px 34px;width:520px}
 .fila{display:flex;align-items:center;margin:12px 0;font-size:22px;font-weight:bold}
 .fila span{width:150px}
 .fila input{width:110px;height:36px;border-radius:10px;border:2px solid #ffd84d;background:#fff;color:#222;
             font-size:20px;padding:0 10px;outline:none}
</style>
<div class="q" data-r="pregunta"><div class="tarjeta">
 <div style="font-size:24px;margin-bottom:10px">Completa la tabla</div>
 <div class="fila"><span>2 + 2 =</span><input data-k="1" data-r="i1"></div>
 <div class="fila"><span>5 × 3 =</span><input data-k="2" data-r="i2"></div>
 <div class="fila"><span>9 − 4 =</span><input data-k="3" data-r="i3"></div>
 <div class="fila"><span>10 ÷ 2 =</span><input data-k="4" data-r="i4"></div>
</div></div>
<script>window.valores = ()=>{ const v={}; document.querySelectorAll('input').forEach(i=>v[i.dataset.k]=i.value.trim()); return v; };</script>"""

# ---- tipo Kahoot (escribir la respuesta): fondo de color, una sola caja grande con texto de ayuda.
PAGINAS["kahoot"] = """<body data-prueba="kahoot" style="background:#46178f">
<style>
 .pq{background:#fff;border-radius:6px;padding:18px;font-size:26px;font-weight:bold;text-align:center;width:820px}
 .resp{margin-top:150px;display:flex;justify-content:center;width:860px}
 .resp input{width:520px;height:58px;border:none;border-radius:6px;font-size:24px;padding:0 18px;outline:none;
             box-shadow:0 4px 0 #0003}
</style>
<div class="q" data-r="pregunta">
 <div class="pq">¿Cuánto es 7 × 8?</div>
 <div class="resp"><input placeholder="Escribe tu respuesta" data-r="campo"></div>
</div>
<script>window.valores = ()=>({texto: document.querySelector('input').value.trim()});</script>"""

# ---- quiz de Gemini: tarjetas con boton "Seleccionar"; las opciones salen abajo y ocupan dos renglones.
PAGINAS["menus"] = """<body data-prueba="menus">
<style>
 .tarjetas{display:flex;gap:18px;margin-top:16px;align-items:flex-start}
 .tarjeta{border:1.5px solid #ccc;border-radius:12px;padding:16px;width:240px;font-size:15px;background:#fafafa}
 .tarjeta h3{margin:4px 0 14px;font-family:Georgia,serif}
 .sel{border:1px solid #bbb;border-radius:8px;padding:10px 12px;background:#fff;cursor:pointer;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .lista{display:none;border:1px solid #ddd;border-radius:10px;background:#fff;margin-top:6px;box-shadow:0 4px 14px #0002}
 .lista div{padding:9px 12px;border-bottom:1px solid #eee;cursor:pointer;line-height:1.35}
 .abierta .lista{display:block}
</style>
<div class="q" data-r="pregunta">
 <div style="font-size:19px;font-family:Georgia,serif">Haz clic en <b>Seleccionar</b> debajo de cada civilización para elegir su aporte principal:</div>
 <div class="tarjetas" id="t"></div>
</div>
<script>
 const OPS = ["Democracia ateniense y filosofía clásica","Construcción de acueductos y derecho romano",
              "Invención de la imprenta de tipos móviles","Sistema de caminos Qhapaq Ñan en los Andes"];
 const elegido = {};
 ["Antigua Grecia","Imperio Inca","Antigua Roma"].forEach((n,i)=>{
   const t = document.createElement('div'); t.className='tarjeta';
   t.innerHTML = '<div style="font-size:12px;color:#777">TARJETA '+(i+1)+'</div><h3>'+n+'</h3><div class="sel">Seleccionar</div><div class="lista"></div>';
   const sel = t.querySelector('.sel'), lista = t.querySelector('.lista');
   OPS.forEach(o=>{ const d=document.createElement('div'); d.textContent=o;
     d.onclick=()=>{ elegido[n]=o; sel.textContent=o; t.classList.remove('abierta'); }; lista.appendChild(d); });
   sel.onclick = ()=>{ document.querySelectorAll('.tarjeta').forEach(x=>{ if(x!==t) x.classList.remove('abierta'); }); t.classList.toggle('abierta'); };
   document.getElementById('t').appendChild(t);
 });
 window.valores = ()=>Object.assign({}, elegido);
</script>"""

# ---- ordenar con flechas (como el quiz de Gemini): se pican las flechas, NO se arrastra.
PAGINAS["flechas"] = """<body data-prueba="flechas">
<style>
 .fila{display:flex;align-items:center;border:1.5px solid #ddd;border-radius:12px;padding:10px 16px;margin:12px 0;
       width:760px;font-size:19px;background:#fbfbf9}
 .fila .n{width:26px;height:26px;border:1px solid #bbb;border-radius:6px;text-align:center;margin-right:16px;font-size:14px;line-height:26px}
 .fila .t{flex:1}
 .fila button{width:38px;height:38px;margin-left:8px;border:1px solid #ccc;border-radius:8px;background:#fff;font-size:18px}
 .fila button:disabled{opacity:.3}
</style>
<div class="q" data-r="pregunta">
 <div style="font-size:20px;font-family:Georgia,serif;margin-bottom:6px">Ordena los hitos de forma cronológica, desde el más antiguo (1) hasta el más reciente (4):</div>
 <div id="l"></div>
</div>
<script>
 let items = ["Caída del Imperio romano de Occidente (476 d. C.)","Invención de la escritura cuneiforme (3200 a. C.)",
              "Llegada de Cristóbal Colón a América (1492)","Inicio de la Revolución Francesa (1789)"];
 function pintar(){
   const l = document.getElementById('l'); l.innerHTML='';
   items.forEach((t,i)=>{
     const f=document.createElement('div'); f.className='fila';
     f.innerHTML='<div class="n">'+(i+1)+'</div><div class="t">'+t+'</div><button data-r="sube'+i+'">&#8593;</button><button>&#8595;</button>';
     const [up,down]=f.querySelectorAll('button');
     up.disabled = i===0; down.disabled = i===items.length-1;
     up.onclick=()=>{ [items[i-1],items[i]]=[items[i],items[i-1]]; pintar(); };
     down.onclick=()=>{ [items[i+1],items[i]]=[items[i],items[i+1]]; pintar(); };
     l.appendChild(f);
   });
 }
 pintar();
 let arrastres = 0;
 document.addEventListener('dragstart', ()=>arrastres++);
 window.valores = ()=>({orden: items.map(t=>t.split(' (')[0]), arrastres});
</script>"""

# ---- selecciona todas (renglones con casilla dibujada, como el quiz de Gemini)
PAGINAS["casillas"] = """<body data-prueba="casillas">
<style>
 .op{display:flex;align-items:center;border:1.5px solid #ddd;border-radius:12px;padding:13px 18px;margin:12px 0;width:760px;
     font-size:19px;cursor:pointer;background:#fff}
 .op .c{width:18px;height:18px;border:2px solid #666;border-radius:4px;margin-right:16px}
 .op.si{border-color:#2a9d8f;background:#eefaf7}
 .op.si .c{background:#2a9d8f;border-color:#2a9d8f}
</style>
<div class="q" data-r="pregunta">
 <div style="font-size:20px;font-family:Georgia,serif">Selecciona <b>todas</b> las afirmaciones verdaderas sobre la función cuadrática f(x) = x² − 4x + 3:</div>
 <div id="o"></div>
</div>
<script>
 const OPS=["Sus raíces o ceros son x = 1 y x = 3.","Abre hacia abajo porque el coeficiente principal es positivo.",
            "Su vértice se encuentra en x = 2.","Interseca al eje y en el punto (0, 3)."];
 const marc={};
 OPS.forEach((t,i)=>{ const d=document.createElement('div'); d.className='op'; d.innerHTML='<div class="c"></div><div>'+t+'</div>';
   d.onclick=()=>{ marc[i]=!marc[i]; d.classList.toggle('si', marc[i]); }; document.getElementById('o').appendChild(d); });
 window.valores = ()=>({marcadas: OPS.map((t,i)=>marc[i]?i:-1).filter(i=>i>=0)});
</script>"""

# ---- completar un espacio (solo una raya abajo, como un ______) con texto gris de ayuda
PAGINAS["completar"] = """<body data-prueba="completar">
<style>
 .linea{border:none;border-bottom:2px solid #555;font-size:19px;width:300px;padding:6px 4px;outline:none;background:transparent}
 .linea:focus{border-bottom-color:#2a6df4}
</style>
<div class="q" data-r="pregunta" style="font-family:Georgia,serif;font-size:21px;line-height:1.6">
 Hacia mediados del siglo XV, Johannes Gutenberg perfeccionó en Europa un sistema para imprimir libros.
 <div style="font-family:Arial;font-size:17px;margin-top:26px">¿Cómo se llama el sistema de impresión que perfeccionó Gutenberg?</div>
 <input class="linea" placeholder="Tu respuesta" data-r="campo">
</div>
<script>window.valores = ()=>({texto: document.querySelector('input').value.trim()});</script>"""

# ---- grafica: el usuario YA eligio la herramienta de recta; NO LIMIT solo pica los dos puntos.
PAGINAS["grafica"] = """<body data-prueba="grafica">
<div class="q" data-r="pregunta">
 <div style="font-size:18px">Grafica la recta cuya intersección con el eje y es 2 y cuya intersección con el eje x es −1.</div>
 <div style="margin:8px 0;font-size:14px;color:#555">Herramienta: <b>Recta</b></div>
 <canvas id="c" width="560" height="560" data-r="plano"></canvas>
</div>
<script>
 const c=document.getElementById('c'), g=c.getContext('2d'); const U=26, O=280; const pts=[];
 function px(v){return O+v*U} function py(v){return O-v*U}
 function linea(x0,y0,x1,y1){ g.beginPath(); g.moveTo(Math.round(x0)+0.5,Math.round(y0)+0.5); g.lineTo(Math.round(x1)+0.5,Math.round(y1)+0.5); g.stroke(); }
 function pintar(){   // como ALEKS o MyLab: cuadricula gris clara, ejes negros, rayitas y numeros de 2 en 2
   g.fillStyle='#fff'; g.fillRect(0,0,560,560); g.lineWidth=1;
   for(let k=-10;k<=10;k++){ g.strokeStyle='#d5d8e2'; linea(px(k),py(10),px(k),py(-10)); linea(px(-10),py(k),px(10),py(k)); }
   g.strokeStyle='#000'; linea(px(-10),O,px(10),O); linea(O,py(-10),O,py(10));
   g.fillStyle='#000'; g.font='13px Arial';
   for(let k=-10;k<=10;k++){ if(!k) continue; linea(px(k),O-4,px(k),O+4); linea(O-4,py(k),O+4,py(k));
     if(k%2) continue;
     const t=String(k); const w=g.measureText(t).width;
     g.fillText(t, px(k)-w/2, O+18); g.fillText(t, O-8-w, py(k)+5); }
   pts.forEach(p=>{ g.fillStyle='#1a5fd0'; g.beginPath(); g.arc(px(p[0]),py(p[1]),5,0,7); g.fill(); });
   if(pts.length>=2){ g.strokeStyle='#1a5fd0'; g.lineWidth=2; const [a,b]=pts; const m=(b[1]-a[1])/((b[0]-a[0])||1e-9);
     g.beginPath(); g.moveTo(px(-10),py(a[1]+m*(-10-a[0]))); g.lineTo(px(10),py(a[1]+m*(10-a[0]))); g.stroke(); g.lineWidth=1; }
 }
 pintar();
 const crudos = [];
 c.addEventListener('click', e=>{ const b=c.getBoundingClientRect(); const x=(e.clientX-b.left-O)/U, y=(O-(e.clientY-b.top))/U;
   crudos.push([Math.round(x*100)/100, Math.round(y*100)/100]);
   if(pts.length<2){ pts.push([Math.round(x), Math.round(y)]); pintar(); } });
 window.valores = ()=>({puntos: pts, crudos});
</script>"""


# ---- 2.5.1: grafica tipo ALEKS con numeros chiquitos de 1 en 1 y barra de herramientas (Parabola ya elegida).
# NO LIMIT solo pica los dos puntos: ni la herramienta, ni trazar arrastrando.
PAGINAS["grafica_parabola"] = """<body data-prueba="grafica_parabola">
<style>
 .fila{display:flex;gap:16px;align-items:flex-start;margin-top:8px}
 .barra{display:flex;flex-direction:column;gap:8px}
 .barra div{border:1px solid #9aa;border-radius:6px;padding:7px 10px;font-size:14px;background:#f3f4f6;cursor:pointer}
 .barra div.si{background:#dfe9ff;border-color:#2348d6}
</style>
<div class="q" data-r="pregunta">
 <div style="font-size:18px">Grafica la parábola y = (x − 1)² − 4. Primero pica el vértice y luego otro punto de la parábola.</div>
 <div class="fila">
  <div class="barra"><div>Punto</div><div>Recta</div><div class="si">Parábola</div><div>Borrar</div></div>
  <canvas id="c" width="440" height="440" data-r="plano"></canvas>
 </div>
</div>
<script>
 const c=document.getElementById('c'), g=c.getContext('2d'); const U=20, O=220; const pts=[], crudos=[]; let herramienta=0;
 document.querySelectorAll('.barra div').forEach(b=>b.addEventListener('click',()=>herramienta++));
 function px(v){return O+v*U} function py(v){return O-v*U}
 function linea(x0,y0,x1,y1){ g.beginPath(); g.moveTo(Math.round(x0)+0.5,Math.round(y0)+0.5); g.lineTo(Math.round(x1)+0.5,Math.round(y1)+0.5); g.stroke(); }
 function pintar(){   // como ALEKS: cuadricula clara, ejes negros, numeros chiquitos en CADA rayita
   g.fillStyle='#fff'; g.fillRect(0,0,440,440); g.lineWidth=1;
   for(let k=-10;k<=10;k++){ g.strokeStyle='#d5d8e2'; linea(px(k),py(10),px(k),py(-10)); linea(px(-10),py(k),px(10),py(k)); }
   g.strokeStyle='#000'; linea(px(-10),O,px(10),O); linea(O,py(-10),O,py(10));
   g.fillStyle='#333'; g.font='11px Arial';
   for(let k=-10;k<=10;k++){ if(!k) continue; linea(px(k),O-4,px(k),O+4); linea(O-4,py(k),O+4,py(k));
     const t=String(k); const w=g.measureText(t).width; g.fillText(t, px(k)-w/2, O+16); g.fillText(t, O-7-w, py(k)+4); }
   pts.forEach(p=>{ g.fillStyle='#c0392b'; g.beginPath(); g.arc(px(p[0]),py(p[1]),5,0,7); g.fill(); });
   if(pts.length>=2){ const [v,q]=pts; const a=(q[1]-v[1])/(((q[0]-v[0])**2)||1e-9); g.strokeStyle='#c0392b'; g.lineWidth=2; g.beginPath();
     for(let i=0;i<=80;i++){ const x=-10+i/4; const y=a*(x-v[0])**2+v[1]; i?g.lineTo(px(x),py(y)):g.moveTo(px(x),py(y)); } g.stroke(); g.lineWidth=1; }
 }
 pintar();
 let trazos=0; c.addEventListener('mousemove', e=>{ if(e.buttons&1) trazos++; });
 c.addEventListener('click', e=>{ const b=c.getBoundingClientRect(); const x=(e.clientX-b.left-O)/U, y=(O-(e.clientY-b.top))/U;
   crudos.push([Math.round(x*100)/100, Math.round(y*100)/100]);
   if(pts.length<2){ pts.push([Math.round(x), Math.round(y)]); pintar(); } });
 window.valores = ()=>({puntos: pts, crudos, herramienta, trazos});
</script>"""

# ---- 2.5.1: plano con tema oscuro (como Desmos en modo oscuro): solo picar los puntos que pide la instruccion.
PAGINAS["grafica_oscura"] = """<body data-prueba="grafica_oscura" style="background:#121212;color:#eee">
<div class="q" data-r="pregunta">
 <div style="font-size:18px">Plot the points (−3, 4) and (2, −1) in that order.</div>
 <canvas id="c" width="440" height="440" data-r="plano" style="margin-top:10px"></canvas>
</div>
<script>
 const c=document.getElementById('c'), g=c.getContext('2d'); const U=20, O=220; const pts=[], crudos=[];
 function px(v){return O+v*U} function py(v){return O-v*U}
 function linea(x0,y0,x1,y1){ g.beginPath(); g.moveTo(Math.round(x0)+0.5,Math.round(y0)+0.5); g.lineTo(Math.round(x1)+0.5,Math.round(y1)+0.5); g.stroke(); }
 function pintar(){
   g.fillStyle='#1e1e1e'; g.fillRect(0,0,440,440); g.lineWidth=1;
   for(let k=-10;k<=10;k++){ g.strokeStyle='#3a3a3a'; linea(px(k),py(10),px(k),py(-10)); linea(px(-10),py(k),px(10),py(k)); }
   g.strokeStyle='#eee'; linea(px(-10),O,px(10),O); linea(O,py(-10),O,py(10));
   g.fillStyle='#ddd'; g.font='12px Arial';
   for(let k=-10;k<=10;k++){ if(!k) continue; linea(px(k),O-4,px(k),O+4); linea(O-4,py(k),O+4,py(k));
     if(k%2) continue; const t=String(k); const w=g.measureText(t).width; g.fillText(t, px(k)-w/2, O+17); g.fillText(t, O-8-w, py(k)+4); }
   pts.forEach(p=>{ g.fillStyle='#4fc3f7'; g.beginPath(); g.arc(px(p[0]),py(p[1]),5,0,7); g.fill(); });
 }
 pintar();
 c.addEventListener('click', e=>{ const b=c.getBoundingClientRect(); const x=(e.clientX-b.left-O)/U, y=(O-(e.clientY-b.top))/U;
   crudos.push([Math.round(x*100)/100, Math.round(y*100)/100]); pts.push([Math.round(x), Math.round(y)]); pintar(); });
 window.valores = ()=>({puntos: pts, crudos});
</script>"""

# ---- 2.5.1: ordenar ARRASTRANDO (sin flechas), con arrastrar y soltar del navegador (HTML5 draggable).
PAGINAS["ordenar_arrastrar"] = """<body data-prueba="ordenar_arrastrar">
<style>
 .it{display:flex;align-items:center;border:1.5px solid #cfd6e4;border-radius:10px;padding:12px 16px;margin:10px 0;width:520px;
     font-size:19px;background:#f7f9fc;cursor:grab;user-select:none}
 .it .h{color:#b5bccb;margin-right:16px;font-size:13px}
 .it.sobre{border-color:#2a6df4}
</style>
<div class="q" data-r="pregunta">
 <div style="font-size:20px;font-family:Georgia,serif;margin-bottom:8px">Arrastra los planetas para ordenarlos del más cercano al Sol (arriba) al más lejano (abajo):</div>
 <div id="l"></div>
</div>
<script>
 let items=["Marte","Mercurio","Júpiter","Tierra","Venus"]; let arrastrando=null, arrastres=0;
 function pintar(){ const l=document.getElementById('l'); l.innerHTML='';
   items.forEach((t,i)=>{ const d=document.createElement('div'); d.className='it'; d.draggable=true;
     d.innerHTML='<span class="h">&#9679;&#9679;</span><span>'+t+'</span>';
     d.addEventListener('dragstart',e=>{ arrastrando=i; arrastres++; e.dataTransfer.effectAllowed='move'; e.dataTransfer.setData('text/plain',t); });
     d.addEventListener('dragover',e=>{ e.preventDefault(); d.classList.add('sobre'); });
     d.addEventListener('dragleave',()=>d.classList.remove('sobre'));
     d.addEventListener('drop',e=>{ e.preventDefault(); if(arrastrando===null) return;
        const b=d.getBoundingClientRect(); let j=i+(e.clientY>b.top+b.height/2?1:0);
        const [x]=items.splice(arrastrando,1); if(arrastrando<j) j--; items.splice(j,0,x); arrastrando=null; pintar(); });
     d.addEventListener('dragend',()=>{ arrastrando=null; });
     l.appendChild(d); }); }
 pintar();
 window.valores=()=>({orden: items, arrastres});
</script>"""

# ---- 2.5.1: ordenar arrastrando con el mouse (como dnd-kit o las tarjetas de un quiz): la tarjeta sigue al mouse y
# las demas se recorren mientras se arrastra.
PAGINAS["ordenar_puntero"] = """<body data-prueba="ordenar_puntero">
<style>
 .it{border:1.5px solid #d9d4ef;border-radius:10px;padding:12px 16px;margin:10px 0;width:560px;font-size:19px;
     background:#fbfaff;user-select:none;cursor:grab;box-sizing:border-box}
 .it.vuela{position:fixed;z-index:10;box-shadow:0 8px 20px #0003;margin:0;pointer-events:none}
 .hueco{border:1.5px dashed #b9b0e6;border-radius:10px;margin:10px 0;width:560px;box-sizing:border-box}
</style>
<div class="q" data-r="pregunta">
 <div style="font-size:20px;font-family:Georgia,serif;margin-bottom:8px">Ordena los pasos del método científico, del primero (arriba) al último (abajo):</div>
 <div id="l"></div>
</div>
<script>
 let items=["Experimentación","Observación","Conclusión","Hipótesis","Análisis de resultados"]; let drag=null, arrastres=0;
 const l=document.getElementById('l');
 function pintar(){ l.innerHTML=''; items.forEach(t=>{ const d=document.createElement('div'); d.className='it'; d.textContent=t; l.appendChild(d); }); }
 pintar();
 l.addEventListener('mousedown', e=>{ const el=e.target.closest('.it'); if(!el) return; e.preventDefault();
   const b=el.getBoundingClientRect(); drag={el, x0:e.clientX, y0:e.clientY, dx:e.clientX-b.left, dy:e.clientY-b.top, h:b.height, va:false}; });
 document.addEventListener('mousemove', e=>{ if(!drag) return;
   if(!drag.va){ if(Math.hypot(e.clientX-drag.x0, e.clientY-drag.y0)<5) return;
     drag.va=true; arrastres++; const hueco=document.createElement('div'); hueco.className='hueco'; hueco.style.height=drag.h+'px';
     l.insertBefore(hueco, drag.el); drag.hueco=hueco; drag.el.classList.add('vuela'); document.body.appendChild(drag.el); }
   drag.el.style.left=(e.clientX-drag.dx)+'px'; drag.el.style.top=(e.clientY-drag.dy)+'px';
   const otros=[...l.querySelectorAll('.it')]; const antes=otros.find(o=>{ const b=o.getBoundingClientRect(); return e.clientY<b.top+b.height/2; });
   if(antes) l.insertBefore(drag.hueco, antes); else l.appendChild(drag.hueco); });
 document.addEventListener('mouseup', ()=>{ if(!drag) return;
   if(drag.va){ const orden=[...l.children].map(c=>c===drag.hueco?drag.el.textContent:c.textContent); items=orden; drag.el.remove(); pintar(); }
   drag=null; });
 window.valores=()=>({orden: items, arrastres});
</script>"""

# ---- 2.5.1: arrastrar etiquetas a su lugar (como H5P, Wordwall o Educaplay): al soltar una, las del banco se recorren.
PAGINAS["etiquetas"] = """<body data-prueba="etiquetas">
<style>
 .banco{display:flex;gap:14px;margin:16px 0 22px;min-height:48px}
 .et{border:1.5px solid #e0a83a;background:#fff4dc;border-radius:8px;padding:10px 18px;font-size:18px;cursor:grab;user-select:none}
 .et.vuela{position:fixed;z-index:10;box-shadow:0 6px 16px #0003;pointer-events:none}
 .cols{display:flex;gap:18px}
 .col{border:1.5px solid #ccc;border-radius:12px;width:250px;padding:12px;background:#fafafa}
 .col .d{font-size:16px;min-height:44px}
 .zona{margin-top:10px;height:62px;border:2px dashed #aab;border-radius:8px;display:flex;align-items:center;justify-content:center;
       color:#888;font-size:15px}
</style>
<div class="q" data-r="pregunta">
 <div style="font-size:20px;font-family:Georgia,serif">Arrastra cada órgano a la función que le corresponde:</div>
 <div class="banco" id="banco"></div>
 <div class="cols" id="cols"></div>
</div>
<script>
 const ORG=["Riñones","Corazón","Pulmones"];
 const FUN=["Bombea la sangre a todo el cuerpo","Intercambian oxígeno y dióxido de carbono","Filtran la sangre y forman la orina"];
 const puesto={}; let drag=null, arrastres=0;
 function pintar(){
   const banco=document.getElementById('banco'); banco.innerHTML='';
   ORG.filter(o=>!Object.values(puesto).includes(o)).forEach(o=>{ const d=document.createElement('div'); d.className='et'; d.textContent=o; banco.appendChild(d); });
   const cols=document.getElementById('cols'); cols.innerHTML='';
   FUN.forEach(f=>{ const c=document.createElement('div'); c.className='col';
     c.innerHTML='<div class="d">'+f+'</div><div class="zona" data-f="'+f+'">'+(puesto[f]?'<div class="et">'+puesto[f]+'</div>':'Suelta aquí')+'</div>';
     cols.appendChild(c); });
 }
 pintar();
 document.addEventListener('mousedown', e=>{ const el=e.target.closest('#banco .et'); if(!el) return; e.preventDefault();
   const b=el.getBoundingClientRect(); drag={el, x0:e.clientX, y0:e.clientY, dx:e.clientX-b.left, dy:e.clientY-b.top, va:false}; });
 document.addEventListener('mousemove', e=>{ if(!drag) return;
   if(!drag.va){ if(Math.hypot(e.clientX-drag.x0, e.clientY-drag.y0)<4) return; drag.va=true; arrastres++; drag.el.classList.add('vuela'); }
   drag.el.style.left=(e.clientX-drag.dx)+'px'; drag.el.style.top=(e.clientY-drag.dy)+'px'; });
 document.addEventListener('mouseup', e=>{ if(!drag) return;
   if(drag.va){ const z=document.elementsFromPoint(e.clientX,e.clientY).find(x=>x.classList && x.classList.contains('zona'));
     if(z && !puesto[z.dataset.f]) puesto[z.dataset.f]=drag.el.textContent; }
   drag=null; pintar(); });
 window.valores=()=>Object.assign({arrastres}, puesto);
</script>"""


# ---------------------------------------------------------------- servidor de las paginas

class _Estado:
    prueba = "inicio"
    valores = {}
    layout = {}
    candado = threading.Lock()


class _Paginas(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _enviar(self, codigo, cuerpo, tipo="text/html; charset=utf-8"):
        crudo = cuerpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("content-type", tipo)
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    def do_GET(self):
        if self.path.startswith("/estado"):
            return self._enviar(200, json.dumps({"prueba": _Estado.prueba}), "application/json")
        return self._enviar(200, pagina(self.path.split("/p/", 1)[1].split("?")[0] if "/p/" in self.path else "inicio"))

    def do_POST(self):
        largo = int(self.headers.get("content-length") or 0)
        try:
            datos = json.loads(self.rfile.read(largo) or b"{}")
        except ValueError:
            datos = {}
        with _Estado.candado:
            if self.path.startswith("/valores"):
                _Estado.valores[datos.get("prueba")] = datos.get("valores") or {}
            elif self.path.startswith("/layout"):
                _Estado.layout[datos.get("prueba")] = datos
        self._enviar(200, "{}", "application/json")


def pagina(nombre):
    """El HTML completo de una pagina de prueba (con la marca de la esquina y el codigo que reporta)."""
    html = PAGINAS.get(nombre, PAGINAS["inicio"])
    cuerpo = html.replace("<body ", "<!doctype html><html><head><meta charset='utf-8'><title>NO LIMIT prueba</title>"
                          "</head><body ", 1)
    i = cuerpo.index(">", cuerpo.index("<body ")) + 1
    return cuerpo[:i] + COMUN + cuerpo[i:] + "</body></html>"


# ---------------------------------------------------------------- abrir el navegador

def _navegador():
    if sys.platform == "win32":
        candidatos = [os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                      os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                      os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
                      os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
                      os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")]
    else:
        candidatos = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    if os.environ.get("CLW_NAVEGADOR"):
        candidatos.insert(0, os.environ["CLW_NAVEGADOR"])
    for c in candidatos:
        if c and os.path.exists(c):
            return c
    return None


def _abrir(url, perfil):
    exe = _navegador()
    if not exe:
        return None, None
    args = [exe, f"--user-data-dir={perfil}", "--no-first-run", "--no-default-browser-check",
            "--disable-search-engine-choice-screen", "--disable-features=Translate,TranslateUI,msEdgeTranslate",
            "--disable-session-crashed-bubble", "--disable-infobars", "--disable-sync", "--disable-extensions",
            "--disable-background-networking", "--disable-component-update", "--use-mock-keychain",
            "--force-device-scale-factor=1", "--window-position=0,0", "--window-size=1000,740", f"--app={url}"]
    # (en Mac el navegador va en su propia sesion: asi, al cerrarlo, sus avisos de cierre no le llegan a NO LIMIT)
    return (subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=sys.platform != "win32"), os.path.basename(exe))


# ---------------------------------------------------------------- la IA de mentiras (ve lo que veria la de verdad)

def _lineas(texto):
    out = []
    for l in texto.splitlines():
        m = re.match(r"\[([A-Z]?\d+)\] \((-?\d+),(-?\d+)\) ?(.*)$", l)
        if m:
            out.append((m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)))
    return out


def _puntero(texto):
    m = re.search(r"esta en \((\d+),(\d+)\)", texto)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFKD", str(t).lower()) if not unicodedata.combining(c))


def _campos(texto, max_w=300, max_h=90):
    """Donde escribir, como lo escogeria la IA: los A# que son campo (Mac) o los C# (por su forma), del tamano
    de una casilla, ordenados por renglon y de izquierda a derecha."""
    a = [(i, x, y) for i, x, y, t in _lineas(texto) if i.startswith("A") and t.startswith("campo")]
    if not a:
        for i, x, y, t in _lineas(texto):
            m = re.match(r"(\d+)x(\d+)", t)
            if i.startswith("C") and m and 6 <= int(m.group(1)) <= max_w and 8 <= int(m.group(2)) <= max_h:
                a.append((i, x, y))
    return sorted(a, key=lambda t: (round(t[2] / 18), t[1]))


def _ids(texto, fragmento, exacto=False):
    f = _norm(fragmento)
    return [(int(i), x, y) for i, x, y, t in _lineas(texto)
            if i.isdigit() and (_norm(t).strip(" .:") == f if exacto else f in _norm(t))]


def _contestar_aleks(t):
    c = _campos(t, max_w=160, max_h=70)
    fila = [k for k in c if c and abs(k[2] - c[-1][2]) < 25][-3:]
    if len(fila) < 3:
        return {"tipo": "numerica", "respuesta": "A = 39 | b = 41.1 | c = 34.6", "acciones": [],
                "diag": [k[0] for k in c]}
    return {"tipo": "numerica", "respuesta": "A = 39 | b = 41.1 | c = 34.6", "acciones": [
        {"hacer": "escribir", "en": fila[0][0], "texto": "39"},
        {"hacer": "escribir", "en": fila[1][0], "texto": "41.1"},
        {"hacer": "escribir", "en": fila[2][0], "texto": "34.6"}],
        "calculo": ["180-84-57", "26*sind(84)/sind(39)", "26*sind(57)/sind(39)"]}


def _contestar_juego(t):
    c = _campos(t)[-4:]
    valores = ["4", "15", "5", "5"]
    return {"tipo": "completar", "respuesta": " | ".join(valores),
            "acciones": [{"hacer": "escribir", "en": k[0], "texto": v} for k, v in zip(c, valores)],
            "calculo": ["2+2", "5*3", "9-4", "10/2"]}


def _contestar_kahoot(t):
    c = _campos(t, max_w=700, max_h=120)
    ayuda = _ids(t, "Escribe tu respuesta")
    en = c[-1][0] if c else (ayuda[0][0] if ayuda else None)
    return {"tipo": "numerica", "respuesta": "56", "calculo": "7*8",
            "acciones": [{"hacer": "escribir", "en": en, "texto": "56"}] if en is not None else []}


def _contestar_menus(t):
    sel = [k for k in _ids(t, "Seleccionar") if len(_norm([l for l in _lineas(t) if l[0] == str(k[0])][0][3]).split()) <= 3]
    sel = sorted(sel, key=lambda k: k[1])
    ops = ["Democracia ateniense y filosofía clásica", "Sistema de caminos Qhapaq Ñan en los Andes",
           "Construcción de acueductos y derecho romano"]
    return {"tipo": "desplegable", "respuesta": " | ".join(ops),
            "acciones": [{"hacer": "elegir", "en": k[0], "opcion": o} for k, o in zip(sel, ops)]}


def _contestar_flechas(t):
    x, y = _puntero(t)                       # (la prueba deja el puntero sobre una flecha de subir)
    return {"tipo": "ordenar", "respuesta": "escritura, Roma, Colón, Revolución Francesa", "acciones": [
        {"hacer": "ordenar", "orden": ["Invención de la escritura cuneiforme (3200 a. C.)",
                                       "Caída del Imperio romano de Occidente (476 d. C.)",
                                       "Llegada de Cristóbal Colón a América (1492)",
                                       "Inicio de la Revolución Francesa (1789)"],
         "flechas": {"arriba": {"x": x, "y": y}}}]}


def _contestar_casillas(t):
    acciones = []
    for frag, texto in (("ceros son", "Sus raíces o ceros son x = 1 y x = 3."),
                        ("vertice se encuentra", "Su vértice se encuentra en x = 2."),
                        ("Interseca al eje", "Interseca al eje y en el punto (0, 3).")):
        ids = _ids(t, frag)
        if ids:
            acciones.append({"hacer": "clic", "en": ids[0][0], "texto": texto})
    return {"tipo": "opcion_multiple", "respuesta": "1, 3 y 4", "acciones": acciones}


def _contestar_completar(t):
    c = _campos(t, max_w=420, max_h=60)
    ayuda = _ids(t, "Tu respuesta")
    en = c[-1][0] if c else (ayuda[0][0] if ayuda else None)
    return {"tipo": "completar", "respuesta": "imprenta de tipos móviles",
            "acciones": [{"hacer": "escribir", "en": en, "texto": "imprenta de tipos móviles"}] if en is not None else []}


def _contestar_grafica(t):
    return {"tipo": "graficar", "respuesta": "y = 2x + 2", "acciones": [
        {"hacer": "clic", "en": _ids(t, "Recta")[0][0] if _ids(t, "Recta") else {"x": 60, "y": 40}, "texto": "Recta"},
        {"hacer": "clic", "en": {"gx": 0, "gy": 2}}, {"hacer": "clic", "en": {"gx": -1, "gy": 0}}]}


def _contestar_grafica_parabola(t):
    # (como a veces la IA de verdad: pica la herramienta y quiere trazar arrastrando; NO LIMIT solo pica los puntos)
    herr = _ids(t, "Parabola")
    return {"tipo": "graficar", "respuesta": "vertice (1, -4) y el punto (3, 0)", "acciones": [
        {"hacer": "clic", "en": herr[0][0] if herr else {"x": 30, "y": 120}, "texto": "Parábola"},
        {"hacer": "clic", "en": {"gx": 1, "gy": -4}},
        {"hacer": "arrastrar", "desde": {"gx": 1, "gy": -4}, "hasta": {"gx": 3, "gy": 0}},
        {"hacer": "clic", "en": {"gx": 3, "gy": 0}}]}


def _contestar_grafica_oscura(t):
    return {"tipo": "graficar", "respuesta": "(-3, 4) y (2, -1)", "acciones": [
        {"hacer": "clic", "en": {"gx": -3, "gy": 4}}, {"hacer": "clic", "en": {"gx": 2, "gy": -1}}]}


def _contestar_ordenar_arrastrar(t):
    return {"tipo": "ordenar", "respuesta": "Mercurio, Venus, Tierra, Marte, Júpiter",
            "acciones": [{"hacer": "ordenar", "orden": ["Mercurio", "Venus", "Tierra", "Marte", "Júpiter"]}]}


def _contestar_ordenar_puntero(t):
    return {"tipo": "ordenar", "respuesta": "Observación, Hipótesis, Experimentación, Análisis, Conclusión",
            "acciones": [{"hacer": "ordenar", "orden": ["Observación", "Hipótesis", "Experimentación",
                                                        "Análisis de resultados", "Conclusión"]}]}


def _id_parecido(t, texto):
    """El id de la caja cuyo texto mas se parece (el OCR lee 'Coraz6n' o '| Rifiones': la IA de verdad ve la imagen)."""
    import difflib
    mejor = (0.0, None)
    for i, x, y, tx in _lineas(t):
        if not i.isdigit():
            continue
        v = difflib.SequenceMatcher(None, _norm(texto), _norm(tx).strip(" |.:")).ratio()
        if v > mejor[0]:
            mejor = (v, (int(i), x, y))
    return [mejor[1]] if mejor[0] >= 0.6 else []


def _contestar_etiquetas(t):
    """Cada organo se arrastra hasta el 'Suelta aqui' de la columna de su funcion (el que queda abajo de ella)."""
    zonas = _ids(t, "Suelta")
    acciones = []
    for organo, funcion in (("Corazón", "Bombea la sangre"), ("Pulmones", "Intercambian"), ("Riñones", "Filtran la sangre")):
        desde, f = _id_parecido(t, organo), _ids(t, funcion)
        if not desde or not f or not zonas:
            continue
        z = min(zonas, key=lambda k: abs(k[1] - f[0][1]) + (0 if k[2] > f[0][2] else 9999))
        acciones.append({"hacer": "arrastrar", "desde": desde[0][0], "hasta": {"x": z[1], "y": z[2]}})
    return {"tipo": "arrastrar", "respuesta": "Corazón: bombea | Pulmones: intercambian | Riñones: filtran",
            "acciones": acciones}


def _cerca(crudos, esperados, tol=0.25):
    return len(crudos) == len(esperados) and all(abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol
                                                 for a, b in zip(crudos, esperados))


def _ok_aleks(v):
    return v.get("A") == "39" and v.get("b") == "41.1" and v.get("c") == "34.6"


# nombre, contestar, tipo (pista de UBICAR), casilla donde el usuario dejo el cursor antes, donde da el
# Ctrl / Option + clic (elemento, x, y: pixeles o fraccion del elemento), y como saber si quedo bien
PRUEBAS = [
    ("aleks", _contestar_aleks, "numerica", "c", ("pregunta", 30, 20), _ok_aleks),
    ("juego", _contestar_juego, "completar", "i4", ("pregunta", 40, 30),
     lambda v: v == {"1": "4", "2": "15", "3": "5", "4": "5"}),
    ("kahoot", _contestar_kahoot, "numerica", None, ("pregunta", 400, 30), lambda v: v.get("texto") == "56"),
    ("menus", _contestar_menus, "desplegable", None, ("pregunta", 40, 12),
     lambda v: v == {"Antigua Grecia": "Democracia ateniense y filosofía clásica",
                     "Imperio Inca": "Sistema de caminos Qhapaq Ñan en los Andes",
                     "Antigua Roma": "Construcción de acueductos y derecho romano"}),
    ("flechas", _contestar_flechas, "ordenar", None, ("sube1", 0.5, 0.5),
     lambda v: v.get("orden") == ["Invención de la escritura cuneiforme", "Caída del Imperio romano de Occidente",
                                   "Llegada de Cristóbal Colón a América", "Inicio de la Revolución Francesa"]
     and not v.get("arrastres")),
    ("casillas", _contestar_casillas, "opcion_multiple", None, ("pregunta", 40, 12),
     lambda v: v.get("marcadas") == [0, 2, 3]),
    ("completar", _contestar_completar, "completar", None, ("pregunta", 40, 12),
     lambda v: v.get("texto") == "imprenta de tipos móviles"),
    ("grafica", _contestar_grafica, "graficar", None, ("pregunta", 40, 10),
     lambda v: v.get("puntos") == [[0, 2], [-1, 0]]),
    ("grafica_parabola", _contestar_grafica_parabola, "graficar", None, ("pregunta", 40, 10),
     lambda v: v.get("puntos") == [[1, -4], [3, 0]] and _cerca(v.get("crudos") or [], [[1, -4], [3, 0]])
     and not v.get("herramienta") and not v.get("trazos")),
    ("grafica_oscura", _contestar_grafica_oscura, "graficar", None, ("pregunta", 40, 10),
     lambda v: v.get("puntos") == [[-3, 4], [2, -1]] and _cerca(v.get("crudos") or [], [[-3, 4], [2, -1]])),
    ("ordenar_arrastrar", _contestar_ordenar_arrastrar, "ordenar", None, ("pregunta", 40, 12),
     lambda v: v.get("orden") == ["Mercurio", "Venus", "Tierra", "Marte", "Júpiter"]),
    ("ordenar_puntero", _contestar_ordenar_puntero, "ordenar", None, ("pregunta", 40, 12),
     lambda v: v.get("orden") == ["Observación", "Hipótesis", "Experimentación", "Análisis de resultados", "Conclusión"]),
    ("etiquetas", _contestar_etiquetas, "arrastrar", None, ("pregunta", 40, 12),
     lambda v: v.get("Bombea la sangre a todo el cuerpo") == "Corazón"
     and v.get("Intercambian oxígeno y dióxido de carbono") == "Pulmones"
     and v.get("Filtran la sangre y forman la orina") == "Riñones"),
]


class _Ahora:
    """Lo que la IA falsa necesita saber de la prueba en curso para dar la caja de la pregunta (como la daria la de
    verdad): donde quedo la pregunta en la pantalla y que zona de la pantalla capturo NO LIMIT."""
    caja = None          # (x0, y0, x1, y1) de la pregunta, pixeles de la pantalla
    zona = None          # (left, top, w, h) de la captura, pixeles de la pantalla


def _fases(contestar, tipo):
    def elegir(t):
        if t.startswith("FASE: UBICAR"):
            m = re.search(r"Captura de (\d+)x(\d+)", t)
            W, H = (int(m.group(1)), int(m.group(2))) if m else (1000, 700)
            caja = [0, 0, W, H]
            if _Ahora.caja and _Ahora.zona and _Ahora.zona[2]:
                left, top, w, _h = _Ahora.zona
                s = W / float(w)
                x0, y0, x1, y1 = _Ahora.caja
                caja = [round((x0 - left) * s), round((y0 - top) * s), round((x1 - left) * s), round((y1 - top) * s)]
            return json.dumps({"hay_pregunta": True, "caja": caja, "tipo": tipo})
        if t.startswith("FASE: REVISAR"):
            return json.dumps({"ok": True})
        return json.dumps(contestar(t))
    return elegir


# ---------------------------------------------------------------- la prueba

def _escala():
    if sys.platform != "darwin":
        return 1.0
    from .mac import entrada as me          # (en Mac: puntos x escala = pixeles)
    return me.escala_actual()


def _pantalla_px():
    """(ancho, alto) de la pantalla principal en pixeles."""
    from . import motor
    if sys.platform == "darwin":
        from .mac import entrada as me
        (x, y, w, h), s = me.pantalla_en(10, 10)
        me.poner_escala(s)
        return int(w * s), int(h * s)
    vx, vy, vw, vh = motor.pantalla_virtual()
    return vw, vh


def _origen():
    """Donde quedo la esquina de la pagina en la pantalla (pixeles): se busca el cuadrito magenta."""
    from . import motor
    W, H = _pantalla_px()
    im = motor.capturar_zona(0, 0, min(W, 1300), min(H, 900))
    px = im.load()
    k = _escala()
    for y in range(0, min(im.height, 420)):
        for x in range(0, min(im.width, 640)):
            r, g, b = px[x, y]
            if r > 230 and g < 40 and b > 230:
                return x - 2 * k, y - 2 * k
    return None


def _zona_captura(X, Y):
    """La zona que captura NO LIMIT con un Ctrl / Option + clic en (X, Y), en pixeles de la pantalla."""
    from . import motor
    if sys.platform == "darwin":
        from .mac import captura
        from .mac import entrada as me
        s = me.escala_actual()
        pantalla, _ = me.pantalla_en(X / s, Y / s)
        l, t, w, h = captura.zona(X / s, Y / s, pantalla, motor.TAM_BASE, motor.ARRIBA_BASE)
        return round(l * s), round(t * s), round(w * s), round(h * s)
    return motor.calcular_zona(X, Y, motor.pantalla_virtual(), motor.factor_zoom())


def _esperar_layout(nombre, limite=25.0):
    fin = time.time() + limite
    while time.time() < fin:
        lay = _Estado.layout.get(nombre)
        if lay and lay.get("r") is not None:
            return lay
        time.sleep(0.2)
    return None


SEG_POR_PRUEBA = 150


def _sin_error(fn):
    try:
        fn()
    except Exception:
        pass


def _con_tiempo(fn, seg):
    """Corre fn en otro hilo. True si termino a tiempo; False si se paso (el hilo se deja: es de fondo)."""
    hilo = threading.Thread(target=lambda: _sin_error(fn), name="prueba-navegador", daemon=True)
    hilo.start()
    hilo.join(seg)
    return not hilo.is_alive()


def _pilas():
    """Que estaba haciendo cada hilo (solo los de NO LIMIT y el de la prueba)."""
    nombres = {t.ident: t.name for t in threading.enumerate()}
    out = {}
    for ident, marco in sys._current_frames().items():
        n = nombres.get(ident, str(ident))
        if n in ("trabajo", "prueba-navegador", "esc") or n.startswith("Thread"):
            out[n + f"-{ident}"] = "".join(traceback.format_stack(marco)[-8:])[-1800:]
    return out


def _cerrar_navegador(proc, perfil):
    """Cierra el navegador CON todos sus procesos (si queda uno vivo, Windows se queda esperando)."""
    if proc is None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=20,
                           creationflags=0x08000000)
        else:
            import signal
            try:
                os.killpg(proc.pid, signal.SIGTERM)      # el navegador y sus ayudantes (su propio grupo)
            except Exception:
                proc.terminate()
            try:
                proc.wait(5)
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    proc.kill()
    except Exception:
        pass


def _una(prueba, paso, ctx):
    """Una pregunta en el navegador: abrir la pagina, encontrarla en la pantalla, Ctrl / Option + clic y ver que
    quedo. 'paso' dice por donde va (por si se cuelga)."""
    nombre, contestar, tipo, enfoque, disparo, revisar = prueba
    IA, bot, detalle, salida, d = ctx["IA"], ctx["bot"], ctx["detalle"], ctx["salida"], ctx["datos"]
    entrada, motor = ctx["entrada"], ctx["motor"]

    def ir(donde):
        paso["donde"] = donde
        log.info("navegador: %s: %s", nombre, donde)
    t0 = time.time()
    pedidos0 = getattr(IA, "pedidos", 0)
    try:
        ir("abrir la pagina")
        _Estado.prueba = nombre
        lay = _esperar_layout(nombre)
        time.sleep(0.8)
        lay = _Estado.layout.get(nombre) or lay
        ir("buscar la pagina en la pantalla")
        origen = _origen()
        if not lay or not lay.get("r") or origen is None:
            detalle[nombre] = {"ok": False, "error": "la pagina no aparecio en la pantalla", "layout": bool(lay),
                               "origen": origen}
            _sin_error(lambda: motor.capturar_zona(0, 0, *_pantalla_px()).save(os.path.join(salida, f"nav_{nombre}.png")))
            return
        ox, oy = origen
        k = _escala()
        r = lay["r"]

        def punto(clave, fx, fy):
            x, y, w, h = r[clave]
            if 0 < fx < 1 or 0 < fy < 1:
                return ox + (x + w * fx) * k, oy + (y + h * fy) * k
            return ox + (x + fx) * k, oy + (y + fy) * k
        ir("traer el navegador al frente")
        entrada.clic(ox + 960 * k, oy + 12 * k)
        time.sleep(0.4)
        if enfoque:
            ir("dejar el cursor en una casilla")
            X, Y = punto(enfoque, 0.5, 0.5)
            entrada.clic(X, Y, lento=True)                  # el usuario dejo el cursor del teclado en esa casilla
            time.sleep(0.5)
        foco_antes = (_Estado.layout.get(nombre) or {}).get("foco")
        x, y, w, h = r["pregunta"]
        m = 14
        _Ahora.caja = (ox + (x - m) * k, oy + (y - m) * k, ox + (x + w + m) * k, oy + (y + h + m) * k)
        X, Y = punto(*disparo)
        _Ahora.zona = _zona_captura(X, Y)
        fases, vistos = _fases(contestar, tipo), []

        def elegir(t):
            vistos.append(t[:2500])
            return fases(t)
        IA.elegir = elegir
        ir("Ctrl / Option + clic")
        entrada.mover(X, Y)
        time.sleep(0.3)
        bot._disparo(X, Y)                                 # (como el Ctrl / Option + clic del usuario)
        time.sleep(1.0)
        ir("NO LIMIT contestando")
        fin = time.time() + 90
        while time.time() < fin and bot._ocupado.locked():
            time.sleep(0.3)
        time.sleep(1.2)
        ir("ver que quedo")
        v = dict(_Estado.valores.get(nombre) or {})
        ok = bool(revisar(v))
        actividad = []
        while True:
            try:
                e = bot.eventos.get_nowait()
            except Exception:
                break
            if e and e[0] == "actividad":
                actividad.append(e[1])
        detalle[nombre] = {"ok": ok, "valores": v, "actividad": actividad[-3:], "seg": round(time.time() - t0, 1),
                           "pedidos_ia": getattr(IA, "pedidos", 0) - pedidos0, "foco_antes": foco_antes,
                           "escala": k, "dpr": lay.get("dpr")}
        if bot._ocupado.locked():
            detalle[nombre]["ok"] = False
            detalle[nombre]["error"] = "NO LIMIT no termino en 90 s"
            detalle[nombre]["pilas"] = _pilas()
        if not detalle[nombre]["ok"]:          # (para saber que vio la IA: lo que manda NO LIMIT en CONTESTAR)
            detalle[nombre]["ia"] = [t for t in vistos if t.startswith("FASE: CONTESTAR")][:1]
        ir("guardar las fotos")
        try:
            motor.capturar_zona(0, 0, min(_pantalla_px()[0], int(1000 * k)),
                                min(_pantalla_px()[1], int(760 * k))).save(os.path.join(salida, f"nav_{nombre}.png"))
            for f in ("ultima_captura.png", "ultima_revision.png"):
                rev = os.path.join(d, "revision", f)
                if os.path.exists(rev):
                    shutil.copy(rev, os.path.join(salida, f"nav_{nombre}_{f.split('_')[1]}"))
                    os.remove(rev)
        except Exception:
            pass
        ir("listo")
    except Exception as e:
        detalle[nombre] = {"ok": False, "error": repr(e), "traza": traceback.format_exc()[-1500:]}


def correr(salida, IA, resultados, guardar=None, nombre_resultado="navegador", solo=None):
    """Corre las pruebas en el navegador y deja el resultado en resultados[nombre_resultado]."""
    import queue

    from . import config, entrada, motor
    from .bot import Bot
    t_total = time.time()
    detalle = {}
    resultados[nombre_resultado] = {"ok": False, "detalle": detalle, "nota": "corriendo"}
    srv = _servidor(_Paginas)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    perfil = tempfile.mkdtemp(prefix="nl-nav-")
    proc, cual = _abrir(base + "/p/inicio", perfil)
    if proc is None:
        resultados[nombre_resultado] = {"ok": False, "error": "no hay Chrome ni Edge en esta maquina"}
        srv.shutdown()
        return
    d = tempfile.mkdtemp(prefix="nl-nav-cfg-")
    os.environ["CLW_DATOS"] = d
    c = config.Config(os.path.join(d, "ajustes.json"))
    c["guardar_capturas"] = True
    c.poner_clave("claude", "sk-ant-prueba")
    bot = Bot(c, queue.Queue())
    bot.activo = True
    pruebas = [p for p in PRUEBAS if not solo or p[0] in solo]
    ctx = {"IA": IA, "bot": bot, "detalle": detalle, "salida": salida, "datos": d, "entrada": entrada, "motor": motor}
    try:
        if not _esperar_layout("inicio", 45):
            resultados[nombre_resultado] = {"ok": False, "error": "el navegador no abrio la pagina", "navegador": cual}
            return
        time.sleep(1.5)
        for prueba in pruebas:
            nombre = prueba[0]
            paso = {"donde": "empezar", "t": time.time()}
            hecho = _con_tiempo(lambda: _una(prueba, paso, ctx), SEG_POR_PRUEBA)
            if hecho is not True:
                # se colgo: se apunta donde iba y que hacia cada hilo (para arreglarlo) y ya no se sigue
                log.warning("navegador: %s se colgo en '%s'", nombre, paso["donde"])
                detalle[nombre] = {"ok": False, "error": f"se colgo (mas de {SEG_POR_PRUEBA} s) en: {paso['donde']}",
                                   "pilas": _pilas()}
                if guardar:
                    _sin_error(guardar)
                break
            if guardar:
                _sin_error(guardar)
    finally:
        bot.activo = False
        _cerrar_navegador(proc, perfil)
        srv.shutdown()
        shutil.rmtree(perfil, ignore_errors=True)
    buenas = [n for n, x in detalle.items() if x.get("ok")]
    resultados[nombre_resultado] = {"ok": len(buenas) == len(pruebas), "navegador": cual,
                                    "bien": f"{len(buenas)}/{len(pruebas)}", "seg": round(time.time() - t_total, 1),
                                    "detalle": detalle}
