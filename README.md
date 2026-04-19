# en-reader

English reader with inline Russian translations for B1-C1 learners.

## Как запустить

```
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
pytest
```

The spaCy model `en_core_web_sm==3.8.0` is pinned as a wheel dependency in
`pyproject.toml`, so `pip install -e .` installs it directly — no separate
`python -m spacy download` step is needed. The pin exists because golden
fixtures in `tests/fixtures/golden/` depend on exact pipeline output; any
model bump must be followed by `pytest tests/test_golden.py --update-golden`
plus a manual diff review.

## Dev

```
python scripts/build_demo.py tests/fixtures/long.txt
uvicorn en_reader.app:app --reload --port 8000
# open http://localhost:8000
```
