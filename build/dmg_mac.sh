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
hdiutil create -volname "NO LIMIT" -srcfolder "$TMP" -ov -format UDZO "salida/$DMG"
ls -la "salida/$DMG"
