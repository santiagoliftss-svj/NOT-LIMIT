#!/bin/bash
# Firma NO LIMIT.app. Con el certificado propio de NO LIMIT (secretos MAC_FIRMA_P12 y MAC_FIRMA_CLAVE del repo)
# la firma es siempre la misma, asi macOS NO vuelve a pedir los permisos despues de cada actualizacion.
# Sin el certificado (o si algo falla) se firma ad-hoc, como antes.
APP="$1"
if [ -n "${MAC_FIRMA_P12:-}" ] && [ -n "${MAC_FIRMA_CLAVE:-}" ]; then
  KC="$RUNNER_TEMP/firma-nolimit.keychain-db"
  KCP="$(uuidgen)"
  P12="$RUNNER_TEMP/firma-nolimit.p12"
  printf '%s' "$MAC_FIRMA_P12" | base64 --decode > "$P12"
  if security create-keychain -p "$KCP" "$KC" \
     && security set-keychain-settings -lut 21600 "$KC" \
     && security unlock-keychain -p "$KCP" "$KC" \
     && security import "$P12" -k "$KC" -P "$MAC_FIRMA_CLAVE" -T /usr/bin/codesign \
     && security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KCP" "$KC" >/dev/null; then
    security list-keychains -d user -s "$KC" $(security list-keychains -d user | tr -d '"')
    ID="$(security find-identity -p codesigning "$KC" | awk '/NO LIMIT Firma/ {print $2; exit}')"
    if [ -n "$ID" ] && codesign --force --deep --keychain "$KC" -s "$ID" "$APP"; then
      rm -f "$P12"
      echo "firmada con el certificado de NO LIMIT"
      codesign -d -r- "$APP" 2>&1 | tail -1
      exit 0
    fi
  fi
  rm -f "$P12"
  echo "::warning::no se pudo firmar con el certificado de NO LIMIT; se firma ad-hoc"
fi
codesign --force --deep -s - "$APP"
echo "firmada ad-hoc"
