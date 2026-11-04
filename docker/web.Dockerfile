# syntax=docker/dockerfile:1.6
# Build context: repository root. Produces an nginx image serving one Angular
# front end, the WebAssembly engine and a same-origin proxy to the API and broker.
#   APP=web       the ledger client (default)
#   APP=diorama   the 3D client; needs web/projects/diorama/public/art from tools/zeroad/bake.sh

FROM rust:1-slim-bookworm AS wasm
RUN rustup target add wasm32-unknown-unknown
# Must equal the wasm-bindgen version pinned in engine/crates/ovian-wasm/Cargo.toml.
RUN --mount=type=cache,target=/usr/local/cargo/registry cargo install wasm-bindgen-cli --version 0.2.95 --locked
WORKDIR /build
COPY engine engine
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/build/engine/target \
    cd engine && cargo build -p ovian-wasm --release --target wasm32-unknown-unknown \
 && wasm-bindgen --target web --out-dir /out --out-name ovian_engine target/wasm32-unknown-unknown/release/ovian_wasm.wasm

FROM node:22-bookworm-slim AS web
ARG APP=web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY web ./
COPY --from=wasm /out public/engine
RUN if [ "$APP" = diorama ] && [ ! -f projects/diorama/public/art/manifest.json ]; then \
      echo "0 A.D. art missing: run tools/zeroad/bake.sh before building the diorama image" >&2; exit 1; fi \
 && npx ng build "$APP" --configuration production && mv "dist/$APP/browser" /site

FROM nginx:1.27-alpine
COPY docker/web/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker/web/40-ovian-config.sh /docker-entrypoint.d/40-ovian-config.sh
COPY --from=web /site /usr/share/nginx/html
ENV OVIAN_API_UPSTREAM=http://server:8000 OVIAN_MQTT_UPSTREAM=http://broker:9001 \
    OVIAN_PUBLIC_API_URL= OVIAN_PUBLIC_MQTT_URL= OVIAN_DEFAULT_SKIN=parchment OVIAN_SKINS=parchment,nightwatch,aegean \
    OVIAN_LEDGER_URL= OVIAN_DIORAMA_URL=
EXPOSE 80
