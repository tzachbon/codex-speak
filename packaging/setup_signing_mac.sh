#!/bin/bash
# Run once on a Mac that builds Harness Discussion: creates the local signing identity that build_mac.sh uses.
# An ad-hoc signature changes with every build, so macOS drops the Accessibility grant after each
# rebuild. A fixed certificate keeps it. The self-signed key lives in its own keychain and signs only
# local builds; that keychain's random password is stored in the login keychain.
set -euo pipefail
name="Harness Discussion Local Signing"
keychain="$HOME/Library/Keychains/harness-discussion-signing.keychain-db"
service=harness-discussion-signing

create() {
    local password
    work=$(mktemp -d)  # global: the exit trap runs after this function returns
    trap 'rm -rf "$work"' EXIT  # the key leaves no copy outside the keychain
    password=$(openssl rand -hex 24)
    security add-generic-password -U -s "$service" -a "$USER" -l "$name keychain" -w "$password"
    security create-keychain -p "$password" "$keychain"
    security unlock-keychain -p "$password" "$keychain"
    cat > "$work/req.cnf" <<EOF
[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = $name
[v3]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
EOF
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -config "$work/req.cnf" \
        -keyout "$work/key.pem" -out "$work/cert.pem" 2>/dev/null
    # macOS cannot read the PKCS#12 encryption that current OpenSSL uses by default
    openssl pkcs12 -export -inkey "$work/key.pem" -in "$work/cert.pem" -out "$work/id.p12" -name "$name" \
        -passout "pass:$password" -certpbe PBE-SHA1-3DES -keypbe PBE-SHA1-3DES -macalg sha1
    security import "$work/id.p12" -k "$keychain" -P "$password" -T /usr/bin/codesign >/dev/null
    # lets codesign use the key without a prompt
    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$password" "$keychain" >/dev/null
    security lock-keychain "$keychain"
    echo "Created $name in $keychain"
}

if [[ -f "$keychain" ]]; then
    echo "Already set up: $keychain"
else
    create
fi
# codesign finds an identity only in a keychain on the search list, even when given the keychain
if ! security list-keychains -d user | grep -qF "\"$keychain\""; then
    listed=()
    while read -r path; do
        path=${path#\"}
        listed+=("${path%\"}")
    done < <(security list-keychains -d user)
    security list-keychains -d user -s "${listed[@]}" "$keychain"
fi
