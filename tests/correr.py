"""Corre todas las pruebas (funciones que empiezan con 'prueba_'). Uso: python tests/correr.py"""

import importlib.util
import os
import sys
import time
import traceback

AQUI = os.path.dirname(os.path.abspath(__file__))


def main():
    fallas = 0
    total = 0
    for nombre in sorted(os.listdir(AQUI)):
        if not (nombre.startswith("test_") and nombre.endswith(".py")):
            continue
        spec = importlib.util.spec_from_file_location(nombre[:-3], os.path.join(AQUI, nombre))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for f in [getattr(mod, n) for n in dir(mod) if n.startswith("prueba_")]:
            total += 1
            t = time.time()
            try:
                f()
                print(f"  ok   {nombre}:{f.__name__} ({time.time() - t:.1f}s)")
            except Exception:
                fallas += 1
                print(f"  FALLA {nombre}:{f.__name__}")
                traceback.print_exc()
    print(f"\n{total - fallas}/{total} pruebas bien")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
