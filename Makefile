# The integration control center. `make test` assembles the ecosystem and reports one green/red.

UV ?= uv

#: The batteries-included image and the stack that runs it. The stack lives in infra/ but its
#: paths resolve at the repository root, so compose is always given that project directory.
IMAGE ?= dirigent-full:local
COMPOSE ?= docker compose --project-directory . -f infra/compose.yaml

.PHONY: test sync lock clone lint clean image up down

# Assemble and run everything: clone the packs, run each pack's own tests and examples
# against the assembled environment, validate the cross-boundary examples, and run the
# integration's own tests. One command, one result.
test: sync
	$(UV) run python scripts/run_integration.py

# Install the assembled runtime and dev tooling into .venv, from a lock resolved at the tips:
# the lock is not committed, so a stale one would test an old ecosystem.
sync: lock
	$(UV) sync

# Resolve the ecosystem's branch tips into uv.lock. The lock is not committed -- the sources
# ride main, so it is resolved fresh -- and it is what both the environment and the image
# are built from.
lock:
	$(UV) lock --upgrade

# Clone (or refresh) every pack named in ecosystem.yaml into checkouts/, without running.
clone: sync
	$(UV) run python scripts/run_integration.py --clone-only

# Lint and format-check the integration's own sources.
lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

# Build dirigent-full from this repo's pyproject and a freshly resolved lock. The components
# are public, so GITHUB_TOKEN is optional: unset, the one gh is logged in with is used if gh is
# there, and otherwise it stays empty. It reaches the build as a BuildKit secret.
image: lock
	GITHUB_TOKEN="$${GITHUB_TOKEN:-$$(gh auth token 2>/dev/null || true)}" \
	  DOCKER_BUILDKIT=1 docker build \
	  --secret id=github_token,env=GITHUB_TOKEN \
	  -f infra/Dockerfile -t $(IMAGE) .

# Bring the stack up: postgres, the migration, the server and a worker, seeding the
# cross-boundary examples. Needs a .env; see .env.example.
up:
	GITHUB_TOKEN="$${GITHUB_TOKEN:-$$(gh auth token 2>/dev/null || true)}" $(COMPOSE) up --build

# Remove the stack: containers, volumes and orphans.
down:
	$(COMPOSE) down --volumes --remove-orphans

# Remove the cloned packs and the environment.
clean:
	rm -rf checkouts .venv
