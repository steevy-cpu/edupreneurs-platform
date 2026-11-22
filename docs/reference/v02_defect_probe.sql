-- Evidence probe: demonstrates defects C01-C05 and C10 in the UNMODIFIED v0.2
-- drafts. It is NOT part of the schema and never runs against the real `app`
-- schema: it uses a throw-away database inside the LOCAL Postgres container.
--
-- How to run (local stack must be up):
--   pq() { docker exec -i supabase_db_mon-edupreneur psql -U postgres -d v02_check -q "$@"; }
--   docker exec supabase_db_mon-edupreneur psql -U postgres -q -c "CREATE DATABASE v02_check"
--   echo "CREATE SCHEMA auth; CREATE TABLE auth.users (id uuid PRIMARY KEY);" | pq
--   pq < docs/reference/schema-v0.2/migrations/0001_core_schema.sql
--   pq < docs/reference/schema-v0.2/migrations/0002_api_role_and_policies.sql
--   pq -At < docs/reference/v02_defect_probe.sql
--   docker exec supabase_db_mon-edupreneur psql -U postgres -q -c "DROP DATABASE v02_check"
--
-- Observed output on 2026-11-21 is recorded in docs/TEST_REPORT.md.
select 'tables='||count(*) from pg_tables where schemaname='app';
select 'policies='||count(*) from pg_policies where schemaname='app';
select 'triggers='||count(*) from pg_trigger t join pg_class c on c.oid=t.tgrelid where c.relnamespace='app'::regnamespace and not t.tgisinternal;
insert into auth.users values ('a0000000-0000-4000-8000-000000000001'),('a0000000-0000-4000-8000-000000000003');
insert into app.grades(id,code,sort_order,labels) values ('b0000000-0000-4000-8000-000000000001','9AF',3,'{}');
insert into app.subjects(id,slug,labels) values ('b0000000-0000-4000-8000-000000000002','math','{}');
insert into app.courses(id,grade_id,subject_id,slug,titles,visibility) values ('b0000000-0000-4000-8000-000000000003','b0000000-0000-4000-8000-000000000001','b0000000-0000-4000-8000-000000000002','c1','{}','published');
insert into app.units(id,course_id,slug,position,titles) values ('b0000000-0000-4000-8000-000000000004','b0000000-0000-4000-8000-000000000003','u1',1,'{}');
insert into app.lessons(id,unit_id,slug,position) values ('b0000000-0000-4000-8000-000000000005','b0000000-0000-4000-8000-000000000004','l1',1);
insert into app.learner_profiles(user_id) values ('a0000000-0000-4000-8000-000000000001');
insert into app.lesson_revisions(id,lesson_id,revision,locale,title,blocks,status,created_by,approved_by,approved_at)
 values ('c0000000-0000-4000-8000-000000000001','b0000000-0000-4000-8000-000000000005',1,'fr','x','[]','approved','a0000000-0000-4000-8000-000000000003','a0000000-0000-4000-8000-000000000003',now());
select 'C02 v0.2: rows approved with no review, no source, self-approved='||count(*) from app.lesson_revisions where status='approved';
insert into app.lesson_revisions(id,lesson_id,revision,locale,title,blocks,created_by) values ('c0000000-0000-4000-8000-000000000009','b0000000-0000-4000-8000-000000000005',9,'fr','q holder','[]','a0000000-0000-4000-8000-000000000003');
insert into app.pack_releases(id,pack_key,revision,locale,status,manifest_object_key,manifest_sha256,compressed_bytes,released_at)
 values ('f0000000-0000-4000-8000-000000000001','p-key',1,'fr','active','x',sha256('x'),1,now());
insert into app.pack_current(pack_key,locale,release_id) values ('p-key','fr','f0000000-0000-4000-8000-000000000001');
select 'C03 v0.2: EMPTY pack inserted as active and made current='||count(*) from app.pack_current;
insert into app.pack_releases(id,pack_key,revision,locale) values ('f0000000-0000-4000-8000-000000000002','p-key',2,'fr'),('f0000000-0000-4000-8000-000000000003','p-key',3,'fr');
insert into app.pack_items values ('f0000000-0000-4000-8000-000000000002','c0000000-0000-4000-8000-000000000001',1);
update app.pack_releases set status='ready', manifest_object_key='x', manifest_sha256=sha256('x'), compressed_bytes=1 where id='f0000000-0000-4000-8000-000000000002';
update app.pack_items set pack_release_id='f0000000-0000-4000-8000-000000000003' where pack_release_id='f0000000-0000-4000-8000-000000000002';
select 'C04 v0.2: items remaining in the finalized pack after the move='||count(*) from app.pack_items where pack_release_id='f0000000-0000-4000-8000-000000000002';
update app.lesson_revisions set created_by = NULL where id='c0000000-0000-4000-8000-000000000009';
select 'C05 v0.2: author erased on a draft (independence check then skipped)='||count(*) from app.lesson_revisions where created_by is null;
insert into app.question_revisions(id,lesson_revision_id,question_key,position,kind,prompt,response_spec,answer_key,explanation)
 values ('d0000000-0000-4000-8000-000000000001','c0000000-0000-4000-8000-000000000009','q',1,'mcq','{}','{}','{"correct_choice_id":"a"}','{}');
grant edu_api to postgres with inherit false, set true;
begin;
set local role edu_api; set local edu.actor_id = 'a0000000-0000-4000-8000-000000000001';
insert into app.practice_attempts(learner_id,op_id,lesson_revision_id,question_revision_id,response,score)
 values ('a0000000-0000-4000-8000-000000000001',gen_random_uuid(),'c0000000-0000-4000-8000-000000000009','d0000000-0000-4000-8000-000000000001','{"choice_id":"WRONG"}',1);
select 'next_version='||app.next_change_version('a0000000-0000-4000-8000-000000000001');
select 'next_version='||app.next_change_version('a0000000-0000-4000-8000-000000000001');
update app.account_sync_state set current_version = 0;
insert into app.audit_events(actor_id,actor_kind,action,outcome) values ('a0000000-0000-4000-8000-000000000001','staff','publish.pack','allowed');
commit;
select 'C01 v0.2: attempts with score 1 forged by the student role (DRAFT question, wrong answer)='||count(*) from app.practice_attempts where score=1;
select 'C01 v0.2: change version after the student role rewound it='||current_version from app.account_sync_state;
select 'C01 v0.2: audit rows with actor_kind=staff written by the student role='||count(*) from app.audit_events where actor_kind='staff';
select 'C10 v0.2: existing app functions executable by PUBLIC='||count(*) from pg_proc p where p.pronamespace='app'::regnamespace and has_function_privilege('public', p.oid, 'EXECUTE');
create function app.future_fn() returns int language sql as 'select 1';
select 'C10 v0.2: a NEW app function is executable by PUBLIC='||has_function_privilege('public','app.future_fn()','EXECUTE');
