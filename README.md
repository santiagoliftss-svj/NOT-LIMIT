# NO LIMIT

(Antes se llamaba CLW GANG.)

Contesta preguntas de la pantalla con un **Ctrl + clic**.

**Descarga:** https://santiagoliftss-svj.github.io/clw-gang/

- Opción múltiple: marca la respuesta.
- Preguntas abiertas: escribe la respuesta sola (corta o larga según la pregunta), y llena varias cajitas si la pregunta tiene varias.
- Funciona con Claude, Gemini (clave gratis) o ChatGPT. Cada quien pone su propia API key; se guarda cifrada en su computadora.
- Al tocar **INYECTAR** la ventana se va junto al reloj (icono junto al reloj) y sigue activa ahí: desde el icono se abre, se detiene o se cierra. Escondida no dibuja nada.
- No estorba en juegos: con un juego en pantalla completa, o con Ctrl apretado mucho rato (agacharse), el Ctrl + clic no hace nada.
- No inyecta nada en otros programas ni en la memoria: solo toma una captura cuando haces Ctrl + clic.

## Cómo se arma

GitHub Actions arma todo en Windows cada vez que se sube un cambio a `main`:

1. Corre las pruebas (`python tests/correr.py`).
2. Arma el `.exe` con PyInstaller y le mete Tesseract (OCR en español).
3. Corre la autoprueba del `.exe` en Windows (incluye un Ctrl + clic real).
4. Arma el instalador con Inno Setup.
5. Si `app/clw/version.py` tiene una versión nueva, la publica en *Releases*.

Para sacar una versión nueva: cambia `VERSION` en `app/clw/version.py` y sube el cambio.

## Carpetas

- `app/` código de la app (`clw_gang.py` es el inicio).
- `tests/` pruebas.
- `build/` PyInstaller y Tesseract.
- `installer/` instalador (Inno Setup).
- `docs/` página de descarga (GitHub Pages).
- `herramientas/` genera el logo, los iconos, las imágenes del instalador y la vista de la app para la página.
