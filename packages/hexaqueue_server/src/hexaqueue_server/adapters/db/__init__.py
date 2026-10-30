"""Database and columnar persistence adapters for Hexaqueue Server.

Notes/Architectural Intent:
    Provides zero-copy columnar query projection adapters using Polars and Apache Arrow,
    supporting high-speed analytical dashboards and binary tabular telemetry exports.
"""

from hexaqueue_server.adapters.db.analytics import ColumnarAnalyticsAdapter

__all__ = [
    "ColumnarAnalyticsAdapter",
]
