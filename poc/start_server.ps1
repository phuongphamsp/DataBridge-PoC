# DataBridge PoC - Server Launcher
# Reads locked src files via .NET, injects as env vars, starts uvicorn

$SrcDir = "D:\DataBridge-PoC\poc\src"
$WebDir = "D:\DataBridge-PoC\poc\web"

Write-Host "=== DataBridge PoC Server ===" -ForegroundColor Cyan
Write-Host "Reading source files..." -ForegroundColor Yellow

$srcFiles = @{
  "DATABRIDGE_TRE_PARSER"     = "$SrcDir\parsers\tre_parser.py"
  "DATABRIDGE_SST_INPUT"      = "$SrcDir\models\sst_input.py"
  "DATABRIDGE_SST_MAPPER"     = "$SrcDir\mappers\sst_mapper.py"
  "DATABRIDGE_SST_PLAYWRIGHT" = "$SrcDir\integration\sst_playwright.py"
  "DATABRIDGE_API"            = "$WebDir\api.py"
}

foreach ($key in $srcFiles.Keys) {
  $path  = $srcFiles[$key]
  $bytes = [System.IO.File]::ReadAllBytes($path)
  $b64   = [Convert]::ToBase64String($bytes)
  [System.Environment]::SetEnvironmentVariable($key, $b64, "Process")
  $env:($key) = $b64
  Write-Host "  Loaded: $([System.IO.Path]::GetFileName($path)) ($($bytes.Length) bytes)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Starting FastAPI server at http://localhost:8000" -ForegroundColor Cyan
Write-Host "Open your browser to: http://localhost:8000" -ForegroundColor White
Write-Host "Press Ctrl+C to stop." -ForegroundColor Gray
Write-Host ""

Set-Location $WebDir

# Launch via bootstrap loader (bypasses Python 3.14 file lock on .py files)
python -c "
import os, base64, types, sys, pathlib

# Load api.py from env var
code = base64.b64decode(os.environ['DATABRIDGE_API']).decode('utf-8')
m = types.ModuleType('api')
m.__file__ = r'D:/DataBridge-PoC/poc/web/api.py'
exec(compile(code, 'api.py', 'exec'), m.__dict__)

import uvicorn
uvicorn.run(m.app, host='0.0.0.0', port=8000, log_level='info')
"