"""Core maintainer entry point for compiling canonical policy specifications.

The maintained implementation lives in :mod:`tools.policy.compiler`. This
small entry point remains the command recorded in the immutable generated Core
runtime; new platform workflows should invoke the maintained module directly.
"""

from tools.policy.compiler import main

if __name__ == "__main__":
    raise SystemExit(main())
