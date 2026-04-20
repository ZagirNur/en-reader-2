# Contributing

1. Branch off `main` as `task/Mx-y-name` (or a similar descriptive prefix).
2. Open a PR into `main`.
3. CI (`lint`, `test`, `e2e`) must be green before merge — the branch is
   protected and red checks block the merge button.
4. Keep the branch up to date with `main` before requesting review.
5. One approval from the team lead unblocks merge.

## Local setup

```
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"       # runtime + test tooling
```

The spaCy model wheel is pinned as a dependency, so `pip install -e .`
already installs `en_core_web_sm==3.8.0`. No separate
`python -m spacy download` step is needed.

## Running the suite

Unit + integration (the default loop):

```
pytest tests/ --ignore=tests/e2e
```

Full coverage report:

```
pytest --cov=en_reader --cov-report=term-missing tests/ --ignore=tests/e2e
```

End-to-end (Playwright, Chromium):

```
python -m playwright install --with-deps chromium   # first time only
pytest tests/e2e
```

Set `HEADED=1` and sprinkle `page.pause()` for interactive debugging.

## Lint & format

```
ruff check .
black --check .
```

Both are wired into CI's `lint` job; running them locally before pushing
avoids a round-trip.

## Migrations

See `docs/migrations.md` for the procedure when adding a new
`_migrate_vN_to_vN+1`. Each migration needs a matching `schema_vN.db`
fixture in `tests/fixtures/migrations/`.

## Deploy

Autopull pulls every 10 s on the VPS (see `deploy/README.md`). Merging
to `main` is the release.
