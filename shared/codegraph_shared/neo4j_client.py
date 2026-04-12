"""Async Neo4j client wrapper.

Provides a thin, typed interface over the official ``neo4j`` async driver.
All methods use explicit transactions so callers never manage sessions directly.
"""

from __future__ import annotations
from typing import Any
from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession
from .exceptions import GraphQueryError, GraphWriteError
from .logging import get_logger

logger = get_logger(__name__)

class Neo4jClient:
    """Async Neo4j driver wrapper with connection lifecycle management.

    Args:
        uri: Bolt URI (e.g. ``bolt://neo4j:7687``).
        user: Database username.
        password: Database password.
        max_pool_size: Maximum number of connections in the pool.
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        *,
        max_pool_size: int = 50,
    ) -> None:
        self._uri = uri
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=max_pool_size,
        )

    async def verify_connectivity(self) -> None:
        """Raise if the database is unreachable."""
        await self._driver.verify_connectivity()
        logger.info("neo4j_connected", uri=self._uri)

    def session(self) -> AsyncSession:
        return self._driver.session()

    async def execute_read(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Run a read query and return all rows as plain dicts.

        Args:
            query: Cypher query string.
            params: Named query parameters.

        Returns:
            List of record dicts.

        Raises:
            GraphQueryError: If the query fails.
        """
        try:
            async with self.session() as session:
                result = await session.execute_read(
                    run_query, query, params or {}
                )
                return result
        except Exception as exc:
            logger.error("neo4j_read_failed", query=query[:200], error=str(exc))
            raise GraphQueryError(f"Read query failed: {exc}") from exc

    async def execute_write(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Run a write query inside an implicit write transaction.

        Args:
            query: Cypher query string (must contain write clauses).
            params: Named query parameters.

        Raises:
            GraphWriteError: If the write fails.
        """
        try:
            async with self.session() as session:
                await session.execute_write(run_query, query, params or {})
        except Exception as exc:
            logger.error("neo4j_write_failed", query=query[:200], error=str(exc))
            raise GraphWriteError(f"Write query failed: {exc}") from exc

    async def execute_write_batch(
        self,
        query: str,
        batch: list[dict[str, Any]],
        chunk_size: int = 500,
    ) -> None:
        """Write a list of records using UNWIND batching for performance.

        Args:
            query: Cypher query that uses ``$batch`` as the UNWIND parameter.
            batch: List of parameter dicts to pass as the ``batch`` value.
            chunk_size: How many records to send per transaction.
        """
        for i in range(0, len(batch), chunk_size):
            chunk = batch[i : i + chunk_size]
            await self.execute_write(query, {"batch": chunk})

    async def close(self) -> None:
        """Close all connections in the pool."""
        await self._driver.close()
        logger.info("neo4j_closed")


async def run_query(
    tx: Any,
    query: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Transaction function used by both read and write helpers."""
    result = await tx.run(query, params)
    records = await result.data()
    return records
