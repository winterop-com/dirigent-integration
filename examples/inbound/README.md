# Inbound examples

Eight pipelines going the same direction: an outside system, a transform, DHIS2. They are
authored here rather than in a pack because each one spans several -- the http, storage,
transform and parquet blocks the runtime contributes, feeding the blocks `dirigent-dhis2`
contributes -- and no single pack can hold, or test, a pipeline that needs them all.

Every one of them:

- names every block it uses under `requires: blocks:`, so an environment missing one refuses
  the document rather than failing halfway through a run;
- carries its DHIS2 connection in the document, pointed at the public play server, so
  `dg run --local <file>` works with nothing applied and nothing configured;
- imports with `dry_run` defaulting to true. The play server is shared: leave it that way
  there, and turn it off against an instance of your own;
- uses ids that exist on the demo. `WUg3MYWQ7pt` (Total Population, yearly) and
  `x0PshcPLSk1` / `wZqi8EXN5x4` (PMTCT monthly) at Ngelehun CHC, `DiszpKrYNg8`, are the
  defaults, because those are elements the demo will actually accept values for.

The two that read object storage need an `s3` connection bound to the scheme as an instance
setting (`storage_connections: {s3: <code>}`); the rest need only a network.

| Example | What it teaches |
| --- | --- |
| [`http-json-to-data-values.yaml`](http-json-to-data-values.yaml) | The shortest inbound path: pull a public JSON API, reshape it, gate it on DHIS2's own id and period formats, import it as a dry run. |
| [`csv-drop-to-data-values.yaml`](csv-drop-to-data-values.yaml) | The file drop: wait for a csv to land in a bucket, decode it, translate the sender's codes to uids through a lookup, drop the rows that carry no measurement. |
| [`webhook-payload-to-tracker-event.yaml`](webhook-payload-to-tracker-event.yaml) | Push instead of poll: a webhook maps one posted encounter onto parameters, and that mapping is the whole security boundary. |
| [`parquet-lakehouse-to-dhis2.yaml`](parquet-lakehouse-to-dhis2.yaml) | Grain: a parquet table of encounter-level rows reduced to the figures DHIS2 stores, then a completeness sensor that observes rather than registers. |
| [`fhir-observations-to-data-values.yaml`](fhir-observations-to-data-values.yaml) | Two standards meeting: LOINC codes mapped onto data elements, instants truncated to periods, and the org unit the payload cannot supply. |
| [`weekly-window-pull-and-import.yaml`](weekly-window-pull-and-import.yaml) | The window: a schedule whose runs pull the week that closed, `${run.window.start}` to `${run.window.end}`, so a late run and a backfill read the same week. |
| [`fan-out-per-facility-import.yaml`](fan-out-per-facility-import.yaml) | One call per facility with `items: continue`, why the fan converges before the import, and a reconciliation of asked-for against answered. |
| [`outside-to-dhis2-with-checks.yaml`](outside-to-dhis2-with-checks.yaml) | Every guard at once: a readiness sensor, a schema on what arrived, a schema on what was built, a rehearsed import, and the real one behind it. |
