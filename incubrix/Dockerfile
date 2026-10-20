# IncuBrix editing engine - the HTTP service and the session runner.
#
#   docker compose up                 the API on :8080 with an S3 store (SeaweedFS)
#   docker compose run --rm test      every test: unit, integration, end to end
#
# Stages: `builder` compiles (with whisper.cpp for speech recognition),
# `test` runs the suite, `runtime` is the slim image that serves.

FROM rust:1-bookworm AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
        cmake clang libclang-dev ffmpeg python3-pip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN cargo build --release -p incubrix-api --features whisper -p incubrix-cli \
    && cp target/release/incubrix-api target/release/incubrix /usr/local/bin/

# The test stage reuses the build: `docker compose run --rm test`.
FROM builder AS test
# The official OpenTimelineIO reader, for the export test.
RUN pip3 install --break-system-packages opentimelineio==0.18.1
ENV NLU_PROVIDER=rules
CMD ["sh", "-c", "cargo test --release --workspace && incubrix check fixtures/sessions && cargo test --release -p incubrix-api --test live -- --nocapture"]

FROM debian:bookworm-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
# Speech recognition model: whisper.cpp tiny.en (MIT), 75 MB.
ADD https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin /models/ggml-tiny.en.bin
COPY --from=builder /usr/local/bin/incubrix-api /usr/local/bin/incubrix /usr/local/bin/
ENV API_BIND=0.0.0.0:8080 \
    DATA_DIR=/data \
    WHISPER_MODEL=/models/ggml-tiny.en.bin \
    NLU_PROVIDER=rules
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=6 CMD curl -fs http://localhost:8080/ready || exit 1
CMD ["incubrix-api"]
