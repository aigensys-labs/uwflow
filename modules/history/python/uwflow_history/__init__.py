"""UWflow historical-data connectors and replay contracts.

This package is deliberately outside the underwriting runtime. Kestra invokes
its command-line tools; it does not own data access, synthetic generation, or
underwriting calculations.
"""

__version__ = "0.1.0"

from .contracts import DatasetManifest, HistoricalCase, HistoricalDataSink, HistoricalDataSource

__all__ = [
    "DatasetManifest",
    "HistoricalCase",
    "HistoricalDataSink",
    "HistoricalDataSource",
    "__version__",
]
