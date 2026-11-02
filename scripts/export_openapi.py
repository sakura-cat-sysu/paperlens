"""从真实 API 导出契约，前端类型只由此生成。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import app  # noqa: E402

print(json.dumps(app.openapi(), ensure_ascii=False))
