"""bootstrap.py — Single import for all UWflow Kestra tasks.

Eliminates repetitive sys.path setup, Kestra import, and env access.
Every task script starts with:  from bootstrap import ctx
"""
import json
import os
import sys
from pathlib import Path


class _Ctx:
    """Task context: path setup + Kestra + env access."""
    
    def __init__(self):
        from kestra import Kestra
        self.kestra = Kestra

        # Re-export stdlib for convenience in task scripts
        self.json = json
        self.sys = sys
        self.os = os
        self.Path = Path        

    def env_json(self, name: str) -> dict:
        """Read a JSON environment variable."""
        return json.loads(os.environ[name])

    def env_str(self, name: str) -> str:
        """Read a plain string environment variable."""
        return os.environ[name]


ctx = _Ctx()