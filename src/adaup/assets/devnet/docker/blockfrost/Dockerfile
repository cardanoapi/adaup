# blockfrost-ryo, Blockfrost's own API server over db-sync, built from a pinned
# release commit. Blockfrost publishes amd64 images only, and not for every
# release, so the devnet builds it for whatever architecture docker runs on.
#
# The checkout is fetched by commit and checked against it, so a moved tag
# cannot change what is built. Dependencies come from the repository's
# yarn.lock (--immutable) through the yarn release it vendors.
ARG NODE_IMAGE=node:24-bookworm-slim

FROM ${NODE_IMAGE} AS build
ARG BLOCKFROST_RYO_REPO=https://github.com/blockfrost/blockfrost-backend-ryo.git
ARG BLOCKFROST_RYO_COMMIT=6d0000098ac865ebad3910732427f55bbb65fe9d

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN set -eux; \
    git init -q .; \
    git remote add origin "${BLOCKFROST_RYO_REPO}"; \
    git fetch -q --depth 1 origin "${BLOCKFROST_RYO_COMMIT}"; \
    git checkout -q FETCH_HEAD; \
    test "$(git rev-parse HEAD)" = "${BLOCKFROST_RYO_COMMIT}"; \
    rm -rf .git
RUN node .yarn/releases/yarn-3.6.3.cjs install --immutable \
 && node .yarn/releases/yarn-3.6.3.cjs build

FROM ${NODE_IMAGE}
WORKDIR /app
COPY --from=build /app/package.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/genesis ./genesis
ENV NODE_ENV=production
USER node
EXPOSE 3000
ENTRYPOINT ["node", "--max-http-header-size=32768", "dist/server.js"]
