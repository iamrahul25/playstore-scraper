# Google Play Store Reviews Scraper

CLI tool that fetches public Google Play reviews for an app and saves **raw** server responses plus normalized JSON.

## Install

```bash
cd playstore-scraper
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

## Usage

```bash
# Interactive (prompts for count, sort, language)
python -m playstore_scraper

# Package ID or URL
python -m playstore_scraper com.oakever.meowdoku --yes
python -m playstore_scraper "https://play.google.com/store/apps/details?id=com.oakever.meowdoku" --yes

# The three main options
python -m playstore_scraper com.oakever.meowdoku --count 100 --sort newest --lang en
python -m playstore_scraper com.oakever.meowdoku --count 10k --sort relevant --lang hindi
python -m playstore_scraper com.oakever.meowdoku --count all --sort newest --lang en,hi
python -m playstore_scraper com.oakever.meowdoku --count 5000 --sort rating --lang any
```


| Flag              | Description                                              |
| ----------------- | -------------------------------------------------------- |
| `APP`             | Package ID or Play Store URL                             |
| `--count`         | `100`, `1000`, `10k`, `100000`, or `all` (default `all`) |
| `--sort`          | `newest` (default), `relevant`, `rating`, or `all`       |
| `--lang`          | `en` (default), `any`, name (`hindi`), or list (`en,hi`) |
| `--yes` / `-y`    | Skip interactive prompts                                 |
| `--country`       | Country codes, comma-separated (default `us`)            |
| `--no-star-split` | Skip per-star streams                                    |
| `--fresh`         | Ignore checkpoint / start a new run folder               |
| `--out`           | Output root (default `data/`)                            |
| `--delay`         | Seconds between requests (default `1.0`)                 |
| `--pretty`        | Pretty-print `reviews.json`                              |




## Output

```
data/<app_id>/<timestamp>/
  raw/<stream>/page_XXXX.json   # untouched batchexecute bodies
  reviews.jsonl                 # one normalized review per line
  reviews.json                  # merged array
  checkpoint.json               # resume state
  summary.json
  app_info.json
```

Interrupted runs can be resumed by running the same command again (omit `--fresh`).

## Tests

```bash
pytest
pytest -m live   # optional live smoke test against Play Store
```



## Notes

- Only public review data is collected. Request rates are polite by default.
- Google caps how deep a single review stream goes; `--sort all` and `--lang any` expand coverage.
- For apps you own, prefer the official Play Developer API (last 7 days only).

