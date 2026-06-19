"""
DataBridge PoC - Server Launcher (run_server.py)
Usage: python run_server.py
"""
import os, base64, subprocess, sys
from pathlib import Path

ROOT   = Path(__file__).parent
SRC    = ROOT / "src"
WEB    = ROOT / "web"

FILES = {
    "DATABRIDGE_TRE_PARSER":     SRC / "parsers"     / "tre_parser.py",
    "DATABRIDGE_SST_INPUT":      SRC / "models"      / "sst_input.py",
    "DATABRIDGE_SST_MAPPER":     SRC / "mappers"     / "sst_mapper.py",
    "DATABRIDGE_SST_PLAYWRIGHT": SRC / "integration" / "sst_playwright.py",
    "DATABRIDGE_API":            WEB / "api.py",
}

print("=== DataBridge PoC Server ===")
for key, path in FILES.items():
    data = path.read_bytes()
    os.environ[key] = base64.b64encode(data).decode()
    print(f"  Loaded: {path.name} ({len(data)} bytes)")

print("\nStarting server at http://localhost:8000")
print("Press Ctrl+C to stop.\n")

bootstrap = (
    "import os,base64,types,sys;"
    "code=base64.b64decode(os.environ['DATABRIDGE_API']).decode();"
    "m=types.ModuleType('api');"
    "m.__file__=r'" + str(WEB / 'api.py').replace('\\','\\\\') + "';"
    "exec(compile(code,'api.py','exec'),m.__dict__);"
    "import uvicorn;"
    "uvicorn.run(m.app,host='0.0.0.0',port=8000,log_level='info')"
)

os.chdir(WEB)
os.execv(sys.executable, [sys.executable, "-c", bootstrap])