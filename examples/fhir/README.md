# FHIR examples

Pipelines that move data between a FHIR endpoint and a DHIS2 instance. They are cross-boundary
twice over: the DHIS2 blocks come from the `dirigent-dhis2` pack, the HTTP, transform and
validate blocks from the runtime, and neither knows the other exists -- only an assembled
environment runs any of these at all.

Most of them read a `d2w fhir serve` facade, which publishes one DHIS2 instance as a FHIR
endpoint and takes captures back. Two are running on this machine at `http://localhost:8095`
and `http://localhost:8096`; `fhir_base` defaults to the first, so every read below works
against a real server. Where a general-purpose FHIR server is the point -- an Encounter, an
Observation, a Subscription, a `_lastUpdated` search, none of which the facade serves -- the
default is the public HAPI R4 sandbox at `https://hapi.fhir.org/baseR4` instead, and the
document's header says why.

No document here imports for real without being told to. Every write is a dry run:
`dryRun=true` on `/api/dataValueSets` and `importMode=VALIDATE` on `/api/tracker`. Those are
two spellings of one intention on two endpoints of the same server, and reaching for the wrong
one does not fail -- it imports.

## The mapping vocabulary

Three words carry the whole translation, and they are worth learning once.

**Subject.** Every capture is *about* something, and which something depends on the form.
An aggregate or event form is answered for a place, so its `subject` is a literal
`Reference(Location/<orgUnitUid>)` and the DHIS2 org unit is read straight out of it. A tracker
form is answered about a person, so its `subject` is a *logical* reference -- `subject.type`
`Patient` and `subject.identifier` under `http://dhis2.org/fhir/id/tracked-entity`, with no
`reference` at all -- and the org unit rides on a `D2OrganisationUnit` extension instead. Two
shapes, one field, and mixing them up is the first thing a facade refuses.

**Capture.** The capture pair is `Questionnaire` and `QuestionnaireResponse`. A `Questionnaire`
is a form *definition* generated from DHIS2 metadata: one per aggregate data set, event program,
tracker program, program stage, or tracked entity type. A `QuestionnaireResponse` is one
*submission* against it, answering item by item on the same `linkId`s. Those linkIds are DHIS2
uids -- a plain one is a data element, and a dotted one, `<dataElement>.<categoryOptionCombo>`,
is a single disaggregated cell -- which is what makes a response readable back into DHIS2
without consulting the form. Everything DHIS2 has and FHIR has no field for rides as a named
extension: `D2Period` carries the ISO period, `D2AttributeOptionCombo` the attribute option
combo, `D2TrackerEnrollment` the enrollment. A capture reaches the facade one resource per
`POST /QuestionnaireResponse`; there is no batch, and nothing reaches DHIS2 at capture time --
the facade holds a receipt whose lifecycle moves `received` to `forwarded` or `rejected`.

**ConceptMap.** A published, versioned, addressable translation between two code systems. The
facade emits one per DHIS2 option set, with two groups distinguished by `group.target`: one to
the DHIS2 option uid, always complete, and one to the DHIS2 option code, only where an option
has one. Fetching the map at run time instead of writing a lookup into a document is the
difference between a mapping that can drift and one that cannot: an option added to a DHIS2
option set is in the regenerated map, and the pipeline that reads it needs no edit.

## Pipelines

| File | What it teaches |
| --- | --- |
| [fhir-capture-bundle-to-data-values.yaml](fhir-capture-bundle-to-data-values.yaml) | The capture pair end to end: a page of `QuestionnaireResponse` captures pulled off the facade, translated to `/api/dataValueSets`, gated on the pack's `dhis2-uid` and `dhis2-period` formats, rehearsed and then imported. |
| [fhir-questionnaire-response-to-data-values.yaml](fhir-questionnaire-response-to-data-values.yaml) | The general case, where a `linkId` is a form designer's name rather than a DHIS2 uid: an explicit lookup in params, and every unmapped answer counted rather than dropped in silence. |
| [fhir-patient-to-tracked-entity.yaml](fhir-patient-to-tracked-entity.yaml) | The `Patient` register searched by identifier and folded into an `/api/tracker` registration -- and why the write is an `http.request` on the `dhis2` connection, because `dhis2.tracker` reads and does not write. |
| [fhir-encounter-to-event.yaml](fhir-encounter-to-event.yaml) | Cardinalities that do not line up: one `Encounter` plus every `Observation` naming it, folded into the single program stage event DHIS2 wants, with the LOINC codes mapped and the rest reported. |
| [fhir-conceptmap-driven-mapping.yaml](fhir-conceptmap-driven-mapping.yaml) | The mapping fetched rather than written: a `ConceptMap` flattened into a lookup at run time, applied to coded answers, with `equivalence` honoured so an inexact match is reported instead of imported. |
| [fhir-measure-report-to-analytics-check.yaml](fhir-measure-report-to-analytics-check.yaml) | A reconciliation that writes nothing: a `MeasureReport` held against `dhis2.analytics_query` for the same period and org unit, and the gap delivered by `webhook.post` whether or not there is one. |
| [dhis2-to-fhir-observations.yaml](dhis2-to-fhir-observations.yaml) | The outbound direction: a data value set published as a transaction `Bundle` of `Observation`s, each a conditional update keyed on the aggregate cell's natural key so republishing updates rather than duplicates. |
| [fhir-subscription-webhook-to-dhis2.yaml](fhir-subscription-webhook-to-dhis2.yaml) | The subscription contract -- `criteria`, `channel.type`, `channel.endpoint`, and what `channel.payload` decides -- landing on a webhook whose payload mapping is strict enough that no caller can reach a parameter it does not name. |
| [fhir-nightly-window-sync.yaml](fhir-nightly-window-sync.yaml) | The interval a firing covers rather than the moment it fired at: a half-open `_lastUpdated` range, a fan-out per resource type under `items: continue`, and a join under `rule: all_done` that says what it did not reach. |

## Running them

```bash
dg run --local examples/fhir/fhir-capture-bundle-to-data-values.yaml
dg run --local examples/fhir/fhir-conceptmap-driven-mapping.yaml \
  -p target_system=http://dhis2.org/fhir/id/option-code
```

One of them reads the window its firing covers, which no document declares and only a run
carries, so an ad hoc run has to say which interval it is for:

```bash
dg run --local examples/fhir/fhir-nightly-window-sync.yaml --window 2026-09-01..2026-09-02
```
