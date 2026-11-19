#!/bin/bash
# Arma salida/NO-LIMIT-Mac.dmg con la app, un atajo a Aplicaciones y el LEEME.
set -euo pipefail
cd "$(dirname "$0")/.."
TMP=build/dmg
rm -rf "$TMP"
mkdir -p "$TMP" salida
ditto "dist/NO LIMIT.app" "$TMP/NO LIMIT.app"
ln -s /Applications "$TMP/Aplicaciones"
cp build/LEEME_MAC.txt "$TMP/LEEME.txt"
DMG="${DMG:-NO-LIMIT-Mac.dmg}"
rm -f "salida/$DMG"
# (en las Mac de GitHub hdiutil a veces falla con "Resource busy" porque el sistema esta revisando los archivos
# recien hechos: se espera un poco y se vuelve a intentar)
for intento in 1 2 3 4 5; do
  if hdiutil create -volname "NO LIMIT" -srcfolder "$TMP" -ov -format UDZO "salida/$DMG"; then
    break
  fi
  if [ "$intento" = 5 ]; then
    echo "hdiutil fallo 5 veces" >&2
    exit 1
  fi
  echo "hdiutil fallo (intento $intento): se reintenta en $((intento * 10)) s" >&2
  rm -f "salida/$DMG"
  hdiutil info >&2 || true
  sleep $((intento * 10))
done
ls -la "salida/$DMG"
