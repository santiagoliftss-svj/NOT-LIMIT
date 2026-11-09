"""Lo poquito que cambia segun el sistema en lo que se le dice al usuario."""

import sys

MAC = sys.platform == "darwin"
WINDOWS = sys.platform == "win32"

ATAJO = "Option + clic" if MAC else "Ctrl + clic"          # en Mac, Ctrl + clic es clic derecho
A_DONDE = "a la barra de arriba" if MAC else "junto al reloj"
