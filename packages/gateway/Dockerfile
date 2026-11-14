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
# - abstract-logging (a fastify dependency) and onnxruntime-common ship no
#   licence file either; the image adds abstract-logging's MIT text (from
#   https://jsumners.mit-license.org, the licence its README names) and
#   onnxruntime's LICENSE, which covers onnxruntime-common, a package of
#   the same repository.
# - The runtime stage removes npm and corepack: the gateway and the
#   `nullpii` CLI run on node alone, and a package manager in the image
#   is only attack surface.
# - The base image is pinned by digest (node:22-slim) on each FROM line,
#   where Dependabot can bump it; bump it on purpose.
# - The GLiNER ONNX model is NOT baked into this image. The gateway loads
#   it on the first request that needs it, downloading it from Hugging
#   Face (about 1.2 GB) into /home/node/.cache/nullpii, a volume. Fetch it
#   beforehand with the nullpii CLI the image carries, in a container that
#   mounts the same volume:
#     node bin/nullpii.mjs prefetch --backend cpu
#   or set NULLPII_MODEL_DIR to a model directory you mount (see
#   examples/claude-code/).
# - /health answers as soon as the server listens; it does not wait for
#   the model.
#
# Build context: REPO ROOT (the gateway needs the `nullpii` core).
#
#   docker build -t nullpii-gateway:local -f packages/gateway/Dockerfile .

# ---------- builder ----------
FROM node:26-slim@sha256:36793bcbb160a6a16cede1e62b93f84e26b78a972a8a4c0b879c1c12f22761ec AS builder

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
# and Windows builds of onnxruntime-node (160 MB) are dropped, and the
# macOS, Windows and Android builds of tokenizers (about 40 MB): the
# image is Linux.
RUN npm pkg set \
      "dependencies.fastify=$(node -p "require('./package-lock.json').packages['node_modules/fastify'].version")" \
      "dependencies.onnxruntime-node=$(node -p "require('./package-lock.json').packages['node_modules/onnxruntime-node'].version")" \
 && npm pkg delete devDependencies.fastify devDependencies.onnxruntime-node \
 && npm prune --omit=dev --ignore-scripts --no-audit --no-fund \
 && rm -rf node_modules/onnxruntime-node/bin/napi-v*/darwin node_modules/onnxruntime-node/bin/napi-v*/win32 \
 && rm -f node_modules/tokenizers/tokenizers.darwin-*.node node_modules/tokenizers/tokenizers.win32-*.node node_modules/tokenizers/tokenizers.android-*.node

# ---------- runtime ----------
FROM node:26-slim@sha256:36793bcbb160a6a16cede1e62b93f84e26b78a972a8a4c0b879c1c12f22761ec AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NULLPII_HOST=0.0.0.0 \
    NULLPII_PORT=8787 \
    NULLPII_BACKEND=cpu \
    NULLPII_LOG_LEVEL=info

# Root nullpii artifacts, with the licence and notices they ship under, and
# its CLI (`node bin/nullpii.mjs prefetch` fills the model cache).
COPY --from=builder /app/package.json ./
COPY --from=builder /app/dist ./dist
COPY bin ./bin
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
COPY packages/gateway/third_party/onnxruntime/LICENSE ./node_modules/onnxruntime-common/LICENSE
COPY packages/gateway/third_party/abstract-logging/LICENSE ./node_modules/abstract-logging/LICENSE

# No package manager at run time (see the header).
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
      /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack

# Self-link so the gateway's `import 'nullpii'` resolves to the root
# package at runtime as well.
RUN mkdir -p node_modules && ln -snf .. node_modules/nullpii

# Run unprivileged. The model cache lives under its HOME; mount a volume
# there so the (~1.2 GB) FP32 model survives container restarts.
RUN mkdir -p /home/node/.cache/nullpii && chown -R node:node /home/node/.cache
USER node
VOLUME ["/home/node/.cache/nullpii"]

EXPOSE 8787

# Liveness only: the server listens within seconds of starting, model or not.
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.NULLPII_PORT||8787)+'/health').then(r=>{process.exit(r.ok?0:1)}).catch(()=>process.exit(1))"

CMD ["node", "packages/gateway/bin/nullpii-gateway.mjs"]
