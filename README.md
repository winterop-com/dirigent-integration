# dirigent-integration

The control center for the dirigent plugin ecosystem. This is the one place aware of every
official pack at once -- it assembles them into a single environment and runs everyone
together to prove they still compose.

## The principle it protects

dirigent-core knows nothing about any pack. Every adapter, DHIS2 today and more to come --
anything the core is deliberately ignorant of -- lives only in its own repository and
self-tests there, against nothing but its own dependencies. The integration is the only place
the whole set is installed side by side, so it is the only place that can prove they still
compose: that every pack's blocks land in one catalog without colliding, that every pack's
examples still validate against that merged catalog, and that a pipeline spanning two packs is
runnable at all.

## What is here

- **`ecosystem.yaml`** -- the manifest: every component and the ref it tracks, the source of
  truth for what gets assembled. `dirigent` (the runtime monorepo) is `role: runtime`,
  installed as dependencies and never cloned; each adapter is `role: pack`, cloned and
  self-tested here. `dirigent-dhis2` is the first; a future pack becomes real with a single
  entry.
- **`pyproject.toml`** -- the assembled runtime: every dirigent runtime package plus every
  pack, wired through `[tool.uv.sources]` as git dependencies on `branch = main`, unpinned, so
  the integration always assembles the latest ecosystem.
- **`scripts/run_integration.py`** -- the runner. It reads the manifest, clones each pack, and
  runs everything against the assembled environment. It is generic: it iterates the packs the
  manifest names and has no per-pack knowledge.
- **`infra/`** -- the batteries-included image and the stack that runs it: `Dockerfile` builds
  dirigent plus every pack plus the web UI, `compose.yaml` runs it against postgres.
- **`examples/`** -- cross-boundary example pipelines, authored here because they span more
  than one pack and belong to none.
- **`tests/`** -- the integration's own tests: the merged catalog is coherent, and the
  cross-boundary examples validate against it.

## Running it locally

```sh
make test
```

One target, one green or red:

1. clone every `role: pack` in `ecosystem.yaml` into `checkouts/` (gitignored), at its ref;
2. run each pack's own pytest suite against the assembled environment;
3. validate each pack's own examples against the merged catalog;
4. validate the cross-boundary examples against the merged catalog;
5. run the integration's own tests.

A pack whose checkout is already present is reused. Other targets: `make sync`, `make clone`,
`make lint`, `make clean`.

## The cross-boundary examples

Pipelines that no single pack owns because they span several. Today they exercise the first
pack, DHIS2, across the built-in storage and transform packs; as more adapters land,
cross-boundary pipelines across them are authored here the same way.

- **`examples/dhis2-export-to-s3.yaml`** -- a `dhis2.data_value_set_export` streaming to the
  `s3://` scheme, then a `storage.copy` archiving it.
- **`examples/dhis2-values-to-parquet.yaml`** -- the same export feeding `convert.arrow`,
  re-encoding to parquet in `s3://`: three packs in one pipeline.
- **`examples/dhis2-values-per-org-unit-to-parquet.yaml`** -- that export fanned out over a list
  of organisation units, one parquet object each, joined back into a manifest of what landed.
- **`examples/dhis2-analytics-to-csv-report.yaml`** -- a `dhis2.analytics_query` grid flattened
  into rows, written to `s3://` as csv, and announced with a `webhook.post` summary.
- **`examples/parquet-to-dhis2-import.yaml`** -- the return leg: a parquet drop waited on with
  `storage.exists`, decoded, gated on a carried schema, then imported into DHIS2.
- **`examples/dhis2-tracker-weekly-window.yaml`** -- a windowed weekly schedule driving
  `dhis2.tracker` over the week that just closed, archived as ndjson and parquet in `s3://`.
- **`examples/dhis2-metadata-snapshot.yaml`** -- a metadata snapshot written to `s3://`, then
  `pipeline.run` of `dhis2-export-to-s3`: composition across the corpus itself.

## FHIR examples

`examples/fhir/` is a shelf of its own: nine pipelines moving data between a FHIR endpoint and
DHIS2, in both directions. They are cross-boundary twice over -- the DHIS2 blocks come from the
`dirigent-dhis2` pack and the HTTP, transform and validate blocks from the runtime, and neither
knows the other exists.

Most of them read a `d2w fhir serve` facade, which publishes one DHIS2 instance as a FHIR
endpoint and takes captures back; where a general-purpose FHIR server is the point -- an
`Encounter`, an `Observation`, a `Subscription`, a `_lastUpdated` search, none of which that
facade serves -- the default is a public HAPI R4 sandbox instead, and the document's header
says so. Every write is a dry run: `dryRun=true` on `/api/dataValueSets`, `importMode=VALIDATE`
on `/api/tracker`.

[`examples/fhir/README.md`](examples/fhir/README.md) has the one-line table and the mapping
vocabulary the shelf is built on -- subject, capture, ConceptMap.

- **`examples/fhir/fhir-capture-bundle-to-data-values.yaml`** -- the capture pair end to end: a page
  of captures pulled off the facade, translated, gated on the pack's own id and period formats,
  rehearsed and imported.
- **`examples/fhir/fhir-questionnaire-response-to-data-values.yaml`** -- the general case, where a
  `linkId` is a form designer's name and the lookup is the integration.
- **`examples/fhir/fhir-patient-to-tracked-entity.yaml`** -- the `Patient` register folded into an
  `/api/tracker` registration, posted by `http.request` because `dhis2.tracker` only reads.
- **`examples/fhir/fhir-encounter-to-event.yaml`** -- one `Encounter` and its `Observation`s folded
  into the single program stage event DHIS2 wants.
- **`examples/fhir/fhir-conceptmap-driven-mapping.yaml`** -- the mapping fetched from the server at
  run time rather than written into the document.
- **`examples/fhir/fhir-measure-report-to-analytics-check.yaml`** -- a `MeasureReport` held against
  `dhis2.analytics_query` for the same period, and the gap delivered by `webhook.post`.
- **`examples/fhir/dhis2-to-fhir-observations.yaml`** -- the outbound leg: a data value set
  published as a transaction `Bundle` of conditionally-updated `Observation`s.
- **`examples/fhir/fhir-subscription-webhook-to-dhis2.yaml`** -- the subscription contract,
  landing on a webhook whose payload mapping no caller can reach past.
- **`examples/fhir/fhir-nightly-window-sync.yaml`** -- a half-open `_lastUpdated` window, a
  fan-out per resource type under `items: continue`, and a join that says what it missed.

## Inbound examples

`examples/inbound/` is a shelf of eight pipelines going one direction -- an outside system, a
transform, DHIS2 -- teaching the shapes an inbound integration actually takes: a public JSON
API, a csv dropped in a bucket, a pushed webhook, a parquet table from a lakehouse, a FHIR
Observation feed, a windowed weekly pull, a fan-out across facilities, and the defensive
version with every guard on. Each names every block it needs, carries its DHIS2 connection
pointed at the public play server, and imports as a dry run by default, so
`dg run --local examples/inbound/<file>` works with nothing set up.
`examples/inbound/README.md` lists them one line each.

## The batteries-included image

`dirigent-full` is dirigent with every official pack the manifest names, plus the web UI, in
one image, built here with `make image` and not published. The published image is the core
one, `ghcr.io/winterop-com/dirigent`, which carries no adapter: a deployment that wants a pack
builds one layer on it (dirigent's operations guide, "The image"), and `dg init --template
compose` writes that Dockerfile. This repository builds the assembled image because it is the
one place the whole set is already resolved, and the stack below runs it.

`infra/Dockerfile` builds it from this repository's `pyproject.toml` and `uv.lock` in three
stages: a bun stage that builds the UI bundle from the very dirigent commit the lock resolved
(`scripts/dirigent_rev.py` reads it out of the lock -- dirigent-server installed from git
carries no bundle, because its `static/` is gitignored there), a uv stage that runs
`uv sync --locked --no-dev`, and a runtime stage that mirrors the runtime stage of dirigent's
own `infra/Dockerfile` and must move with it.

The build clones the components over public HTTPS and needs no credentials. A component
repository that is private needs a GitHub read token instead; it goes in as a BuildKit secret
and is exposed to git only inside the one `RUN` that needs it, so it never lands in a layer or
a config file.

```sh
make image                             # public components, no token
export GITHUB_TOKEN=$(gh auth token)   # only if a component repository is private
```

### Running the stack

```sh
cp .env.example .env      # set DIRIGENT_SECRET_KEY and DIRIGENT_BOOTSTRAP_ADMIN_PASSWORD
make up
```

Four services -- postgres, a one-shot migration, the server and a worker -- with this
repository's `examples/` mounted as the apply directory, so the cross-boundary pipelines are
seeded at boot. The UI is on http://localhost:3333; `make down` removes it, volumes and all.

## CI

The assembled check is expensive -- clone every pack, install the whole runtime, run every
suite -- so it is deliberately infrequent. Per-commit safety belongs to each repository's own
CI: `dirigent` tests itself on its pushes, each pack tests itself on its own. The integration
is the integration truth, caught once a day. `.github/workflows/ci.yaml` therefore triggers
only on **`schedule:`** (a nightly cron) and **`workflow_dispatch:`** (manual); it never runs
on push, which would turn one commit into a full-ecosystem rebuild. A lightweight
`.github/workflows/lint.yaml` runs on push so every commit still gets a status without
assembling anything.

`repository_dispatch` (type `component-released`) is kept as an optional, opt-in trigger for a
component's release or tag boundary only; nothing sends it today.

The components are public, so the git dependencies uv resolves and the pack clones the runner
makes need no credentials and the workflow needs no secret.

## Licence

Copyright (c) 2026 Morten Olav Hansen. All rights reserved. See [LICENSE](LICENSE).

The source is published for reference only: no licence to use, copy, modify or distribute it
is granted, and any use beyond reading requires written permission.
