from sqlalchemy import ForeignKeyConstraint, create_mock_engine


def test_metadata_contains_all_storage_tables():
    from fitcheck_backend.storage.models import Base
    assert set(Base.metadata.tables) == {"owners", "users", "guests", "auth_sessions", "auth_tokens", "auth_rate_buckets", "profiles", "profile_revisions", "preferences", "drafts", "vacancies", "jobs", "analyses", "analysis_annotations", "quota_buckets", "quota_reservations", "provider_calls", "import_entries"}
    statements = []
    engine = create_mock_engine("postgresql+psycopg://", lambda sql, *args, **kwargs: statements.append(str(sql.compile(dialect=engine.dialect))))
    Base.metadata.create_all(engine)
    assert any("FOREIGN KEY(job_id, owner_id, job_type)" in stmt for stmt in statements)


def test_owner_links_are_composite():
    from fitcheck_backend.storage.models import Base
    table = Base.metadata.tables["analyses"]
    constraints = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
    assert any(list(c.column_keys) == ["vacancy_id", "owner_id"] and c.deferrable for c in constraints)
    assert any(list(c.column_keys) == ["job_id", "owner_id", "job_type"] and c.deferrable for c in constraints)


def test_nullable_links_have_explicit_rules():
    from fitcheck_backend.storage.models import Base
    from sqlalchemy import CheckConstraint
    checks = " ".join(str(c.sqltext) for c in Base.metadata.tables["analyses"].constraints if isinstance(c, CheckConstraint))
    assert "job_id IS NULL" in checks and "job_type IS NULL" in checks
    assert not Base.metadata.tables["analyses"].c.owner_id.nullable
