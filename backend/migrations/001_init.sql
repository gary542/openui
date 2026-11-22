-- OpenUI schema for Supabase / Postgres.
--
-- Run once in the Supabase SQL editor (or: psql "$DIRECT_DATABASE_URL" -f 001_init.sql).
-- It matches the peewee models in backend/openui/db/models.py. The backend also
-- runs CREATE TABLE IF NOT EXISTS on first use, so this file is the canonical,
-- reviewable version rather than a hard requirement. Safe to re-run.

create table if not exists schema_migration (
    id          serial primary key,
    version     varchar(255) not null
);

create table if not exists users (
    id          uuid primary key,
    username    varchar(255) not null unique,
    email       varchar(255),
    created_at  timestamp not null
);

create table if not exists credentials (
    credential_id  varchar(255) primary key,
    public_key     varchar(255) not null,
    sign_count     integer not null,
    aaguid         varchar(255),
    user_verified  boolean not null default false,
    user_id        uuid not null references users (id)
);
create index if not exists credentials_user_id on credentials (user_id);

create table if not exists sessions (
    id          uuid primary key,
    user_id     uuid not null references users (id),
    data        jsonb not null,
    created_at  timestamp not null,
    updated_at  timestamp not null
);
create index if not exists sessions_user_id on sessions (user_id);

create table if not exists components (
    id       uuid primary key,
    name     varchar(255) not null,
    user_id  uuid not null references users (id),
    data     jsonb not null
);
create index if not exists components_user_id on components (user_id);

create table if not exists votes (
    id            uuid primary key,
    user_id       uuid not null references users (id),
    component_id  uuid not null references components (id),
    vote          boolean not null,
    created_at    timestamp not null
);
create index if not exists votes_user_id on votes (user_id);
create index if not exists votes_component_id on votes (component_id);

-- Per user, per day token usage (powers the 24h quota, OPENUI_MAX_TOKENS)
create table if not exists usage (
    user_id        uuid not null references users (id),
    day            date not null,
    input_tokens   integer not null,
    output_tokens  integer not null,
    primary key (user_id, day)
);

-- Shared components (used instead of S3)
create table if not exists shares (
    id          varchar(64) primary key,
    data        text not null,
    created_at  timestamp not null default now()
);

-- Supabase exposes the public schema through its REST API (PostgREST) using the
-- anon / authenticated keys. Enable RLS so that API has no access without
-- policies. The app connects as openui_app; grant that role DML and an
-- openui_app_all policy (see the role setup SQL), then transfer ownership below
-- so optional app-side DDL can run. anon/authenticated still have no policies.
alter table schema_migration enable row level security;
alter table users            enable row level security;
alter table credentials      enable row level security;
alter table sessions         enable row level security;
alter table components       enable row level security;
alter table votes            enable row level security;
alter table usage            enable row level security;
alter table shares           enable row level security;

insert into schema_migration (version)
select '2024-05-14'
where not exists (select 1 from schema_migration);

-- Transfer ownership to openui_app when that role exists. peewee may still
-- issue CREATE INDEX on first use; that requires table ownership. Safe to
-- re-run. PostgreSQL 16+ needs SET OPTION on the membership (GRANT ... WITH
-- SET TRUE) for ALTER ... OWNER TO to succeed.
do $$
declare
    t text;
begin
    if not exists (select 1 from pg_roles where rolname = 'openui_app') then
        return;
    end if;
    if not exists (
        select 1
        from pg_auth_members m
        join pg_roles r on r.oid = m.member
        join pg_roles g on g.oid = m.roleid
        where r.rolname = current_user
          and g.rolname = 'openui_app'
          and m.set_option
    ) then
        execute format(
            'grant openui_app to %I with set true, inherit false',
            current_user
        );
    end if;
    foreach t in array array[
        'schema_migration', 'users', 'credentials', 'sessions',
        'components', 'votes', 'usage', 'shares'
    ] loop
        execute format('alter table public.%I owner to openui_app', t);
    end loop;
end $$;

