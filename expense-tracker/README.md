# Spending Ledger

A personal expense tracker, published as a private claude.ai artifact:
https://claude.ai/artifact/MwVZGUeiSsz1sULAFreuwS

`index.html` is the whole app (no build step). It is separate from the
Eastman tracker in `src/`.

## What it does

- **Log an expense** with amount, place, category, date, and whether it was a
  *need* or a *want*. The category is guessed from the place name.
- **Import a bank statement** (CSV). Date / description / amount columns are
  detected automatically; income, card payments and transfers are skipped, and
  rows already logged are not added twice.
- **Where it goes**: spending per category split into needs and wants, with
  optional monthly budgets, plus a six-month trend.
- **Where you could cut**: suggestions ranked by what they cost per year:
  broken budgets, recurring charges you chose, frequent small buys (the
  daily-coffee effect), categories rising against your 3-month average, big
  one-off purchases, and a wants share above ~30%.
- **Recurring charges**: anything at a steady price in 2+ of the last 6 months.

## Data

Stored in the artifact's database, readable and writable only by the owner:
one document per month (`months/YYYY-MM` → `{items: [...]}`) and
`settings/main` for currency and budgets. Opened outside claude.ai, the page
falls back to the browser's localStorage.

The first data loaded is example data (every item has `ex: true`); the
"Clear examples" button removes it.
