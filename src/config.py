import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


@dataclass
class Config:
    tenant_id: str
    client_id: str
    client_secret: str
    mailbox_user: str
    subject_keyword: str
    poll_lookback_days: int
    tracker_seed_xlsx: str
    tracker_xlsx_path: str
    tracker_sheet_name_template: str
    state_file: str
    log_level: str

    def tracker_sheet_name(self, year: int) -> str:
        return self.tracker_sheet_name_template.format(year=year)


def load_config() -> Config:
    return Config(
        tenant_id=_require("AZURE_TENANT_ID"),
        client_id=_require("AZURE_CLIENT_ID"),
        client_secret=_require("AZURE_CLIENT_SECRET"),
        mailbox_user=_require("MAILBOX_USER"),
        subject_keyword=os.environ.get("SUBJECT_KEYWORD", "NEW EASTMAN CHEMICAL DOCUMENT"),
        poll_lookback_days=int(os.environ.get("POLL_LOOKBACK_DAYS", "7")),
        tracker_seed_xlsx=os.environ.get("TRACKER_SEED_XLSX", "./data/EASTMAN_ORDER_STATUS_seed.xlsx"),
        tracker_xlsx_path=os.environ.get("TRACKER_XLSX_PATH", "./data/EASTMAN_ORDER_STATUS_tracker.xlsx"),
        tracker_sheet_name_template=os.environ.get("TRACKER_SHEET_NAME", "Incoming vessels-{year}"),
        state_file=os.environ.get("STATE_FILE", "./data/processed_messages.json"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
