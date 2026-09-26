# Google Play Store Reviews Scraper — Implementation Plan

## 1. Goal

Build a command-line tool that takes a Google Play app identifier, in either of these forms:

| Input form  | Example                                                              |
| ----------- | -------------------------------------------------------------------- |
| Package ID  | `com.oakever.meowdoku`                                               |
| Store URL   | `https://play.google.com/store/apps/details?id=com.oakever.meowdoku` |

It then extracts reviews (a chosen number, or **as many as Google Play exposes**) and stores them as **raw JSON** on disk. It also saves the unmodified server responses so nothing is lost if the parsing logic changes later.

### 1.1 User inputs

Besides the app, the user controls three things:

| # | Input                  | Options                                                                 | Default  |
| - | ---------------------- | ----------------------------------------------------------------------- | -------- |
| 1 | **How many reviews**   | `100`, `1000`, `10000`, `100000`, any custom positive number, or `all`  | `all`    |
| 2 | **Sort by**            | `newest`, `relevant` (Most relevant), `rating`, or `all` (combine every sort for maximum coverage) | `newest` |
| 3 | **Review language**    | `any` (all languages), or one or more specific languages given by code or name: `en`, `hi`, `hindi`, `en,hi`, `german`, ... | `en`     |

The user can provide them in two ways:

- **Command-line flags** (for scripting): `--count`, `--sort`, `--lang`.
- **Interactive prompts** (for manual use): if a flag is missing and the terminal is interactive, the tool asks for it with a numbered menu. `--yes` skips the prompts and uses the defaults.

```text
$ python -m playstore_scraper
App package name or Play Store URL: https://play.google.com/store/apps/details?id=com.oakever.meowdoku

How many reviews?
  1) 100   2) 1,000   3) 10,000   4) 100,000   5) All possible   6) Custom number
Choose [5]: 6
Enter number: 2500

Sort by?
  1) Newest   2) Most relevant   3) Rating   4) All sorts (max coverage)
Choose [1]: 1

Review language?
  1) English (en)   2) Any language   3) Hindi (hi)   4) Other (type code or name)
Choose [1]: 3

→ Fetching 2,500 newest Hindi reviews for com.oakever.meowdoku
```

How each input changes the scraper's behavior:

**1. Count (`--count`)**

- `N` (a number): stop as soon as `N` **unique** reviews are saved. The last page is trimmed so the output has exactly `N` reviews, or fewer if Google runs out first. The summary then reports `"requested": N, "received": M`.
- `all`: keep going until every planned stream is exhausted (see §2 and §6.6).
- Input validation: accepts `1000`, `1,000`, `1k`, `10k`, `100k`, `1m`, and `all` (case-insensitive). Zero, negative numbers, and non-numbers are rejected with a clear message.

**2. Sort (`--sort`)**

- `newest`, `relevant`, or `rating`: reviews come from that sort order. The first stream is `<sort> / all stars`. If it runs out before the requested count is reached (or when count is `all`), the tool continues with the per-star streams of the **same sort** (5★, 4★, … 1★) to find more reviews. The final `reviews.json` is ordered by the chosen sort:
  - `newest`: by date, newest first;
  - `rating`: by score descending, then by date;
  - `relevant`: in the order Google returned them.
- `all`: combines all three sorts × star filters (the full stream matrix in §6.6). This gives maximum coverage. The final output is ordered newest first.

**3. Language (`--lang`)**

- A specific language such as `en` or `hindi`: only streams with `hl=<code>` are used. Google Play partitions reviews by language, so this returns reviews written in (or tagged as) that language.
- Several languages, e.g. `en,hi`: streams run for each listed language.
- `any`: runs through the built-in `ALL_LANGS` preset (about 40 languages, see §6.2). The tool skips languages that return no reviews after one page (the language pre-check in §6.6).
  - With count = `all`, languages are fetched one after another.
  - With count = `N`, languages are fetched **round-robin, one page at a time**, so a limited sample contains a mix of languages instead of only the first language in the list.
- Names are mapped to codes through a lookup table in `languages.py` (`hindi → hi`, `english → en`, `german → de`, `spanish → es`, `portuguese → pt`, `japanese → ja`, `chinese → zh-CN`, …). Unknown values are rejected, and the error lists the supported names and codes.
- Every saved review records the language it was fetched under in `source.lang`. Google does not return a per-review language field, so this is the best available label.

### Success criteria

1. Accepts a package ID or any valid Play Store URL variant (with extra query params such as `&hl=en&gl=US`, `market://details?id=...`, mobile URLs, etc.).
2. Respects the three user inputs from §1.1: **count** (N or all), **sort** (newest / relevant / rating / all), and **language** (any or specific).
3. Paginates through review pages until the requested count is reached or no continuation token remains.
4. For count = `all`, expands coverage past the single-stream limit by combining several **sort orders × star filters × languages/countries**, then de-duplicates by `reviewId`.
5. Writes:
   - the raw server payloads (the untouched `batchexecute` response bodies), and
   - a normalized `reviews.json` / `reviews.jsonl` with one object per unique review.
6. Is **resumable**: an interrupted run continues from the last saved continuation token.
7. Handles rate limits and transient errors politely (backoff, jitter, retry caps).
8. Prints a final summary: reviews requested vs. received, duplicates removed, streams exhausted, and elapsed time.

### Non-goals (v1)

- No login or authenticated scraping. Only public data is collected.
- No headless browser, unless used as a fallback (see §10).
- No database. Output is flat files. A database exporter can come later.
- No sentiment analysis or other analytics.

---

## 2. Important reality check: "all reviews"

The Play Store header count (for example **"364K reviews"** for Meowdoku) counts **ratings**, and many of those have no text. Google also **caps how deep a single paginated stream goes**. In practice one sort order usually stops after a few thousand to a few tens of thousands of reviews, depending on the app and language.

Getting close to "all reviews" therefore takes several strategies together:

| Strategy                    | Why it helps                                                             |
| --------------------------- | ------------------------------------------------------------------------ |
| Sort = Newest               | Walks the timeline backwards. This is the most complete single stream.   |
| Sort = Most relevant        | Returns a different subset (older, highly upvoted reviews).              |
| Sort = Rating               | Returns another different subset.                                        |
| Star filter 1–5 per sort    | Each star bucket is its own stream with its own depth cap.               |
| Multiple `hl` languages     | Reviews are partitioned by language. `hl=en` does not return German reviews, etc. |
| Multiple `gl` countries     | Changes regional ordering and, for some apps, the review set.            |
| Device filter (optional)    | Phone, tablet, and Chromebook reviews can form separate streams.         |

The tool records per-stream stats so the user can see which streams were exhausted naturally and which hit the cap.

---

## 3. Technical approach

### 3.1 Data source: the internal `batchexecute` RPC

The Play Store web UI loads reviews through an internal RPC endpoint. This endpoint is also what the widely used open-source libraries (`google-play-scraper` for Python and Node) call.

```
POST https://play.google.com/_/PlayStoreUi/data/batchexecute?hl={lang}&gl={country}
Content-Type: application/x-www-form-urlencoded;charset=UTF-8
```

Body (URL-encoded form field `f.req`), RPC id **`UsvDTd`**:

```text
f.req=[[["UsvDTd","[null,null,[2,{sort},[{count},null,{token_or_null}],null,[null,{score_or_null}]],[\"{app_id}\",7]]",null,"generic"]]]
```

| Placeholder  | Meaning                                                                      |
| ------------ | ---------------------------------------------------------------------------- |
| `{sort}`     | `1` = Most relevant, `2` = Newest, `3` = Rating                              |
| `{count}`    | Page size. The server accepts up to roughly 200. Use `200` (fall back to `100` if rejected). |
| `{token}`    | Continuation token from the previous page (`null` on the first page).        |
| `{score}`    | Star filter `1`–`5` (`null` = all stars).                                    |
| `{app_id}`   | Package name, e.g. `com.oakever.meowdoku`.                                   |

> ⚠️ This is an **undocumented** endpoint, and its payload shape changes occasionally. Before implementing, check the exact current payload against the latest source of [`JoMingyu/google-play-scraper`](https://github.com/JoMingyu/google-play-scraper) (`google_play_scraper/constants/request.py`). Newer versions add a device-type slot to the filter array. Keep the payload template in **one module** (`rpc.py`) so it is easy to patch.

### 3.2 Response format

```text
)]}'

[["wrb.fr","UsvDTd","<JSON-ENCODED STRING>",null,null,null,"generic"], ...]
```

Parsing steps:

1. Strip the `)]}'` anti-XSSI prefix (the first line).
2. `json.loads` the remainder into an outer array.
3. Find the entry where `[0] == "wrb.fr"` and `[1] == "UsvDTd"`, take `[2]`, and `json.loads` it again. This gives the inner array.
4. `inner[0]` is the list of review arrays (it can be `null` or empty when the stream is exhausted).
5. `inner[-2][-1]` (fall back to `inner[-1][-1]`) is the **next continuation token**. If it is missing or `null`, the stream is done.

### 3.3 Review array field map (verify against the live response)

| Field                  | Path in review array     | Type                 |
| ---------------------- | ------------------------ | -------------------- |
| `reviewId`             | `[0]`                    | str (`gp:AOqpTO...`) |
| `userName`             | `[1][0]`                 | str                  |
| `userImage`            | `[1][1][3][2]`           | str (URL)            |
| `score`                | `[2]`                    | int 1–5              |
| `content`              | `[4]`                    | str or null          |
| `at` (timestamp)       | `[5][0]`                 | int (Unix seconds)   |
| `thumbsUpCount`        | `[6]`                    | int                  |
| `replyContent`         | `[7][1]`                 | str or null          |
| `repliedAt`            | `[7][2][0]`              | int or null          |
| `reviewCreatedVersion` | `[10]`                   | str or null          |
| `appVersion`           | `[10]`                   | str or null          |

All path lookups go through a **safe getter** (`dig(arr, 1, 1, 3, 2, default=None)`), so a changed or missing index yields `null` instead of a crash. The full original review array is **always** kept under `raw` in the normalized record.

### 3.4 Why not use `google-play-scraper` directly?

It is a good reference and a valid fallback, but:

- it discards the raw arrays, and we want raw JSON;
- it does not support checkpointing or resuming mid-stream to disk;
- it does not orchestrate multiple streams or de-duplicate across them.

**Decision:** implement a small, focused client ourselves. Keep `google-play-scraper` as an **optional dev dependency** for cross-checking results in tests and as a documented fallback (`--engine library`).

---

## 4. Tech stack

| Concern         | Choice                               | Reason                                        |
| --------------- | ------------------------------------ | --------------------------------------------- |
| Language        | Python 3.11+                         | Mature ecosystem, simple JSON handling        |
| HTTP            | `httpx` (sync client, HTTP/2 on)     | Connection pooling, timeouts, HTTP/2          |
| Retries         | `tenacity`                           | Declarative exponential backoff with jitter   |
| CLI             | `typer`                              | Clean CLI with type hints and auto help       |
| Progress / logs | `rich`                               | Progress bars and readable logs               |
| JSON            | stdlib `json` (optional `orjson`)    | `orjson` for speed on large dumps             |
| Config models   | `pydantic` v2                        | Validated config and review schema            |
| Tests           | `pytest`, `respx` (httpx mocking)    | Offline, deterministic tests                  |
| Lint / format   | `ruff`                               | One tool for lint and format                  |
| Packaging       | `pyproject.toml` with `uv` or `pip`  | Standard, reproducible                        |

---

## 5. Project structure

```
playstore-scraper/
├── PLAN.md
├── README.md
├── pyproject.toml
├── .gitignore                  # ignores data/, .venv/, __pycache__/
├── src/
│   └── playstore_scraper/
│       ├── __init__.py
│       ├── __main__.py         # `python -m playstore_scraper`
│       ├── cli.py              # typer app, argument parsing
│       ├── input_parser.py     # package-ID / URL → app_id
│       ├── config.py           # ScrapeConfig (pydantic), defaults
│       ├── prompts.py          # interactive menus for count / sort / language
│       ├── languages.py        # ALL_LANGS preset + name→code map (hindi→hi)
│       ├── http_client.py      # httpx client, headers, rate limiter, retries
│       ├── rpc.py              # payload builder + response decoder for UsvDTd
│       ├── parser.py           # review array → normalized dict (safe dig)
│       ├── streams.py          # Stream definition + stream matrix generation
│       ├── scraper.py          # orchestration: run streams, paginate, dedupe
│       ├── storage.py          # raw page writer, JSONL writer, final merge
│       ├── checkpoint.py       # resume state (per-stream token + counts)
│       ├── app_info.py         # optional: fetch app title/ratings count
│       └── utils.py            # dig(), time helpers, jitter sleep
├── tests/
│   ├── fixtures/
│   │   ├── reviews_page_1.txt  # captured raw batchexecute response
│   │   ├── reviews_last_page.txt
│   │   └── reviews_empty.txt
│   ├── test_input_parser.py
│   ├── test_user_options.py    # count / sort / language parsing + validation
│   ├── test_rpc.py
│   ├── test_parser.py
│   ├── test_scraper.py         # mocked end-to-end pagination + dedupe
│   └── test_checkpoint.py
└── data/                       # output root (git-ignored)
```

---

## 6. Module design

### 6.1 `input_parser.py` — normalize the user input

```python
def resolve_app_id(user_input: str) -> str: ...
```

Rules:

1. Trim whitespace and surrounding quotes.
2. If it looks like a URL (`http://`, `https://`, `market://`, or contains `play.google.com`):
   - parse it with `urllib.parse.urlparse` and `parse_qs`;
   - take the `id` query parameter, and error clearly if it is missing;
   - accept `play.google.com/store/apps/details`, `market://details`, and `play.app.goo.gl` short links (the short link is resolved by following redirects with a HEAD or GET request).
3. Validate the resulting package name with this regex (Android package-name rules):
   `^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$`
4. Return the package name, e.g. `com.oakever.meowdoku`.

Also extract optional `hl`/`gl` from the URL and use them as default language/country when the user did not pass flags.

Errors are raised as an `InvalidAppInputError` with a helpful message and examples.

### 6.2 `config.py` — `ScrapeConfig`

| Field               | Default                     | Notes                                          |
| ------------------- | --------------------------- | ---------------------------------------------- |
| `app_id`            | required                    | From the input parser                          |
| `count`             | `None` (= `all`)            | **User input 1.** `--count 1000` / `10k` / `all`. Global cap on unique reviews across all streams |
| `sort`              | `"newest"`                  | **User input 2.** `newest` \| `relevant` \| `rating` \| `all`. Expands to the `sorts` list below |
| `langs`             | `["en"]`                    | **User input 3.** `--lang en`, `--lang hindi`, `--lang en,hi`, or `--lang any` (= `ALL_LANGS`) |
| `countries`         | `["us"]`                    | `--country us,gb,in`                           |
| `sorts`             | derived                     | `["newest"]` for `--sort newest`; all three for `--sort all` |
| `star_filters`      | `[None, 1, 2, 3, 4, 5]`     | `None` = all stars; `--no-star-split` → `[None]` |
| `page_size`         | `200`                       | Auto-drops to 100 if the server rejects it. For small counts it equals `min(200, count)`, so `--count 100` makes a single request |
| `max_pages_per_stream` | `None`                   | Safety cap                                     |
| `since` / `until`   | `None`                      | Date filter (only effective with `newest`: stop once reviews are older than `since`) |
| `delay_seconds`     | `1.0` ± jitter              | Politeness delay between requests              |
| `max_retries`       | `6`                         | Per request                                    |
| `timeout_seconds`   | `30`                        |                                                |
| `out_dir`           | `data/`                     |                                                |
| `save_raw_pages`    | `True`                      | `--no-raw` to disable                          |
| `resume`            | `True`                      | `--fresh` to ignore checkpoints                |
| `proxy`             | `None`                      | Optional `--proxy http://...`                  |

A built-in `ALL_LANGS` preset in `languages.py` covers the ~40 most common Play Store languages (en, es, pt, de, fr, it, ru, ja, ko, zh-CN, zh-TW, hi, id, tr, ar, vi, th, pl, nl, uk, bn, ta, te, mr, ...). The same module maps language names to codes (`hindi → hi`) and validates `--lang`.

**Sensible pairings:**

- `--sort all` normally goes with `--count all`. If combined with a number, the tool warns that ordering is mixed and still stops at `N`.
- `--count N` with a single sort keeps star-splitting on, but per-star streams only start if the `<sort> / all stars` stream runs out before `N`.

### 6.3 `http_client.py`

- One shared `httpx.Client(http2=True, timeout=cfg.timeout_seconds, follow_redirects=True)`.
- Headers: a realistic desktop `User-Agent`, `Origin: https://play.google.com`, `Referer: https://play.google.com/`, `Accept-Language` matching `hl`.
- **Rate limiter:** a simple token bucket, or "sleep `delay ± 30%` between requests".
- **Retry policy (tenacity):**
  - Retry on: connection errors, timeouts, HTTP `429`, `500`, `502`, `503`, `504`.
  - Exponential backoff: `min(2**attempt, 60)s` plus random jitter.
  - On `429`: honor `Retry-After` if present, and double the base delay for the rest of the run (adaptive slow-down).
  - Do **not** retry `400`/`404`. Surface them as a clear error (bad payload or app not found).
- Returns the raw response text.

### 6.4 `rpc.py`

```python
SORT = {"relevant": 1, "newest": 2, "rating": 3}

def build_reviews_payload(app_id: str, sort: int, count: int,
                          token: str | None, score: int | None) -> str: ...

def decode_reviews_response(body: str) -> tuple[list[list], str | None]:
    """Return (review_arrays, next_token)."""
```

- Builds the inner JSON with `json.dumps` (never string-concatenate user values), wraps it in the outer envelope, and URL-encodes it with `urllib.parse.urlencode({"f.req": ...})`.
- The decoder performs the four steps in §3.2 and raises `RpcDecodeError` (with the first 500 characters of the body saved to logs) if the structure is unrecognized. A full raw dump is written to `data/<app>/errors/`.

### 6.5 `parser.py`

```python
def normalize_review(arr: list, *, lang: str, country: str,
                     sort: str, star_filter: int | None) -> dict: ...
```

Output shape per review:

```json
{
  "reviewId": "gp:AOqpTOE...",
  "userName": "Morgan Roelofs",
  "userImage": "https://play-lh.googleusercontent.com/...",
  "score": 4,
  "content": "I LOVED this game. couldn't stop playing it...",
  "thumbsUpCount": 4,
  "reviewCreatedVersion": "1.12.0",
  "appVersion": "1.12.0",
  "at": "2026-09-18T14:03:11Z",
  "atUnix": 1789740191,
  "replyContent": null,
  "repliedAt": null,
  "source": {
    "lang": "en",
    "country": "us",
    "sort": "newest",
    "starFilter": null,
    "firstSeenStream": "en-us-newest-all"
  },
  "raw": [ "...original review array, untouched..." ]
}
```

### 6.6 `streams.py`

A **stream** is one unique combination of `(lang, country, sort, star_filter)`. Its id looks like `en-us-newest-5`.

```python
@dataclass(frozen=True)
class Stream:
    lang: str
    country: str
    sort: str
    star_filter: int | None
    @property
    def id(self) -> str: ...
```

`build_stream_matrix(cfg)` builds the streams from the user's inputs (`cfg.sorts` × `cfg.langs` × `cfg.countries` × `cfg.star_filters`).

**Single sort (`--sort newest|relevant|rating`)**, per language:

1. `<sort> / all stars`,
2. `<sort> / 5★`, `4★`, `3★`, `2★`, `1★` (only started if more reviews are still needed).

**All sorts (`--sort all`)**, ordered by expected yield:

1. `newest / all stars` for each language (the widest coverage first),
2. `newest / per-star`,
3. `relevant / all` and `relevant / per-star`,
4. `rating / all` and `rating / per-star`,
5. extra countries last (they mostly return duplicates).

**Language order:**

- For `--lang any` with a numeric count, streams from different languages are **interleaved page by page** (round-robin), so a 1,000-review sample is spread across languages.
- Otherwise, languages run one after another in the order given.

**Adaptive pruning:** if a stream's new-unique ratio falls below a threshold (e.g. under 2% new reviews over 5 consecutive pages), stop it early and move on. This avoids wasting requests on streams that only repeat known reviews. It can be disabled with `--no-prune`.

**Language pre-check:** before running the full matrix for a language, fetch one page of `newest / all`. If it returns 0 reviews, skip every stream for that language.

### 6.7 `scraper.py` — orchestration

Pseudocode:

```text
seen_ids   = load from existing reviews.jsonl (if resuming) else empty set
checkpoint = load checkpoint.json (if resuming)

for stream in build_stream_matrix(cfg):
    if checkpoint[stream].done: continue
    token = checkpoint[stream].token          # None on first page
    page  = checkpoint[stream].pages

    loop:
        body            = http.post(batchexecute, payload(stream, token))
        storage.save_raw_page(stream, page, body)          # raw JSON, untouched
        arrays, token   = rpc.decode(body)

        new = 0
        for arr in arrays:
            rec = parser.normalize(arr, stream)
            if rec.reviewId in seen_ids: continue
            seen_ids.add(rec.reviewId)
            storage.append_review(rec)                     # reviews.jsonl
            new += 1

        page += 1
        checkpoint.update(stream, token, page, fetched=len(arrays), new=new)
        checkpoint.save()                                  # atomic write

        stop if: token is None
              or arrays empty
              or cfg.count reached (global; trim the last page to exactly count)
              or max_pages_per_stream reached
              or since-date passed (newest only)
              or prune rule triggered

    checkpoint.mark_done(stream, reason)

storage.finalize()   # build reviews.json and summary.json from reviews.jsonl
```

Other behavior:

- **Ctrl+C handling:** catch `KeyboardInterrupt`, flush the files, save the checkpoint, and print "Resume with the same command."
- **Single-threaded by default.** Concurrency increases block risk. An optional `--workers N` (default 1, max 4) runs different streams in parallel threads with a shared rate limiter and a locked `seen_ids` set.

### 6.8 `storage.py` — output layout

```
data/
└── com.oakever.meowdoku/
    └── 2026-09-27T00-18-00Z/          # one folder per run (or reuse latest when resuming)
        ├── raw/
        │   ├── en-us-newest-all/
        │   │   ├── page_0000.json     # untouched response body in a small envelope (see below)
        │   │   ├── page_0001.json
        │   │   └── ...
        │   └── en-us-newest-5/...
        ├── reviews.jsonl              # streaming append, one normalized review per line
        ├── reviews.json               # final merged array (built at finalize)
        ├── checkpoint.json            # resume state
        ├── summary.json               # run stats
        ├── app_info.json              # optional app metadata
        └── errors/                    # undecodable responses, for debugging
```

Raw page file format. The body is stored **exactly as received**, wrapped in a small envelope so it is still valid JSON:

```json
{
  "stream": "en-us-newest-all",
  "page": 3,
  "requestedAt": "2026-09-27T00:19:42Z",
  "request": { "url": "...batchexecute?hl=en&gl=us", "fReq": "[[[\"UsvDTd\", ...]]]" },
  "httpStatus": 200,
  "body": ")]}'\n\n[[\"wrb.fr\",\"UsvDTd\",...]]"
}
```

Rules:

- **Atomic writes:** write to `*.tmp`, then `os.replace` (this is safe on Windows).
- `reviews.jsonl` is opened in append mode and flushed after every page, so a crash loses at most one page.
- `reviews.json` is created at the end: read the JSONL, sort by `atUnix` descending, and write a pretty-printed or compact array (`--pretty`).
- Encoding is always UTF-8 with `ensure_ascii=False`, so emoji and non-Latin text stay readable.
- Optional gzip of the `raw/` folder when the run finishes (`--compress-raw`).

### 6.9 `checkpoint.py`

```json
{
  "appId": "com.oakever.meowdoku",
  "configHash": "sha1-of-relevant-config",
  "streams": {
    "en-us-newest-all": { "token": "CpoBCpcBKpQB...", "pages": 57, "fetched": 11400,
                          "new": 11400, "done": false, "doneReason": null },
    "en-us-newest-5":   { "token": null, "pages": 40, "fetched": 8000,
                          "new": 312, "done": true, "doneReason": "exhausted" }
  },
  "totalUnique": 11712,
  "updatedAt": "2026-09-27T00:41:09Z"
}
```

- On start, if a checkpoint exists for the same `appId`, the tool resumes it (unless `--fresh` is passed). If the `configHash` differs, the tool warns and resumes only the streams that still match.
- `seen_ids` is rebuilt from `reviews.jsonl` on resume. This is cheap: about 1M ids takes roughly 50 MB of RAM.
- Continuation tokens can expire after hours or days. If a resumed token returns an error or empty data, restart that stream from page 0. De-duplication keeps the output correct.

### 6.10 `app_info.py` (optional but useful)

Fetch `https://play.google.com/store/apps/details?id={app_id}&hl=en&gl=us` and extract the title, developer, total rating count, rating histogram, and installs. The details page embeds data in `AF_initDataCallback` script blocks; parse them with a regex plus `json.loads`, with a safe fallback to `null`.

Uses:

- a **404 early exit**: "App not found: com.foo.bar";
- a **coverage metric** in the summary: `uniqueReviews / totalRatings` (and per-star coverage against the histogram).

---

## 7. CLI design

```bash
# Fully interactive: asks for app, count, sort, and language
python -m playstore_scraper

# App given, the rest prompted
python -m playstore_scraper com.oakever.meowdoku

# The three user inputs as flags
python -m playstore_scraper com.oakever.meowdoku --count 100    --sort newest   --lang en
python -m playstore_scraper com.oakever.meowdoku --count 10k    --sort relevant --lang hindi
python -m playstore_scraper com.oakever.meowdoku --count 5000   --sort rating   --lang any
python -m playstore_scraper com.oakever.meowdoku --count all    --sort newest   --lang en,hi

# Maximum coverage: everything Google exposes, every sort, every language
python -m playstore_scraper "https://play.google.com/store/apps/details?id=com.oakever.meowdoku" \
    --count all --sort all --lang any --country us,gb,in,ca,au

# Non-interactive with defaults (all / newest / en)
python -m playstore_scraper com.oakever.meowdoku --yes

# Only recent reviews
python -m playstore_scraper com.oakever.meowdoku --sort newest --since 2026-09-01

# Fresh run, custom output, slower pace
python -m playstore_scraper com.oakever.meowdoku --fresh --out ./exports --delay 2.5
```

| Flag                  | Description                                            |
| --------------------- | ------------------------------------------------------ |
| `APP` (positional)    | Package ID or Play Store URL (prompted if omitted)     |
| `--count`             | **User input 1.** `100`, `1000`, `10k`, `100000`, any number, or `all` (default `all`) |
| `--sort`              | **User input 2.** `newest` (default), `relevant`, `rating`, or `all` |
| `--lang`              | **User input 3.** `en` (default), `any`, a code or name (`hi`, `hindi`), or a comma list (`en,hi`) |
| `--yes` / `-y`        | Do not prompt; use defaults for anything not given     |
| `--country`           | Comma list of countries (default `us`)                 |
| `--no-star-split`     | Do not add per-star streams (fewer requests, less coverage) |
| `--since / --until`   | ISO date bounds (applied as a filter; `since` also stops `newest` streams early) |
| `--page-size N`       | Default 200                                            |
| `--delay SECONDS`     | Base delay between requests (default 1.0)              |
| `--workers N`         | Parallel streams (default 1)                           |
| `--out DIR`           | Output root (default `data/`)                          |
| `--no-raw`            | Skip saving raw pages                                  |
| `--compress-raw`      | Gzip raw pages at the end                              |
| `--pretty`            | Pretty-print `reviews.json`                            |
| `--fresh`             | Ignore existing checkpoints                            |
| `--no-prune`          | Disable adaptive stream pruning                        |
| `--proxy URL`         | HTTP/SOCKS proxy                                       |
| `--engine`            | `native` (default) or `library` (google-play-scraper fallback) |
| `-v / -q`             | Verbose / quiet logging                                |

Exit codes: `0` success, `1` invalid input, `2` app not found, `3` blocked or rate-limited beyond the retry budget, `4` unexpected response format, `130` interrupted.

Console output (rich):

```
App: Meowdoku: Brain Puzzle Games (com.oakever.meowdoku) — 364K ratings
Request: count=all | sort=all | lang=en
Streams: 18 planned (1 lang × 1 country × 3 sorts × 6 star filters)

[en-us-newest-all]   ████████████░░░  page 57   11,400 fetched   11,400 new
[en-us-newest-5]     done (exhausted) page 40    8,000 fetched      312 new
...
Total unique: 14,982 | duplicates skipped: 21,340 | requests: 214 | 00:07:12
Saved → data/com.oakever.meowdoku/2026-09-27T00-18-00Z/
```

---

## 8. `summary.json`

```json
{
  "appId": "com.oakever.meowdoku",
  "appTitle": "Meowdoku: Brain Puzzle Games",
  "startedAt": "2026-09-27T00:18:00Z",
  "finishedAt": "2026-09-27T00:25:12Z",
  "totalRatingsReported": 364000,
  "request": { "count": "all", "sort": "all", "langs": ["en"] },
  "uniqueReviews": 14982,
  "withText": 14950,
  "coverageOfRatings": 0.0412,
  "byScore": { "1": 812, "2": 403, "3": 990, "4": 2210, "5": 10567 },
  "byLang": { "en": 14982 },
  "requests": 214,
  "retries": 3,
  "streams": [
    { "id": "en-us-newest-all", "pages": 60, "fetched": 12000, "new": 12000, "doneReason": "exhausted" },
    { "id": "en-us-rating-5", "pages": 12, "fetched": 2400, "new": 31, "doneReason": "pruned" }
  ],
  "config": { "...": "effective config" }
}
```

---

## 9. Error handling matrix

| Situation                                 | Behavior                                                         |
| ----------------------------------------- | ---------------------------------------------------------------- |
| Invalid input (not a package or URL)      | Exit 1 with examples of valid input                              |
| URL without an `id` parameter             | Exit 1 with "URL has no `id=` parameter"                         |
| App not found (404 on details, or empty RPC with error) | Exit 2                                             |
| HTTP 429 / 503                            | Backoff and retry, then adaptively raise the delay               |
| Retry budget exhausted                    | Save the checkpoint, exit 3, and tell the user to resume later or use `--proxy` |
| Response structure changed                | Dump to `errors/`, save the checkpoint, exit 4 with a pointer to `rpc.py` |
| Page returns 0 reviews but has a token    | Allow up to 3 empty pages, then mark the stream `exhausted`      |
| Expired token on resume                   | Restart that stream from page 0 (dedupe keeps the output correct) |
| Disk write failure                        | Abort immediately; atomic writes keep the existing files valid   |
| Ctrl+C                                    | Flush, checkpoint, exit 130                                      |

---

## 10. Anti-blocking and politeness

- Default rate of about 1 request per second with jitter. This is enough, since each request returns up to 200 reviews.
- Reuse one connection (keep-alive, HTTP/2) instead of opening a new connection per request.
- Keep headers consistent with a real browser.
- Adaptive slowdown on 429s.
- Optional proxy support for large multi-language runs.
- **Fallback (future):** a Playwright-based engine that opens the reviews dialog and captures `batchexecute` responses from the network. It is only for the case where the direct RPC gets blocked or changes, and is not part of v1.

---

## 11. Testing strategy

| Test type          | What                                                                  |
| ------------------ | --------------------------------------------------------------------- |
| Unit: input parser | Package IDs, URLs with extra params, `market://`, invalid strings, missing `id` |
| Unit: rpc payload  | Payload matches the expected template for every sort, star, and token combination |
| Unit: rpc decoder  | Real captured fixtures: first page, last page (no token), empty page, garbage body |
| Unit: parser       | Field mapping, missing nested fields → `null`, timestamp conversion, `raw` kept |
| Unit: checkpoint   | Save and load round-trip, atomic write, config-hash mismatch          |
| Integration (mocked) | `respx` serves 3 pages for 2 streams with overlapping ids. Assert dedupe, file outputs, and summary counts |
| Resume test        | Simulate a crash after page 2, rerun, and assert no duplicates and correct continuation |
| Live smoke test (opt-in) | `pytest -m live`: fetch 1 page for `com.oakever.meowdoku` and assert more than 0 reviews with valid fields. Skipped in CI by default |
| Cross-check (opt-in) | Compare the first 200 `newest` review ids against the `google-play-scraper` output |

Fixtures are captured once with a `scripts/capture_fixture.py` helper, and user names and images are anonymized before committing.

---

## 12. Implementation milestones

| # | Milestone                         | Deliverables                                                    | Est.  |
| - | --------------------------------- | --------------------------------------------------------------- | ----- |
| 1 | Project scaffold                  | `pyproject.toml`, package layout, ruff, pytest, `.gitignore`    | 0.5 h |
| 2 | Input parsing and user options    | `input_parser.py`, `languages.py`, `prompts.py` (count / sort / language menus) + tests | 1.5 h |
| 3 | RPC layer                         | `rpc.py` payload + decoder, capture live fixtures, tests        | 2 h   |
| 4 | HTTP client                       | `http_client.py` with retries, rate limit, 429 handling         | 1 h   |
| 5 | Parser                            | `parser.py` with safe `dig`, normalized schema, tests           | 1 h   |
| 6 | Single-stream scraper             | Paginate one stream to exhaustion, write raw pages and JSONL    | 1.5 h |
| 7 | Checkpoint and resume             | `checkpoint.py`, Ctrl+C handling, resume tests                  | 1.5 h |
| 8 | Multi-stream orchestration        | Stream matrix, dedupe, pruning, language pre-check              | 2 h   |
| 9 | Finalize and summary              | `reviews.json`, `summary.json`, rich console output             | 1 h   |
| 10 | App info and coverage            | `app_info.py`, 404 early exit, coverage metric                  | 1.5 h |
| 11 | CLI polish                       | All flags, exit codes, help text, README usage examples         | 1 h   |
| 12 | Live validation                  | Full run on `com.oakever.meowdoku`, tune defaults               | 1 h   |
|   | **Total**                         |                                                                 | **~15.5 h** |

**MVP cut (milestones 1–6 and 9):** a single command that takes a package ID or URL plus the three user inputs (count, sort, language), paginates the chosen sort until the count is reached or the stream ends, and writes raw pages plus `reviews.json`. This is usable in about 8 hours. Multi-stream coverage and resume come right after.

---

## 13. Future extensions

- Export to CSV, Parquet, or SQLite (`--format csv,parquet,sqlite`).
- Incremental mode: fetch only reviews newer than the latest `atUnix` in a previous run (`--incremental`).
- Scheduled runs (cron or Task Scheduler) for review monitoring.
- Several apps in one run (`--apps-file apps.txt`).
- Playwright fallback engine (§10).
- A simple web UI or API wrapper.

---

## 14. Legal and ethical notes

- Only publicly visible review data is collected, and no authentication is bypassed.
- Scraping may conflict with Google Play's Terms of Service. Use the tool responsibly, at low request rates, and for research or analysis purposes.
- Reviews contain personal data (display names and avatars). Store them securely, and consider anonymizing `userName`/`userImage` (`--anonymize` flag, which hashes them) before sharing datasets, in line with GDPR and similar regulations.
- For apps you own, prefer the official **Google Play Developer API** (`reviews.list`). Note that it only returns reviews from the last 7 days, which is why scraping is used for historical data.

---

## 15. Open decisions (defaults chosen, confirm if needed)

| Decision                       | Default in this plan               |
| ------------------------------ | ---------------------------------- |
| Language                       | Python 3.11+                       |
| Default count                  | `all`                              |
| Default sort                   | `newest` (per-star streams added only when more reviews are needed) |
| Default language               | `en` (`any` = ~40-language preset) |
| Default country                | `us`                               |
| Raw storage                    | Full response bodies per page, uncompressed |
| Final output                   | `reviews.jsonl` + `reviews.json` (compact) |
| Concurrency                    | 1 worker                           |
