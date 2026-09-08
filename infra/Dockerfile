# dirigent-full: the batteries-included image. Dirigent plus every official pack the manifest
# names, plus the web UI, assembled from this repo's pyproject.toml and uv.lock -- the only
# assembly whose git sources resolve while the packages are not yet on PyPI.
#
# The components are fetched over public HTTPS, so the build needs no credentials. A private
# component repository is covered by an optional `github_token` BuildKit secret: when it is
# supplied, every stage that reaches github.com rewrites https://github.com/ to carry it for
# the duration of one RUN, through GIT_CONFIG_* in that RUN's environment, so the token never
# lands in a layer or a file. Omitting the secret is supported and skips the rewrite.
#
#   docker build -f infra/Dockerfile -t dirigent-full:local .
#   docker build --secret id=github_token,env=GITHUB_TOKEN -f infra/Dockerfile -t dirigent-full:local .

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca AS lock

WORKDIR /lock
COPY uv.lock scripts/dirigent_rev.py ./
RUN python dirigent_rev.py uv.lock > /dirigent-rev


# dirigent-server installed from git carries no bundle -- its static/ directory is gitignored
# in dirigent -- so the UI is built here, from the same commit the lock installed.
FROM oven/bun:1.4-alpine@sha256:d888c0ae6c86d7866ff10c5aafdd9077b36aee6455b33dd270fb93c0dd5cef6f AS frontend

RUN apk add --no-cache git

WORKDIR /src
COPY --from=lock /dirigent-rev /dirigent-rev
RUN --mount=type=secret,id=github_token \
    if [ -s /run/secrets/github_token ]; then \
      export GIT_CONFIG_COUNT=1 \
        GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/github_token)@github.com/.insteadOf" \
        GIT_CONFIG_VALUE_0="https://github.com/"; \
    fi \
    && git init --quiet dirigent \
    && git -C dirigent remote add origin https://github.com/winterop-com/dirigent \
    && git -C dirigent fetch --quiet --depth 1 origin "$(cat /dirigent-rev)" \
    && git -C dirigent checkout --quiet FETCH_HEAD

WORKDIR /src/dirigent/packages/dirigent-server/frontend
RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun install --frozen-lockfile
RUN bun run build


FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# uv shells out to git to resolve the component packages, and this base image has no git.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=github_token \
    if [ -s /run/secrets/github_token ]; then \
      export GIT_CONFIG_COUNT=1 \
        GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/github_token)@github.com/.insteadOf" \
        GIT_CONFIG_VALUE_0="https://github.com/"; \
    fi \
    && uv sync --locked --no-dev

# dirigent_server.ui.static_dir serves this directory out of the installed package.
COPY --from=frontend /src/dirigent/packages/dirigent-server/frontend/dist/ \
     /app/.venv/lib/python3.13/site-packages/dirigent_server/static/


# This stage mirrors the runtime stage of dirigent's infra/Dockerfile and must move with it:
# the same base digest, packages, uid, environment defaults, artifact directory and entrypoint.
FROM python:3.13-slim-bookworm@sha256:c45a22ea000adfd9cda29364bbe7edd23001ce5cc2ad15857cfbf7766943b9ca AS runtime

# The docker CLI, compose and buildx plugins, so the docker.compose.* and docker.build blocks
# have something to shell out to. The daemon itself is never in this image: these speak to a
# daemon named by DOCKER_HOST -- ideally the worker's own (a dind sidecar over tcp+TLS). Mounting
# the host's /var/run/docker.sock is the discouraged fallback; it grants this container root on
# the host. ca-certificates stays for TLS to a tcp daemon.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin docker-buildx-plugin \
    && apt-get purge -y curl gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# The uid is fixed so a mounted artifact volume has predictable ownership across hosts.
RUN groupadd --gid 1000 dirigent \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin dirigent

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DIRIGENT_HOST=0.0.0.0 \
    DIRIGENT_PORT=3333 \
    DIRIGENT_LOG_FORMAT=json \
    DIRIGENT_ARTIFACT_ROOT=file:///var/lib/dirigent/artifacts

WORKDIR /app
COPY --from=builder --chown=dirigent:dirigent /app /app

# Without this a worker fails at the first step of the first run rather than at start.
RUN mkdir -p /var/lib/dirigent/artifacts && chown -R dirigent:dirigent /var/lib/dirigent

USER dirigent
EXPOSE 3333

ENTRYPOINT ["dg"]
CMD ["server"]
