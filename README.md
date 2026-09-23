# Eastman Incoming Vessels Tracker

Automates a manual logistics task: an operations-team email arrives ("...NEW
EASTMAN CHEMICAL DOCUMENT...") with a scanned PDF of shipping paperwork
(Bill of Lading, Waybill, Commercial Invoice, Packing List, Certificate of
Origin, Certificates of Analysis) for a Texanol shipment. Someone used to
open the PDF, find the vessel name, order number, and each container's
delivery number / quantity, and type them into the shared "Incoming
vessels" tracking sheet by hand.

This script does that part: it polls the mailbox, OCRs the attachment,
extracts those fields, and appends a row per container to a **private
working copy** of the tracker workbook. It never opens or writes to the
shared team file.

Scope today: Eastman Texanol shipments only, matching the document layout
described below. Other Eastman products or a different paperwork layout
from Eastman/the freight forwarder will need the parser extended (see
`src/parser.py`).

## Two ways to run this

**Right now, without any Azure setup:** hand over the PDF directly (attach
it here in chat, or download it yourself) and run:

```bash
python -m src.process_pdf path/to/document.pdf
```

This does everything except the mailbox polling: OCR, parsing, cross-checks,
and appending to the tracker workbook, with the same duplicate-safety net
(it refuses to log a shipment whose Delivery No is already in the sheet).
No `AZURE_*` / `MAILBOX_USER` variables are needed for this path -- only the
`TRACKER_*` settings in `.env`.

**Later, once the Azure AD app is set up:** run `python -m src.main` on a
schedule (cron) and it polls the mailbox for you, downloading and processing
matching attachments automatically. See the Azure setup steps below.

## How it works (automatic/email mode)

```
cron (every N min)
  -> Microsoft Graph: list recent Inbox messages with attachments
       whose subject contains "NEW EASTMAN CHEMICAL DOCUMENT"
  -> for each new message (not seen before, tracked in data/processed_messages.json):
       -> download the PDF attachment
       -> render each page to an image (pdftoppm) and OCR it (tesseract)
       -> parse: vessel name + order # from the Certificate of Origin,
                 delivery # + container # + net weight per container from
                 the Packing List, cross-checked against the Certificate of
                 Origin's own container/weight table to catch OCR errors
       -> append one row per container to the tracker workbook's
          "Incoming vessels-<year>" sheet, into the next blank pre-numbered
          template rows (matching the sheet's existing pattern: vessel name
          and unit count only on the first row of a shipment's rows)
       -> if anything couldn't be confidently parsed or was auto-corrected,
          the row's Remarks column gets "NEEDS REVIEW: ..." -- these are
          worth a quick manual glance, not blind trust
```

Offload quantity, offload date, ETA and arrival date are **not** in this
paperwork (they only exist once the vessel actually arrives and is
discharged), so those columns are always left blank for manual entry later,
same as before.

## One-time setup

### 1. Azure AD app registration (Microsoft Graph)

1. In the Azure Portal, register a new app (Entra ID -> App registrations).
2. API permissions -> Add -> Microsoft Graph -> **Application permissions**
   -> `Mail.Read`. Grant admin consent.
3. Certificates & secrets -> create a client secret. Note the value now (it
   won't be shown again).
4. Note the **Tenant ID**, **Application (client) ID**, and the client
   secret you just created.
5. **Important**: `Mail.Read` as an application permission grants access to
   *every* mailbox in the tenant by default. Scope it down to just the
   operations mailbox with an
   [Exchange Application Access Policy](https://learn.microsoft.com/en-us/graph/auth-limit-mailbox-access):

   ```powershell
   New-ApplicationAccessPolicy -AppId <client-id> \
     -PolicyScopeGroupId ops-eastman@yourcompany.com \
     -AccessRight RestrictAccess -Description "Eastman tracker: read-only, this mailbox only"
   ```

### 2. System dependencies (on the server that will run the cron job)

```bash
sudo apt-get install -y poppler-utils tesseract-ocr
```

### 3. Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Configuration

```bash
cp .env.example .env
```

Fill in `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and
`MAILBOX_USER` (the mailbox that receives the Eastman emails).

### 5. Seed the tracker workbook

Put a **one-time copy** of the current shared "Incoming vessels" workbook at
the path in `TRACKER_SEED_XLSX` (default `./data/EASTMAN_ORDER_STATUS_seed.xlsx`).
On the first run this is copied to `TRACKER_XLSX_PATH` and never touched
again -- everything from then on happens only in that private copy. If your
team's file gets new pre-numbered template rows added over time, re-seed by
deleting the working copy (`TRACKER_XLSX_PATH`) and dropping in a fresh seed.

### 6. Run it once by hand

```bash
python -m src.main
```

Check the log output and the tracker workbook. Once you're happy, schedule
it (see `deploy/eastman-tracker.cron.example`) -- every 15 minutes is
reasonable.

## Reliability notes

- **OCR is not perfect.** It's local/free (Tesseract), not a paid cloud OCR
  service, so accuracy on a noisy scan can slip. The parser cross-checks the
  Packing List's container numbers against the Certificate of Origin's own
  table and corrects single-character misreads automatically -- but it
  flags the row (`NEEDS REVIEW` in the Remarks column) whenever it had to
  make a correction, or couldn't find/confirm a field, rather than silently
  guessing. Skim those rows.
- **Idempotent.** `data/processed_messages.json` records which emails have
  already produced a row, so re-running the script (or overlapping cron
  runs) won't duplicate entries. A simple lock file also prevents two runs
  from writing at once.
- **Runs out of template rows eventually.** The sheet has a fixed block of
  pre-numbered blank rows; once they're used up the script raises a clear
  error instead of guessing how to extend the sheet/formulas. Add more
  template rows by hand when that happens.

## Extending

- New product / different document layout: add new extraction patterns
  alongside the existing ones in `src/parser.py` (see the module docstring
  there for how the Texanol layout was reverse-engineered from a real
  sample).
- Different destination (e.g. Excel Online instead of a local file): swap
  `src/tracker_sheet.py`'s implementation for Microsoft Graph
  Files/Workbook API calls; `src/main.py` doesn't need to change.

## Tests

```bash
pip install pytest
pytest
```

`tests/fixtures/` contains real (redacted-nothing, this data was already
shared for this purpose) OCR output captured from an actual sample
shipment, including the OCR engine's actual misreads -- the tests assert
the parser recovers the correct values anyway.
