from peewee import (
    Model,
    BinaryUUIDField,
    BooleanField,
    CharField,
    IntegerField,
    DateField,
    CompositeKey,
    DateTimeField,
    ForeignKeyField,
    OperationalError,
    TextField,
    UUIDField,
    fn,
)
import uuid
import datetime
from urllib.parse import parse_qs, unquote, urlparse
from playhouse.sqlite_ext import SqliteExtDatabase, JSONField
from playhouse.migrate import SqliteMigrator, migrate
from openui import config

POSTGRES = config.DATABASE_URL is not None

if POSTGRES:
    from peewee import PostgresqlDatabase
    from playhouse.postgres_ext import BinaryJSONField

    # Connections are opened lazily and closed at the end of every request (see
    # DatabaseConnectionMiddleware in server.py) so that a serverless function
    # never holds a pooler slot while idle. psycopg2 uses the simple query
    # protocol (no server side prepared statements), which is what transaction
    # mode poolers (Supavisor / pgbouncer) require.
    def _parse_database_url(url: str) -> dict:
        # playhouse.db_url doesn't percent-decode credentials, and generated
        # Supabase passwords often need encoding in a URL.
        parsed = urlparse(url)
        if parsed.scheme not in ("postgres", "postgresql"):
            raise RuntimeError("DATABASE_URL must be a postgresql:// URL")
        kwargs = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        kwargs["database"] = unquote(parsed.path.lstrip("/")) or "postgres"
        if parsed.username:
            kwargs["user"] = unquote(parsed.username)
        if parsed.password:
            kwargs["password"] = unquote(parsed.password)
        if parsed.hostname:
            kwargs["host"] = parsed.hostname
        if parsed.port:
            kwargs["port"] = parsed.port
        return kwargs

    _db_kwargs = _parse_database_url(config.DATABASE_URL)
    _db_name = _db_kwargs.pop("database")
    _db_kwargs.setdefault("connect_timeout", config.DB_CONNECT_TIMEOUT)
    database = PostgresqlDatabase(_db_name, autoconnect=True, **_db_kwargs)
    migrator = None
    JSONColumn = BinaryJSONField

    class IdField(UUIDField):
        """Native uuid column. Accepts the 16 raw bytes the rest of the code
        base passes around (the SQLite schema stores uuids as blobs)."""

        def db_value(self, value):
            if isinstance(value, (bytes, bytearray, memoryview)):
                value = uuid.UUID(bytes=bytes(value))
            return super().db_value(value)

else:
    database = SqliteExtDatabase(
        config.DB,
        pragmas=(
            ("cache_size", -1024 * 64),  # 64MB page-cache.
            ("journal_mode", "wal"),  # Use WAL-mode
            ("foreign_keys", 1),
        ),
    )
    migrator = SqliteMigrator(database)
    JSONColumn = JSONField
    IdField = BinaryUUIDField


def _table(sqlite_name: str, postgres_name: str) -> str:
    # "user" is a reserved word in Postgres, so the Postgres schema uses plural
    # table names. Existing SQLite databases keep their original names.
    return postgres_name if POSTGRES else sqlite_name


class BaseModel(Model):
    class Meta:
        database = database


class SchemaMigration(BaseModel):
    version = CharField()

    class Meta:
        table_name = _table("schemamigration", "schema_migration")


class User(BaseModel):
    id = IdField(primary_key=True)
    username = CharField(unique=True)
    email = CharField(null=True)
    created_at = DateTimeField()

    class Meta:
        table_name = _table("user", "users")


class Credential(BaseModel):
    credential_id = CharField(primary_key=True)
    public_key = CharField()
    sign_count = IntegerField()
    aaguid = CharField(null=True)
    user_verified = BooleanField(default=False)
    user = ForeignKeyField(User, backref="credentials")

    class Meta:
        table_name = _table("credential", "credentials")


class Session(BaseModel):
    id = IdField(primary_key=True)
    user = ForeignKeyField(User, backref="sessions")
    data = JSONColumn()
    created_at = DateTimeField()
    updated_at = DateTimeField()

    class Meta:
        table_name = _table("session", "sessions")


class Component(BaseModel):
    id = IdField(primary_key=True)
    name = CharField()
    user = ForeignKeyField(User, backref="components")
    data = JSONColumn()

    class Meta:
        table_name = _table("component", "components")


class Vote(BaseModel):
    id = IdField(primary_key=True)
    user = ForeignKeyField(User, backref="votes")
    component = ForeignKeyField(Component, backref="votes")
    vote = BooleanField()
    created_at = DateTimeField()

    class Meta:
        table_name = _table("vote", "votes")


class Share(BaseModel):
    """Shared components. Used instead of S3 when no bucket is configured."""

    id = CharField(primary_key=True, max_length=64)
    data = TextField()
    created_at = DateTimeField(default=datetime.datetime.now)

    class Meta:
        table_name = _table("share", "shares")


class Usage(BaseModel):
    input_tokens = IntegerField()
    output_tokens = IntegerField()
    day = DateField()
    user = ForeignKeyField(User, backref="usage")

    class Meta:
        primary_key = CompositeKey("user", "day")
        table_name = _table("usage", "usage")

    @classmethod
    def update_tokens(cls, user_id: str, input_tokens: int, output_tokens: int):
        Usage.insert(
            user_id=uuid.UUID(user_id).bytes,
            day=datetime.datetime.now().date(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ).on_conflict(
            conflict_target=[Usage.user_id, Usage.day],
            update={
                Usage.input_tokens: Usage.input_tokens + input_tokens,
                Usage.output_tokens: Usage.output_tokens + output_tokens,
            },
        ).execute()

    @classmethod
    def tokens_since(cls, user_id: str, day: datetime.date) -> int:
        return (
            Usage.select(
                fn.SUM(Usage.input_tokens + Usage.output_tokens).alias("tokens")
            )
            .where(Usage.user_id == uuid.UUID(user_id).bytes, Usage.day >= day)
            .get()
            .tokens
            or 0
        )


CURRENT_VERSION = "2024-05-14"


def alter(schema: SchemaMigration, ops: list[list], version: str) -> bool:
    try:
        migrate(*ops)
    except OperationalError as e:
        print("Migration failed", e)
        return False
    schema.version = version
    schema.save()
    print(f"Migrated {version}")
    return version != CURRENT_VERSION


def perform_migration(schema: SchemaMigration) -> bool:
    if schema.version == "2024-03-08":
        version = "2024-03-12"
        aaguid = CharField(null=True)
        user_verified = BooleanField(default=False)
        altered = alter(
            schema,
            [
                migrator.add_column("credential", "aaguid", aaguid),
                migrator.add_column("credential", "user_verified", user_verified),
            ],
            version,
        )
        if altered:
            perform_migration(schema)
    if schema.version == "2024-03-12":
        version = "2024-05-14"
        database.create_tables([Vote])
        schema.version = version
        schema.save()
        if version != CURRENT_VERSION:
            perform_migration(schema)


ALL_TABLES = [
    User,
    Credential,
    Session,
    Component,
    SchemaMigration,
    Usage,
    Vote,
    Share,
]


def _postgres_tables_exist() -> bool:
    return all(database.table_exists(model._meta.table_name) for model in ALL_TABLES)


def ensure_migrated():
    if POSTGRES:
        # The canonical schema lives in backend/migrations/001_init.sql (run it in
        # the Supabase SQL editor). peewee's create_tables(safe=True) is not a
        # no-op: it still issues CREATE INDEX on existing tables, which requires
        # table ownership and fails when the tables were created by another role
        # (e.g. postgres). Skip DDL when the schema is already present.
        if not _postgres_tables_exist():
            database.create_tables(ALL_TABLES, safe=True)
        if SchemaMigration.select().first() is None:
            SchemaMigration.create(version=CURRENT_VERSION)
        return
    if not config.DB.exists():
        database.create_tables(ALL_TABLES)
        SchemaMigration.create(version=CURRENT_VERSION)
    else:
        schema = SchemaMigration.select().first()
        if schema.version != CURRENT_VERSION:
            perform_migration(schema)
        # Shares table was added after the first public release
        database.create_tables([Share], safe=True)
