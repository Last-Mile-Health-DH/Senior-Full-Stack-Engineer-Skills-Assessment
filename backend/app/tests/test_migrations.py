from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


def migration_engine() -> Engine:
    url = alembic_config().get_main_option("sqlalchemy.url")
    return create_engine(url)


def test_alembic_upgrade_head_and_downgrade_base_cleanly() -> None:
    config = alembic_config()
    command.downgrade(config, "base")

    command.upgrade(config, "head")
    with migration_engine().connect() as connection:
        current_revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        table_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'documents',
                    'chunks',
                    'page_images',
                    'chat_sessions',
                    'chat_messages',
                    'exact_cache',
                    'semantic_cache',
                    'query_audit_log',
                    'agent_trace_log',
                    'response_grade',
                    'anomaly_flag',
                    'gold_eval_run',
                    'gold_eval_result'
                  )
                """
            )
        ).scalar_one()
        view_exists = connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.views
                    WHERE table_schema = 'public'
                      AND table_name = 'agentops_summary'
                )
                """
            )
        ).scalar_one()

    client_ip_exists = False
    with migration_engine().connect() as connection:
        client_ip_exists = connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'query_audit_log'
                      AND column_name = 'client_ip'
                      AND udt_name = 'inet'
                )
                """
            )
        ).scalar_one()

    assert current_revision == "0016_sem_cache_no_default"
    assert table_count == 13
    assert view_exists is True
    assert client_ip_exists is True

    command.downgrade(config, "base")
    with migration_engine().connect() as connection:
        remaining_tables = connection.execute(
            text(
                """
                SELECT count(*)
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'documents',
                    'chunks',
                    'page_images',
                    'chat_sessions',
                    'chat_messages',
                    'exact_cache',
                    'semantic_cache',
                    'query_audit_log',
                    'agent_trace_log',
                    'response_grade',
                    'anomaly_flag',
                    'gold_eval_run',
                    'gold_eval_result'
                  )
                """
            )
        ).scalar_one()
        view_exists_after_downgrade = connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.views
                    WHERE table_schema = 'public'
                      AND table_name = 'agentops_summary'
                )
                """
            )
        ).scalar_one()

    assert remaining_tables == 0
    assert view_exists_after_downgrade is False
