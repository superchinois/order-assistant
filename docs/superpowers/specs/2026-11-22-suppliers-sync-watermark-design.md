# Suppliers page — validation-date sync with a persisted watermark

Date: 2026-11-22
Status: awaiting approval (revision 2 — supersedes the picking-id cursor design)
Size: small feature (one util module, one page, tests, two bugfixes)

## Intent and why

The **Suppliers** page (`app/reports/suppliers.py`) appends Odoo stock movements to
MongoDB with *Mettre à jour mouvements*. Today that button fails once the newest
document is older than 8 weeks (`IndexError: list index out of range` from
`CacheDao.last_record()`), the page itself stops rendering for the same reason, and —
independently of the crash — some deliveries never reach MongoDB at all.

Three defects were confirmed by investigation and reproduction:

1. **Window-derived cursor.** `last_record()` (`app/utils/mongo_utils.py:160`) picks the
   last row of a rolling 8-week query (`$match: docdate > now - 8 weeks`) and indexes
   `[0]` unconditionally. Empty aggregation → `IndexError`; the header calls the same
   function, so the page dies, not just the button.
2. **Empty insert.** `importFromData` calls `insert_many` unconditionally; `pymongo`
   raises `InvalidOperation("No operations to execute")` for an empty batch.
3. **Picking-id cursor conflation.** The resume point is a *picking* id (`docnum`) chosen
   by max *move* id (`smid`), then fed to `stock.picking.id >`. Wrong-direction only, but
   self-perpetuating: duplicates have the same `smid`, so the cursor never advances and
   each press re-imports the same range. Duplicated `quantity` halves `dcover` and
   inflates `7d`/`14d`, so the app over-orders.

And the reason the cursor itself has to go — **split deliveries**. A backorder picking is
*created* at the moment of the partial validation, so it takes a picking id from that
moment, while its remainder ships later. It is filtered twice: at creation because
`state != 'done'`, at validation because its id is below the cursor. Such a picking can
never be imported, so the outgoing quantity of the second delivery is missing from
MongoDB, and from every number built on it.

The one path that would catch it selects by `date_done` instead of id — and it has never
run. `fetch_data_from_odoo`'s date branch (`app/utils/function_utils.py:381-383`) has two
bugs, verified against a stub API: `_map(get_values([...]), query)` maps over the dict's
*keys* (`TypeError: string indices must be integers`), and
`get_stock_moves_from(from_client_location, start, end)` omits the `odoo_api` argument
that `get_stock_moves_from(odoo_api, location_id, start_date, end_date_excluded)`
requires.

## Goals

- The Suppliers page always renders, whatever state `raw-data` is in.
- The button never raises on: empty collection, empty slice, nothing new, large backlog.
- Deliveries are imported **when they are validated**, so a split delivery's remainder is
  never skipped, however old its picking id.
- One press imports a bounded volume; a long gap is worked through over several presses,
  oldest first, with no silent hole.
- Re-running an import cannot duplicate rows, so a rewind/repair is safe and repeatable.
- The operator can re-synchronise a chosen past window from the page.

## Non-goals

- Importing history older than the pivot anchor. Bootstrap and repair start at
  `getStartDateOfPeriod(now, 10)`; older movements are deliberately left out of sync.
- A server-side batch limit. `odoo_client.API.extract_from_odoo` forwards only
  `fields` + `context` to `search_read` (verified at the pinned commit), so there is no
  `limit` to pass. Slicing by date is the only bound available.
- Changing what the page displays, the 10-week pivot, or the supplier list.

## Anti-goals (would count as failure)

- Silently advancing a watermark past movements that were never written.
- A catch-up that cannot terminate because a slice is empty.
- A repair that duplicates the healthy rows while adding the missing ones.

## Approaches considered

- **A — validation-date sync with a persisted watermark (chosen).** No cursor derived
  from movements. A `sync-state` document stores the last `date_done` covered; each press
  fetches `stock.picking` by `date_done` over bounded slices and upserts on `smid`.
- **B — picking-id cursor, corrected.** Sort by `docnum` instead of `smid`, add a
  collection-wide "last record" and a date-slice catch-up for stale starts. Fixes the
  crash and the duplicates, but keeps "validation order == creation order", which is
  exactly what split deliveries violate. Rejected after the backorder case was raised.
- **C — date windows with no stored state**, deriving the start from `max(docdate)`.
  Rejected: `docdate` comes from the move date, not `date_done`, so the anchor cannot be
  trusted to reveal a hole — and a hole is the thing we must detect.

## Design

### `app/utils/function_utils.py` — make the date branch work

```python
elif 'start_date' in query:
    start, end = query['start_date'], query['end_date']
    stock_moves = get_stock_moves_from(odoo_api, from_client_location, start, end)
```

`get_stock_moves_from` already filters `state = done`, `date_done >= start`,
`date_done < end`, and pickings touching location 5, so slices are adjacent and
non-overlapping by construction. `get_stock_pickings_after_id` stays in the module but is
no longer on the sync path.

### `app/utils/mongo_utils.py`

1. `last_movement_pipeline()` — replaces `last_docnum(sorting_id, date_format, from_date)`.
   No `$match`; projects `docnum`, `docdate`, `timestamp`; `$sort {docdate: -1}`,
   `$limit 1`. Display only.
2. `CacheDao.last_record()` — returns the record (`_id` stripped) or `None`. Never indexes
   an empty list. `MongoConfig.sorting_id` / `CacheDao._sorting_id` are removed: with no
   id cursor there is no sort key to configure.
3. `CacheDao.importFromData(data)` — returns `0` for an empty iterable; otherwise
   `bulk_write([ReplaceOne({'smid': …}, doc, upsert=True), …])` and returns upserted +
   modified. This is what makes slices, retries and repairs idempotent.
4. `CacheDao.get_sync_state()` / `set_sync_state(watermark)` — a `sync-state` collection,
   one document `{'_id': 'raw-data', 'watermark': <naive UTC datetime>, 'updated_at': …}`.
   Separate collection so `raw-data` stays purely movements. `set_sync_state` never moves
   the watermark backwards (`max(old, new)`), so a rewind does not rewind progress.
5. `CacheDao.ensure_indexes()` — best-effort `create_index` on `smid` and `docdate`
   (non-unique), called from `init_app`, failures swallowed so the page still renders. A
   **unique** index on `smid` stays an ops decision (it fails while historical duplicates
   exist).
6. `CacheDao.sync_from_odoo(fetch=None, since=None, max_moves=1000, slice_days=14,
   overlap_hours=6)` — the policy, out of the page so it is unit-testable without
   Streamlit; `fetch` defaults to the date branch of `fetch_data_from_odoo` and is
   injectable. Returns
   `SyncResult(mode, imported, window_start, window_end, remaining_days,
   watermark_before, watermark_after)`.

   ```
   now    = naive_utc_now()
   state  = get_sync_state()
   if since is not None:                       # operator rewind, from the page
       start, mode = min(since, now), 'heal'
   elif state is None:                        # bootstrap: pivot anchor, 10 weeks
       start, mode = getStartDateOfPeriod(now, 10), 'bootstrap'
   else:                                      # incremental
       start, mode = state.watermark - overlap, 'incremental'

   imported, cursor = 0, start
   while cursor < now and imported < max_moves:
       end = min(cursor + slice_days, now)
       imported += importFromData(fetch({'start_date': cursor, 'end_date': end}))
       cursor = end                           # advances even when the slice is empty
       set_sync_state(cursor)                 # only after the slice is written
   return SyncResult(mode, imported, start, cursor, (now - cursor).days, …)
   ```

   The watermark advances slice by slice, after that slice's rows are written, and never
   backwards. A failed write therefore leaves the watermark before the failed slice and
   the next press retries it; the `smid` upsert makes the retry and the repair harmless.
   Backorders need no special case: their `date_done` is after the watermark no matter how
   old their picking id is.

### `app/reports/suppliers.py` — presentation only

- Header shows the last movement (`last_record()`, `never` when `None`) and the last sync
  (watermark).
- *Mettre à jour mouvements* callback stores `mongo_dao.sync_from_odoo()` in
  `st.session_state['sync_result']` (Streamlit discards output written inside an
  `on_click` callback) and the page body pops it and renders from `mode`:
  - `incremental` → "N mouvements importés (X → Y)." plus, when `remaining_days > 0`,
    "Il reste R jours — relancez."
  - `bootstrap` → "Premier import : N mouvements (X → Y)."
  - `heal` → "Re-synchronisation X → Y : N mouvements importés."
  - `no_new` → "Aucun nouveau mouvement depuis X."
- New control: a date input defaulting to the pivot anchor plus a
  *Re-synchroniser depuis cette date* button calling
  `sync_from_odoo(since=<date at 00:00 UTC>)`. This is both the bootstrap accelerator and
  the repair tool for backorders already missed; safe to repeat because of the upsert.

## Constraints

- No new dependency; `pymongo.ReplaceOne`/`bulk_write` are already present.
- Tests: `cd app && python -m unittest discover tests`, no network, no Mongo.
- The page script cannot be imported by tests (Streamlit calls at module level), hence the
  policy on the DAO.
- `date_done` is UTC; comparisons use a naive-UTC clock, not the Reunion-local
  `dt.datetime.now()` used for display elsewhere.

## Tests (written first, expected to fail)

`app/tests/test_sync_state.py`, with fake state/collection objects and an injectable
`fetch` backed by a fixture of pickings:

- `last_movement_pipeline` has no `$match`; `last_record()` → `None` on empty.
- `importFromData([])` → `0`, collection untouched; `importFromData(docs)` →
  `ReplaceOne({'smid': …}, upsert=True)`.
- **regression:** `fetch_data_from_odoo({'start_date', 'end_date'})` builds a
  `stock.picking` domain with `date_done` bounds (stub API); `{'picking_id': …}` still
  works.
- incremental: fetch receives `{'start_date': watermark - 6h, 'end_date': +14d}`, and the
  query dict never contains `picking_id`.
- bootstrap with no state starts at `getStartDateOfPeriod(now, 10)`.
- **split delivery:** a picking whose `docnum` is below the watermark but whose `date_done`
  falls in the window is imported (the backorder case).
- `heal` from a date earlier than the watermark imports, and the watermark never ends
  lower than it started.
- empty slice advances the watermark and terminates; `max_moves` cap stops early with
  `remaining_days > 0` and the watermark at the last completed slice end.
- a `fetch`/write raising mid-run leaves the watermark before the failed slice.

## Risks / operational notes

- Several presses for a long gap (14 days and `max_moves` per press). Deliberate: the only
  server-side bound available.
- `date_done` is UTC and independent of the display `docdate`, which comes from the move
  date converted to Reunion time. A delivery validated near midnight can therefore display
  on the neighbouring day. Pre-existing behaviour, out of scope, worth a follow-up check.
- `sync-state` is a new collection: the Mongo user needs to create it.
- Historical rows already missed stay missed unless the operator uses the rewind control;
  it defaults to the 10-week anchor and is idempotent.
- `docs/architecture.md`, `docs/pages.md`, `docs/configuration.md` get updated: watermark,
  `sync-state`, indexes, and the rewind control.

## Left to the builder

Implementation order, test layout, message wording, whether `remaining_days` is shown as a
day count or a press count, and whether `get_stock_pickings_after_id` is kept or deleted
now that the sync path no longer uses it.
