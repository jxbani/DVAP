"""The operator agent's long-term memory.

The implementation lives in `dvap_common.memory` so mcp-plant (which serves the
remember/recall tools and owns the SQLite file) can reuse it without copying this
package into its image. This module is the memory's home in the agent package.
"""

from dvap_common.memory import MemoryStore

__all__ = ["MemoryStore"]
