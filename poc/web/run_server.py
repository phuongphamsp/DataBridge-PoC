"""
DataBridge PoC - Server bootstrap (Python 3.14 workaround)
Usage:  python D:\DataBridge-PoC\poc\web\run_server.py
"""
import os, base64, types, sys, pathlib

SRC_DIR = pathlib.Path(__file__).parent.parent / "src"
WEB_DIR = pathlib.Path(__file__).parent

FILES = {
    "DATABRIDGE_TRE_PARSER":     SRC_DIR / "parsers/tre_parser.py",
    "DATABRIDGE_SST_INPUT":      SRC_DIR / "models/sst_input.py",
    "DATABRIDGE_SST_MAPPER":     SRC_DIR / "mappers/sst_mapper.py",
    "DATABRIDGE_SST_PLAYWRIGHT": SRC_DIR / "integration/sst_playwright.py",
    "DATABRIDGE_SST_API":        SRC_DIR / "integration/sst_api.py",
    "DATABRIDGE_API":            WEB_DIR / "api.py",
}

print("=== DataBridge PoC Server ===")
for key, path in FILES.items():
    data = path.read_bytes()
    os.environ[key] = base64.b64encode(data).decode()
    print(f"  Loaded: {path.name} ({len(data)} bytes)")

print("\nStarting at http://localhost:8000  (Ctrl+C to stop)\n")

api_code = base64.b64decode(os.environ["DATABRIDGE_API"]).decode("utf-8")
m = types.ModuleType("api")
m.__file__ = str(WEB_DIR / "api.py")
exec(compile(api_code, "api.py", "exec"), m.__dict__)

import uvicorn
uvicorn.run(m.app, host="0.0.0.0", port=8000, log_level="info")
