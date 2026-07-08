"""PersistenceBackend implementations.

The protocol itself lives in moirai.protocols.PersistenceBackend. This
package holds concrete backends — MVP ships MemoryBackend only; file-based
persistence (SPEC.md §18) is post-MVP.
"""

from moirai.persistence.memory_backend import MemoryBackend

__all__ = ["MemoryBackend"]
