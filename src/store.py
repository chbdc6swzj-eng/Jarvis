import json
import logging
import os

logger = logging.getLogger(__name__)


class ProcessedStore:
    """Tracks which email message IDs have already produced a tracker row,
    so re-running the cron job never creates duplicate entries.
    """

    def __init__(self, path: str):
        self.path = path
        self._ids: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                self._ids = set(json.load(f))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read state file %s (%s); starting fresh", self.path, exc)

    def is_processed(self, message_id: str) -> bool:
        return message_id in self._ids

    def mark_processed(self, message_id: str) -> None:
        self._ids.add(message_id)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(sorted(self._ids), f, indent=2)
