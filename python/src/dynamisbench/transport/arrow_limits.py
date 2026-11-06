"""Cross-language resource budgets for the application's Arrow IPC reader.

These caps are deliberately stricter than the IPC format's representable dimensions. They
bound work before PyArrow or the browser Arrow reader constructs arrays or Python/JS row
objects. Keep the matching TypeScript constants in ``apps/workbench/src/arrow/arrow.ts`` in
sync; the frozen cross-language fixture remains the compatibility contract.
"""

from typing import Final

MAX_ARROW_IPC_BYTES: Final = 1 * 1024 * 1024
MAX_ARROW_ROWS: Final = 100_000
MAX_ARROW_COLUMNS: Final = 256
MAX_ARROW_FIELD_NODES: Final = 512
MAX_ARROW_LOGICAL_VALUES: Final = 250_000
MAX_ARROW_DECODED_BYTES: Final = 8 * 1024 * 1024
MAX_ARROW_MESSAGE_METADATA_BYTES: Final = 256 * 1024
MAX_ARROW_TOTAL_METADATA_BYTES: Final = 512 * 1024
MAX_ARROW_MESSAGES: Final = 128
MAX_ARROW_RECORD_BATCHES: Final = 64
MAX_ARROW_FIELD_DEPTH: Final = 16
MAX_ARROW_BUFFERS: Final = 4_096
MAX_ARROW_METADATA_ENTRIES: Final = 256
MAX_ARROW_FIELD_NAME_BYTES: Final = 1_024
MAX_ARROW_METADATA_STRING_BYTES: Final = 16 * 1024

__all__ = [
    "MAX_ARROW_BUFFERS",
    "MAX_ARROW_COLUMNS",
    "MAX_ARROW_DECODED_BYTES",
    "MAX_ARROW_FIELD_DEPTH",
    "MAX_ARROW_FIELD_NAME_BYTES",
    "MAX_ARROW_FIELD_NODES",
    "MAX_ARROW_IPC_BYTES",
    "MAX_ARROW_LOGICAL_VALUES",
    "MAX_ARROW_MESSAGE_METADATA_BYTES",
    "MAX_ARROW_MESSAGES",
    "MAX_ARROW_METADATA_ENTRIES",
    "MAX_ARROW_METADATA_STRING_BYTES",
    "MAX_ARROW_RECORD_BATCHES",
    "MAX_ARROW_ROWS",
    "MAX_ARROW_TOTAL_METADATA_BYTES",
]
