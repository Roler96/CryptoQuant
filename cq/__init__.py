"""CQuant — causality-first crypto quant research platform.

Design invariant that motivates this whole tree: a strategy must not be able
to see data that did not exist at decision time.  That is enforced by the
`Context` API (physical slicing), not by review or by tests alone.
"""

__version__ = "0.1.0"
