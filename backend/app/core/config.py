from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings


ROOT_DIR = Path(__file__).resolve().parents[3]
TOOLS_BIN = ROOT_DIR / "tools" / "node_modules" / ".bin" / "promptfoo"


class Settings(BaseSettings):
    app_name: str = "EvalKit"
    api_prefix: str = "/api"
    # Keep runtime artifacts outside backend/ so uvicorn --reload ignores them.
    data_dir: Path = ROOT_DIR / "data"
    promptfoo_bin: Optional[str] = None
    promptfoo_args: List[str] = []
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]

    def resolve_promptfoo_cmd(self) -> List[str]:
        if self.promptfoo_bin:
            return [self.promptfoo_bin, *self.promptfoo_args]
        if TOOLS_BIN.exists():
            return [str(TOOLS_BIN)]
        return ["npx", "--yes", "promptfoo@0.125.1"]

    @property
    def configs_dir(self) -> Path:
        return self.data_dir / "configs"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


settings = Settings()
for path in (settings.configs_dir, settings.runs_dir, settings.reports_dir):
    path.mkdir(parents=True, exist_ok=True)
