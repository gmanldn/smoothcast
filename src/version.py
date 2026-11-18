"""SmoothCast version counter — increment the patch (x.y.Z) on every commit.

The version is formatted as ``1.0.x`` where ``x`` is the build/patch number.
Bump this number on every meaningful commit so the running build is always
traceable to a specific point in history.
"""

MAJOR = 1
MINOR = 0
PATCH = 31

__version__ = f"{MAJOR}.{MINOR}.{PATCH}"
