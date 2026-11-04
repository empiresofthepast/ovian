# Builds the engine as a WebAssembly ES module (wasm-bindgen --target web).
#   docker build -f docker/wasm.Dockerfile -o web/src/engine-wasm .
FROM rust:1-slim-bookworm AS build
RUN rustup target add wasm32-unknown-unknown
# Must equal the wasm-bindgen version pinned in engine/crates/ovian-wasm/Cargo.toml.
RUN --mount=type=cache,target=/usr/local/cargo/registry cargo install wasm-bindgen-cli --version 0.2.95 --locked
WORKDIR /build
COPY engine engine
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/build/engine/target \
    cd engine && cargo build -p ovian-wasm --release --target wasm32-unknown-unknown \
 && wasm-bindgen --target web --out-dir /out --out-name ovian_engine \
      target/wasm32-unknown-unknown/release/ovian_wasm.wasm

FROM scratch
COPY --from=build /out /
