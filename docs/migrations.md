# Adding a migration

1. Define `_migrate_v<N>_to_v<N+1>` in `src/en_reader/storage.py`.
2. Append to the `MIGRATIONS` list.
3. Regenerate fixtures: `python scripts/generate_migration_fixtures.py`.
4. Add a new entry to `test_migrations.py` parametrize.
5. PR is blocked until `pytest tests/test_migrations.py` is green.
