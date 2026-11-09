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
rm -f salida/NO-LIMIT-Mac.dmg
hdiutil create -volname "NO LIMIT" -srcfolder "$TMP" -ov -format UDZO salida/NO-LIMIT-Mac.dmg
ls -la salida/NO-LIMIT-Mac.dmg
