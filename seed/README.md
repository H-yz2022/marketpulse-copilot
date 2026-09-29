# Built-in snapshot

`marketpulse_seed.json.gz` is a small snapshot of real data (daily prices, the latest
10-K risk-factor sections, their sentiment scores and each chunk's precomputed
embedding) for the default tickers.

- The app loads it automatically on first start when the database is empty, so a fresh
  install or deploy is usable in seconds instead of waiting on SEC EDGAR and Yahoo Finance.
- Users can still click **Refresh live data** on any ticker to replace its snapshot with
  real-time data.
- To update it: fetch fresh data locally (`python scripts/run_pipeline.py --ticker ...`),
  then run `python scripts/export_seed.py` and commit the new file.
