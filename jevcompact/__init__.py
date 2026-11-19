"""JevCompact: Session Compaction using Jev."""
from .config import PRESETS, CompactionConfig
from .formats import FormatError, detect_format, parse_session, user_messages_lost
from .judges import Judge, JudgeError, MockJudge
from .middleware import JevCompactMiddleware
from .models import CompactionResult, Decision, SummaryInfo
from .pipeline import CompactionError, compact, compact_sync, restore_item
from .recall import MemoryRecallStore, SqliteRecallStore, recall
from .report import export_json, report_csv, savings_report
from .summarizers import MockSummarizer, Summarizer

__all__ = [
    "PRESETS", "CompactionConfig", "CompactionResult", "Decision", "SummaryInfo",
    "compact", "compact_sync", "restore_item", "recall", "JevCompactMiddleware",
    "Judge", "JudgeError", "MockJudge", "Summarizer", "MockSummarizer",
    "MemoryRecallStore", "SqliteRecallStore", "FormatError", "CompactionError",
    "detect_format", "parse_session", "user_messages_lost",
    "export_json", "report_csv", "savings_report",
]
__version__ = "0.1.0"
