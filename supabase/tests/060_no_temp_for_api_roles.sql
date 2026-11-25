-- API-facing roles must not be able to create temporary objects (see migration 20261125100000).
BEGIN;
SELECT * FROM no_plan();

SELECT is(has_database_privilege('edu_api', current_database(), 'TEMPORARY'), false,
    'edu_api cannot create temporary objects');
SELECT is(has_database_privilege('edu_api_login', current_database(), 'TEMPORARY'), false,
    'edu_api_login cannot create temporary objects');
SELECT is(has_database_privilege('anon', current_database(), 'TEMPORARY'), false,
    'anon cannot create temporary objects');
SELECT is(has_database_privilege('authenticated', current_database(), 'TEMPORARY'), false,
    'authenticated cannot create temporary objects');
SELECT is(has_database_privilege('authenticator', current_database(), 'TEMPORARY'), false,
    'authenticator cannot create temporary objects');
SELECT is(has_database_privilege('service_role', current_database(), 'TEMPORARY'), false,
    'service_role cannot create temporary objects');

SELECT * FROM finish();
ROLLBACK;
