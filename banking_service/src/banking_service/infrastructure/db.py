from importlib import resources

from psycopg_pool import ConnectionPool


def build_pool(database_url: str, *, min_size: int, max_size: int) -> ConnectionPool:
    return ConnectionPool(conninfo=database_url, min_size=min_size, max_size=max_size, open=True)


def apply_schema(pool: ConnectionPool) -> None:
    sql = resources.files("banking_service.infrastructure").joinpath("schema.sql").read_text()
    with pool.connection() as conn:
        conn.execute(sql)
