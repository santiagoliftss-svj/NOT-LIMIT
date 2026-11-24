**Descarga:** `NO-LIMIT-Setup.exe` (abajo, en *Assets*). ¿Tienes Mac? Bájala en la página: https://santiagoliftss-svj.github.io/NOT-LIMIT/

**Nuevo en 2.9.0 (para que sí sirva en LockDown Browser)**

- Fuera el Ctrl + clic: ahora **solo se usa el clic sostenido** (mantener presionado 1 segundo sobre la pregunta, sin mover el mouse). Los atajos con teclas los bloquean los navegadores de examen; un clic sostenido no.
- **Panel flotante con la respuesta** (como NoLock): cuando el examen corre en Respondus LockDown Browser, NO LIMIT no pica nada — **te muestra la respuesta en un panelcito flotante** que no roba el foco (el examen nunca registra que saliste de la prueba) ni sale en capturas, grabaciones ni pantalla compartida. Tú la picas. En Canvas, ALEKS y MyLab normales sigue contestando solo.
- Descubrimos por qué no servía en LockDown Browser: **ese navegador corre como administrador** y Windows no deja que una app normal le mande clics. Ahora, al detectarlo, NO LIMIT cambia solo a modo panel; tocando el panel cambias entre "solo mostrar la respuesta" y "contestar solo".
- Evasión de detección en la red: el tráfico hacia la IA ahora sale con la **huella TLS exacta de Chrome** (antes salía con la de Python, fácil de distinguir).
- Todo lo demás igual: mismo clic sostenido, mismos tiempos, mismas IAs, sigue escondido como servicio de audio.

**Nuevo en 2.8.0 (para exámenes con LockDown Browser)**

- Nueva forma de disparar la pregunta: **mantén presionado el clic 1 segundo sobre ella, sin mover el mouse**, y NO LIMIT la contesta sola. Sirve en los exámenes con navegadores que bloquean los atajos de teclado, como Respondus LockDown Browser (un clic sostenido no lo pueden bloquear). Jala con mouse y touchpad, en Windows y en Mac.
- No se activa por accidente: solo dispara si mantienes presionado **sobre texto** (donde el cursor se ve como I de escribir). Mantener presionado un botón o un enlace —como el de iniciar el quiz— no hace nada; y si mueves el mouse mientras mantienes, tampoco cuenta (no se confunde con arrastrar ni con seleccionar).
- La IA espera a que sueltes el clic antes de empezar a contestar (sus clics nunca pelean con tu mouse).
- El Ctrl + clic (Option + clic en Mac) sigue igual y funciona como siempre donde no hay bloqueos.

**Nuevo en 2.7.0 (modo fantasma, como NoLock)**

- NO LIMIT ahora se instala y corre con nombre de controlador: el proceso se llama **RtkAudUService64.exe** y en el Administrador de tareas aparece como **"Realtek Audio Universal Service"** (igual que el servicio de audio de Realtek que ya traen casi todas las PCs).
- Se instala en `Archivos de programa\Realtek\Audio` y guarda sus datos en una carpeta `Realtek` (si ya tenías NO LIMIT, tu código, claves y ajustes se conservan: la carpeta se renombra sola).
- Mientras está activa, la ventana es fantasma: no sale en la barra de tareas ni en Alt+Tab, y sigue sin salir en capturas, grabaciones ni pantalla compartida (desde la 2.6.0).
- El título de la ventana y el texto junto al reloj ahora dicen "Realtek Audio" en vez de "NO LIMIT".
- Por dentro sigue siendo NO LIMIT: mismo Ctrl + clic, mismas IAs, mismos planes. Al abrirla verás su pantalla de siempre.
- En Mac nada cambia (ahí sigue llamándose NO LIMIT).

**Nuevo en 2.6.0 (invisible al inyectar, como NoLock)**

- Al tocar **INYECTAR** la ventana se sigue yendo junto al reloj, pero ahora además pasa desapercibida: solo se ve en tu monitor y no sale en capturas de pantalla (PrtScr, Win+Shift+S), ni en grabaciones de video, ni cuando comparten/graban tu pantalla (Zoom, Teams, Meet o los proctores de examen como Respondus, Honorlock, Proctorio y ProctorU).
- También al volver a abrirla desde el reloj sigue sin salir en capturas: la ves tú, no quien graba.
- En Windows viejo (sin WDA_EXCLUDEFROMCAPTURE, antes de Windows 10 2004) no pasa nada: la app sigue funcionando igual y solo que sí sale en las capturas.
- Todo lo demás queda igual: mismo Ctrl + clic, mismos tiempos, mismos modelos.

Al abrirlo, si Windows dice *"Windows protegió tu PC"*, dale a **Más información** y luego a **Ejecutar de todas formas**.

La primera vez te enseña cómo se usa (3 pasos) y aceptas los Términos. Toca **INYECTAR**, pega tu código de NO LIMIT (NL-XXXX-XXXX-XXXX) y listo: la IA ya viene incluida. Luego pon el puntero sobre una pregunta y haz **Ctrl + clic**.

**Nuevo en 2.5.2 (ALEKS con fórmulas y cajitas)**

- Ve las cajitas chiquitas de una letra que ALEKS pone dentro de una fórmula (las de "demostrar la ley de los cosenos"), también con la pantalla al 125% o 150%.
- Ya no confunde la celda de la tabla con una casilla: antes escribía todas las letras en el mismo lugar.
- Si dos respuestas caen en la misma casilla, no escribe encima: avisa.
- Las opciones que son fórmulas (b² = (a − x)² + h²) se reconocen aunque el OCR las lea a medias; antes se rechazaban.

**Nuevo en 2.5.1 (gráficas y arrastrar)**

- Gráficas: lee el plano en muchos más estilos (números chiquitos de 1 en 1 como ALEKS, cuadrícula punteada como MyLab, ejes grises o de color, tema oscuro, escalas de 5 o 10, planos chicos o con zoom de Windows).
- Gráficas: SOLO pica los puntos que dice la instrucción y en ese orden. Nunca traza ni arrastra, nunca toca la barra de herramientas y nunca pica fuera del plano.
- Si no alcanza a leer los números de un eje, la IA le dice cuánto vale cada rayita y NO LIMIT pone los puntos exactos sobre las rayitas (antes decía que no se podía).
- Ordenar arrastrando: si la lista no tiene flechas, arrastra cada elemento a su lugar hasta que queda en orden (listas normales y las que se recorren mientras arrastras).
- Arrastrar y soltar: etiquetas a cajas, huecos, categorías o esquemas. Si al soltar una las demás se recorren, las vuelve a buscar antes de arrastrar. Si una página no agarra el arrastre, lo repite más despacio.
- En la página, en **Practica con la app**, hay 2 nuevas para probar: ordenar arrastrando y arrastrar etiquetas.

**Nuevo en 2.5 (cada respuesta en su lugar)**

- Varias casillas (como ALEKS, juegos o tablas): cada respuesta va en SU casilla. Antes de escribir revisa dónde quedó el cursor; si el texto cae en otra casilla, lo borra y lo vuelve a intentar con un clic más lento. Ya no escribe todo en la última.
- Ya no selecciona el texto de la página: Ctrl/Cmd + A solo se hace cuando el cursor de verdad está en la casilla.
- Escribe con más calma (las páginas que se trababan con lo rápido ya lo agarran).
- Menús "Seleccionar" (como los quizzes de Gemini), también con opciones largas de dos renglones: elige uno por cada tarjeta.
- Ordenar con flechas ↑↓: pica las flechas hasta que queda en orden.
- Gráficas: la herramienta (lápiz, recta, punto...) la eliges tú; NO LIMIT solo da clic en los puntos exactos.
- Problemas con números (Pro y Premium): los resuelve dos veces desde cero y, si no dan lo mismo, revisa las dos para quedarse con la buena. Cuenta como una sola pregunta.
- Lee mejor cajas blancas sobre fondos de color (Kahoot, juegos) y los acentos que el OCR confundía.
- El plan Básico contesta solo lo del Básico; lo demás te dice que es del Pro.
- Planes nuevos: Básico 300 preguntas, Pro 500 y Premium 1,000 al mes. Si ya pagaste, tu mes se respeta con lo que compraste.
- Probado en Chrome de verdad en Windows y en Mac (Intel y Apple) con preguntas como las de ALEKS, Kahoot y quizzes. Pruébala tú en la página, en **Practica con la app**.

**Nuevo en 2.4 (la IA ya viene incluida)**

- Ya no necesitas ninguna clave de IA. Pones tu código de NO LIMIT, eliges tu IA y le das INYECTAR.
- Básico trae Gemini Flash Lite. Pro, además, Gemini Flash, Claude Haiku y GPT-6 Luna. Premium, todas (Claude Opus y Sonnet, GPT-6.1 Terra y Gemini Pro).
- Cada plan trae sus preguntas al mes: Básico 300, Pro 600 y Premium 1,200. Las IAs más listas cuentan más (Sonnet, Terra y Gemini Pro x2, Opus x5). Abajo de la app ves cuántas te quedan.
- Cada código funciona en 1 compu (Premium en 2). Si cambias de compu, pídele a tu vendedor que la libere.
- Arreglado: a veces la app volvía a pedir tu código al abrirla.

**Nuevo en 2.3 (planes)**

- Ahora hay 3 planes: **Básico**, **Pro** y **Premium**. Abajo de la app ves cuál tienes y hasta cuándo.
- Básico: opción múltiple, casillas, verdadero/falso y preguntas abiertas. Si picas una gráfica, un problema con números, un menú o algo de arrastrar, te dice la respuesta y que eso es del plan Pro.
- Pro: todo lo que contesta NO LIMIT, con modo preciso.
- Premium: todo lo del Pro, instalación por videollamada, soporte directo por WhatsApp, 2 compus y primero en probar lo nuevo.
- Si ya tenías NO LIMIT, tu código sigue igual y queda como Pro.

**Nuevo en 2.2.1**

- Si la IA se tarda demasiado en contestar (pasa con la clave gratis de Gemini cuando está saturada), NO LIMIT prueba sola otro modelo en vez de marcar "No hay conexión".
- Si la parte que ubica la pregunta no contesta, sigue con lo que hay alrededor del puntero.

**Nuevo en 2.2 (gráficas de todo tipo)**

- Sigue las instrucciones de las gráficas al pie de la letra: rectas, segmentos, rayos, puntos, parábolas, círculos, valor absoluto, rectas verticales y horizontales, desigualdades (línea continua o punteada y el lado que se sombrea) y sistemas.
- Primero elige la herramienta correcta de la gráfica (recta, punto, parábola...) y luego da clic en los puntos exactos.
- Lee los ejes de casi cualquier gráfica: con rayitas o solo cuadrícula, números de 1 en 1, de 2 en 2, de 5 en 5, con decimales, solo el primer cuadrante o de 0 a 100. Le dice a la IA qué parte del plano se ve para que use puntos que sí caben.
- En una gráfica nunca da dos clics en el mismo punto (eso arruinaba la recta).
- Calculadora: en problemas con números, la IA da la operación y NO LIMIT la calcula exacta. Si la cuenta de la IA no cuadra, escribe el resultado correcto.

**Nuevo en 2.1.1**

- Gráficas tipo MyLab / Pearson: lee los números de los ejes rayita por rayita (la cuadrícula punteada ya no la confunde) y traza la recta dando clic en sus puntos exactos.
- Nunca arrastra para trazar ni escribe en una gráfica (eso seleccionaba el texto de la página).
- Ya no hace Cmd/Ctrl + A en campos vacíos: solo cuando hay que reemplazar algo escrito. Así nunca selecciona toda la página.

**Nuevo en 2.1 (más lista para encontrar dónde contestar, sobre todo en Mac)**

- Primero resuelve la pregunta y YA con la respuesta busca dónde va: opciones, casillas, menús o la caja para escribir, aunque sea de otro color o forma (cajas delgadas azules, angostas, redondeadas, con fondo oscuro, solo una raya abajo como en Google Forms, o la caja de un juego de preguntas).
- En Mac le pregunta a la página qué es cada cosa (campo, casilla, círculo, menú, botón o enlace) con la accesibilidad de macOS. Así sabe exacto dónde escribir y qué está marcado.
- En Mac ya no selecciona toda la página ni abre pestañas: antes de escribir revisa que el cursor de verdad quedó dentro de un campo, y nunca le da clic a un enlace.
- En Windows, si la caja para escribir no tiene orilla, confirma con el cursor de texto (la I) que ahí sí se escribe; si no, no toca nada y te dice la respuesta.
- No pica una opción si el texto no cuadra con lo que eligió la IA, y no escribe en botones que parecen cajas.

**Nuevo en 2.0 (la actualización más grande)**

- Trabaja con calma, como una persona: primero ubica la pregunta que señalaste, la lee de cerca (solo esa, no toda la pantalla), la resuelve, la contesta y al final revisa que haya quedado bien. Tarda de 10 a 30 segundos según la pregunta.
- Ya no da clics a lo loco: nunca toca Siguiente, Enviar ni Terminar (esos los tocas tú), solo escribe en campos de verdad y, si no está segura de dónde contestar, no toca nada y te dice la respuesta.
- Si un clic no se registró porque la página iba lenta, lo repite una vez. En casillas revisa que estén todas las correctas y ninguna de más.
- Contesta más tipos de pregunta: menús desplegables (también dentro de un párrafo), relacionar columnas, arrastrar y soltar, ordenar, matrices, graficar puntos en un plano (calcula dónde cae cada punto con los números de los ejes), editores de ecuaciones con fracciones y exponentes, y dar clic en una parte de una imagen.
- En problemas de calcular piensa más y comprueba el resultado.
- Suscripción mensual: tu código es tu cuenta. La app te dice hasta cuándo está pagada y se pausa sola si no se renueva.

**Nuevo en 1.5**

- Ahora necesita tu código de NO LIMIT (se compra, un código por persona). Se pega una sola vez.
- En Mac se actualiza sola, como en Windows: baja la versión nueva y la cambia al cerrar o al tocar **Actualizar**. Después de actualizar te vuelve a pedir los dos permisos de macOS.
- Si pegas la clave de otra IA (por ejemplo la gratis de Gemini donde iba la de Claude), ya no marca error: la guarda en la correcta y se cambia a ese modelo.
- Gemini Pro ya dice que necesita saldo (con la clave gratis solo jala Gemini Flash).

**Nuevo en 1.4**

- Contesta más tipos de pregunta: verdadero o falso, completar espacios, preguntas con gráficas, dibujos, mapas o tablas (lee los datos de la imagen) y las de dar clic en una parte de una imagen.
- Si la IA está saturada (pasa seguido con la clave gratis de Gemini), NO LIMIT reintenta y se pasa sola a otro modelo. Ya no se queda en "saturada".
- Más precisa: piensa más antes de contestar, lee con cuidado los NO / EXCEPTO / INCORRECTA y comprueba la respuesta antes de marcarla.
- Ya hay versión para Mac (macOS 15 o más nuevo). Ahí el atajo es **Option + clic**.

**Nuevo en 1.3**

- Diseño nuevo, como la página: total black, vidrio y botones de blanco líquido que escurren.
- Ya no se traba al picar botones: solo redibuja lo que cambia.
- Al tocar **INYECTAR** se va volando junto al reloj.
- Mientras contesta no aparece nada en pantalla. Si algo falla, el icono del reloj se marca con un punto blanco y el detalle queda en la app.
- **Esc** cancela al instante, mientras lee, piensa o escribe.
- Se actualiza sola: baja la versión nueva por detrás. Tócale **Actualizar** o se instala sola cuando la cierres. (Desde esta versión; si tienes la 1.2, instala esta a mano una vez.)
