# MasterV storage

Run `.venv/bin/python MasterV.py` to fetch all city listing pages and then
fetch details only for records whose `DataDeliveryFrom` is not null (including zero). Data goes directly
from the API into SQLite; no intermediate response files are used.

Run `.venv/bin/python masterv_rebuild.py` for a clean rebuild. It builds
`data/masterv_rebuild.db`, checks integrity and coverage, backs up the active
database to `data/backups/`, and replaces `data/masterv.db` only on success.
If interrupted, use `.venv/bin/python masterv_rebuild.py --resume`.
Do not run concurrent writers while rebuilding.

## Tables

- `cities`: IDs 1–7 and their agreed English names.
- `projects`: city list records, keyed by source `DataId`; `compound_id` and
  `developer_id` retain the identifiers required for detail requests.
  `raw_json` preserves `DataDeliveryFrom` and all other source fields.
- `project_details`: one complete response per project, with fetch time.
  Preserves layouts, materials, developer profile and project document IDs.
- `phases`: project stages, keyed by `(data_id, phase_id)`.
- `units`: unit/detail entries, keyed by `(data_id, phase_id, detail_id)`.
- `payment_plans`: keyed by `(data_id, phase_id, plan_id)`.
- `detail_fetch_state`: latest success/failure and timestamp per project.
- `projects_with_city`: view joining project records to city names.

All detail child tables use foreign keys with cascading deletion. Saving a
project's details replaces its child snapshot in a single transaction. Repeated
runs update existing keys instead of duplicating records. Listing records with
`DataDeliveryFrom=null` remain stored, but their details are not fetched.
`DataIsOffer` does not affect eligibility. Missing delivery fields are also excluded.
A clean rebuild contains no old samples or stale detail snapshots.

## Source semantics

Delivery and finishing fields are codes until their dictionaries are confirmed.
Payment intervals and down-payment values retain source units; no guessed unit
conversion is performed. Suspicious sentinel values such as `9999999999` are
preserved verbatim and must not be treated as verified prices or dimensions by
an agent. Raw responses are retained inside SQLite for future normalization.
Unavailable source fields are not invented. Response list entries may represent
unit configurations rather than individually identified physical properties.
