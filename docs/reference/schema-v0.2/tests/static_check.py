"""Static-only sanity checks; NOT a substitute for a PostgreSQL/Supabase test run."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
sql=(ROOT/'migrations/0001_core_schema.sql').read_text()
api=(ROOT/'migrations/0002_api_role_and_policies.sql').read_text()
tables=re.findall(r'CREATE TABLE app\.([a-z_]+)\s*\(', sql)
assert len(tables)==22 and len(tables)==len(set(tables)),tables
missing=[ref for ref in re.findall(r'REFERENCES app\.([a-z_]+)',sql) if ref not in tables]
assert not missing, missing
assert 'REFERENCES auth.users' in sql
assert all(re.search(r'CREATE TABLE app\.'+t+r'\b',sql) for t in tables)
assert re.search(r'FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = \'app\'',sql)
assert 'ENABLE ROW LEVEL SECURITY' in sql
assert len(re.findall(r'CREATE POLICY ',api))>=20
assert 'NOBYPASSRLS' in api
assert 'GRANT UPDATE ON app.staff_roles' not in api
assert 'GRANT INSERT ON app.lesson_revisions' not in api
assert 'GRANT SELECT ON app.background_jobs' not in api
assert 'current_actor_id()' in api
assert 'UNIQUE (learner_id, op_id)' in sql
assert 'PRIMARY KEY (learner_id, op_id)' in sql
assert 'PRIMARY KEY (learner_id, version)' in sql
assert 'SECURITY DEFINER SET search_path' in sql
assert 'CURRENT_SCHEMA' not in sql
assert (ROOT/'diagrams/Mon-Edupreneur-Schema-v0.2.drawio').exists()
print(f'STATIC PASS: {len(tables)} unique private tables; {len(re.findall(r"CREATE POLICY ",api))} RLS policies; '
      f'{len(re.findall(r"CREATE TRIGGER ",sql))} guards; all internal FK table names exist.')
print('NOT TESTED: SQL syntax/execution, Supabase Auth integration, RLS login role, sync concurrency, and trigger behavior.')
