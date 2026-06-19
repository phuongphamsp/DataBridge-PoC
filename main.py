"""
DataBridge PoC - Railway entry point
Adds poc/src to sys.path then runs the FastAPI app from poc/web/api.py
"""
import sys
import os
from pathlib import Path

# Make poc/src importable as normal Python packages
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "poc"))
sys.path.insert(0, str(ROOT / "poc" / "src"))

# Set working dirs so api.py can find static files and output dir
os.environ.setdefault("DATABRIDGE_ROOT", str(ROOT))

# Import the app from poc/web/api.py
# On Linux (Railway) there is no file-lock bug, so direct import works fine
import importlib.util, types

spec = importlib.util.spec_from_file_location("api", ROOT / "poc" / "web" / "api.py")
_api_module = importlib.util.module_from_spec(spec)
sys.modules["api"] = _api_module
spec.loader.exec_module(_api_module)

app = _api_module.app
