# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
# SPDX-License-Identifier: Apache-2.0
#
# The @lbroth/nullpii-gateway image, multi-stage. Published as
# ghcr.io/lbroth/nullpii-gateway by .github/workflows/gateway-docker.yml.
#
# - Build stage compiles the `nullpii` core + the `@lbroth/nullpii-gateway`
#   package against pinned Node + npm.
# - No dependency install script runs: the build needs none, and
#   onnxruntime-node's would download its CUDA 12 provider from NuGet,
#   unverified, into a CPU-only image. The CPU runtime it needs ships in
#   the npm package itself (bin/napi-v6/linux/{x64,arm64}).
# - Runtime stage carries only the compiled output, the production
#   dependencies (the core's, plus fastify and onnxruntime-node at the
#   versions the lockfile pins), the LICENSE and NOTICE of nullpii and of
#   the gateway, and runs as `node`.
# - onnxruntime-node's npm package carries neither the licence nor the
#   third-party notices of the native library it ships. The image adds
#   both next to it, from packages/gateway/third_party/onnxruntime/:
#   LICENSE (MIT) and ThirdPartyNotices.txt, taken verbatim from
#   https://github.com/microsoft/onnxruntime at tag v1.30.0 (commit
#   f2c39fe2f838cf35ce7da92824f5a5e3ee6e88a7), the version the lockfile
#   pins. `npm run license-check` fails when the two versions drift.
# - The base image is pinned by digest (node:22-slim); bump it on purpose.
# - The GLiNER ONNX model is NOT baked into this image. On first boot
#   the engine fetches it from HuggingFace and caches it under the
#   `NULLPII_MODEL_DIR` volume (mount one in production — see
#   `examples/claude-code/docker-compose.yml`).
#
# Build context: REPO ROOT (the gateway needs the `nullpii` core).
#
#   docker build -t nullpii-gateway:local -f packages/gateway/Dockerfile .

# ---------- builder ----------
ARG NODE_IMAGE=node:22-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392

FROM ${NODE_IMAGE} AS builder

WORKDIR /app

# Manifests first so layer cache survives source edits.
COPY package.json package-lock.json tsconfig.base.json tsconfig.build.json biome.json ./
COPY tsconfig.json ./

RUN --mount=type=cache,target=/root/.npm \
    npm ci --ignore-scripts --no-audit --no-fund

# Root nullpii source.
COPY src ./src

# Gateway source.
COPY packages/gateway/package.json ./packages/gateway/
COPY packages/gateway/tsconfig.json ./packages/gateway/
COPY packages/gateway/src ./packages/gateway/src
COPY packages/gateway/bin ./packages/gateway/bin

# Build root → dist/.
RUN npm run build

# Self-link so `import 'nullpii'` resolves from any subpackage.
RUN mkdir -p node_modules && ln -snf .. node_modules/nullpii

# Build gateway → packages/gateway/dist/.
RUN cd packages/gateway && npx tsc -p tsconfig.json

# Production dependencies only, at the versions package-lock.json pins.
# The gateway's runtime also needs fastify and onnxruntime-node, which the
# root manifest lists as dev and peer dependencies: they are moved to
# `dependencies` (lockfile versions) before pruning, so the prune keeps
# them and every transitive dependency at its locked version. The macOS
# and Windows builds of onnxruntime-node (160 MB) are dropped: the image
# is Linux.
RUN npm pkg set \
      "dependencies.fastify=$(node -p "require('./package-lock.json').packages['node_modules/fastify'].version")" \
      "dependencies.onnxruntime-node=$(node -p "require('./package-lock.json').packages['node_modules/onnxruntime-node'].version")" \
 && npm pkg delete devDependencies.fastify devDependencies.onnxruntime-node \
 && npm prune --omit=dev --ignore-scripts --no-audit --no-fund \
 && rm -rf node_modules/onnxruntime-node/bin/napi-v*/darwin node_modules/onnxruntime-node/bin/napi-v*/win32

# ---------- runtime ----------
FROM ${NODE_IMAGE} AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NULLPII_HOST=0.0.0.0 \
    NULLPII_PORT=8787 \
    NULLPII_BACKEND=cpu \
    NULLPII_LOG_LEVEL=info

# Root nullpii artifacts, with the licence and notices they ship under.
COPY --from=builder /app/package.json ./
COPY --from=builder /app/dist ./dist
COPY LICENSE NOTICE ./

# Gateway artifacts, with the gateway's own licence and notices.
COPY --from=builder /app/packages/gateway/package.json ./packages/gateway/
COPY --from=builder /app/packages/gateway/dist ./packages/gateway/dist
COPY --from=builder /app/packages/gateway/bin ./packages/gateway/bin
COPY packages/gateway/LICENSE packages/gateway/NOTICE ./packages/gateway/

# Production node_modules — Fastify + ORT prebuilds + transitive deps.
COPY --from=builder /app/node_modules ./node_modules

# onnxruntime's licence and third-party notices, next to the native
# library they cover (see the header).
COPY packages/gateway/third_party/onnxruntime/ ./node_modules/onnxruntime-node/

# Self-link so the gateway's `import 'nullpii'` resolves to the root
# package at runtime as well.
RUN mkdir -p node_modules && ln -snf .. node_modules/nullpii

# Run unprivileged. The model cache lives under its HOME; mount a volume
# there so the (~1.2 GB) FP32 model survives container restarts.
RUN mkdir -p /home/node/.cache/nullpii && chown -R node:node /home/node/.cache
USER node
VOLUME ["/home/node/.cache/nullpii"]

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=3s --start-period=120s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.NULLPII_PORT||8787)+'/health').then(r=>{process.exit(r.ok?0:1)}).catch(()=>process.exit(1))"

CMD ["node", "packages/gateway/bin/nullpii-gateway.mjs"]
