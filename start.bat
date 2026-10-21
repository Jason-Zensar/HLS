@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title CTPIP launcher

rem ---- 0. settings from .env ------------------------------------------------------------
if not exist ".env" ( echo [!] .env missing - copy .env.example to .env and set NEO4J_PASSWORD & pause & exit /b 1 )
set "PORT=8000"
set "AI_ENABLED=true"
set "AI_MODEL=qwen2.5:3b"
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
  if /i "%%A"=="NEO4J_HOME" set "NEO4J_HOME=%%B"
  if /i "%%A"=="NEO4J_JAVA_HOME" set "NEO4J_JAVA_HOME=%%B"
  if /i "%%A"=="BACKEND_PORT" if not "%%B"=="" set "PORT=%%B"
  if /i "%%A"=="AI_ENABLED" if not "%%B"=="" set "AI_ENABLED=%%B"
  if /i "%%A"=="AI_MODEL" if not "%%B"=="" set "AI_MODEL=%%B"
)

rem ---- 1. Neo4j --------------------------------------------------------------------
powershell -NoProfile -Command "if ((Test-NetConnection 127.0.0.1 -Port 7687 -WarningAction SilentlyContinue).TcpTestSucceeded) { exit 0 } else { exit 1 }"
if errorlevel 1 (
  if defined NEO4J_HOME (
    echo [*] Starting Neo4j from %NEO4J_HOME%
    start "Neo4j" cmd /c "set JAVA_HOME=%NEO4J_JAVA_HOME%&& "%NEO4J_HOME%\bin\neo4j.bat" console"
    echo [*] Waiting for Neo4j on port 7687...
    powershell -NoProfile -Command "for($i=0;$i -lt 90;$i++){ if((Test-NetConnection 127.0.0.1 -Port 7687 -WarningAction SilentlyContinue).TcpTestSucceeded){exit 0}; Start-Sleep 2 }; exit 1"
    if errorlevel 1 ( echo [!] Neo4j did not start & pause & exit /b 1 )
  ) else ( echo [!] Neo4j is not running and NEO4J_HOME is not set in .env & pause & exit /b 1 )
) else ( echo [*] Neo4j already running )

rem ---- 2. Local AI with Ollama (optional; everything else works without it) ----------------
if /i not "%AI_ENABLED%"=="false" (
  where ollama >nul 2>nul
  if errorlevel 1 (
    echo [i] Local AI: Ollama is not installed. AI explanations are optional - install it from https://ollama.com and run start.bat again.
  ) else (
    powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try{$c.Connect([Net.IPAddress]::Loopback,11434);$c.Close();exit 0}catch{exit 1}"
    if errorlevel 1 (
      echo [*] Starting Ollama on port 11434
      start "Ollama" /min ollama serve
      powershell -NoProfile -Command "for($i=0;$i -lt 30;$i++){ $c=New-Object Net.Sockets.TcpClient; try{$c.Connect([Net.IPAddress]::Loopback,11434);$c.Close();exit 0}catch{Start-Sleep 1} }; exit 1"
    )
    ollama list 2>nul | findstr /i /c:"%AI_MODEL%" >nul
    if errorlevel 1 (
      echo [?] The AI model %AI_MODEL% is not installed yet ^(qwen2.5:3b is about a 2 GB download^).
      choice /C YN /T 20 /D N /M "    Download it now"
      if !errorlevel! EQU 1 ( ollama pull %AI_MODEL% ) else ( echo [i] Skipped. You can download it later on the Settings page. )
    ) else ( echo [*] Local AI ready: %AI_MODEL% )
  )
)

rem ---- 3. Python environment ----------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo [*] Creating Python virtual environment
  python -m venv .venv || ( echo [!] Python 3.11+ required & pause & exit /b 1 )
  ".venv\Scripts\python" -m pip install --upgrade pip
  ".venv\Scripts\pip" install -r backend\requirements.txt || ( pause & exit /b 1 )
)

rem ---- 4. Free port for the backend (another program may already use 8000) ------------
set "WANT=%PORT%"
for /f %%P in ('powershell -NoProfile -Command "$p=%PORT%; while($p -lt %PORT%+30){ $c=New-Object Net.Sockets.TcpClient; try{ $c.Connect([Net.IPAddress]::Loopback,$p); $c.Close(); $p++ } catch { break } }; $p"') do set "PORT=%%P"
if not "%PORT%"=="%WANT%" echo [i] Port %WANT% is used by another program - CTPIP will use port %PORT% instead.

rem ---- 5. Frontend ---------------------------------------------------------------------
if not exist "frontend\node_modules" ( pushd frontend & call npm install & popd )
if /i "%1"=="dev" (
  start "CTPIP frontend (dev)" cmd /k "set CTPIP_API_PORT=%PORT%&& cd frontend && npm run dev"
  set "URL=http://127.0.0.1:5173"
) else (
  if not exist "frontend\dist\index.html" ( pushd frontend & call npm run build & popd )
  set "URL=http://127.0.0.1:%PORT%"
)

rem ---- 6. Backend (API + background ingestion worker) -------------------------------------
if not exist "data\logs" mkdir "data\logs"
if not exist "data\ctpip.sqlite3" echo [i] First start: the protocol PDFs in the dataset folders are read automatically ^(about 30-60 minutes^). You can use the app meanwhile.
start "CTPIP backend" cmd /k "cd backend && ..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%"
powershell -NoProfile -Command "for($i=0;$i -lt 90;$i++){ try{ $r=Invoke-WebRequest http://127.0.0.1:%PORT%/api/health -UseBasicParsing -TimeoutSec 2; if($r.Content -match 'database'){exit 0} } catch { }; Start-Sleep 1 }; exit 1"
if errorlevel 1 ( echo [!] The backend did not answer - read the "CTPIP backend" window for the error. & pause & exit /b 1 )
echo [*] CTPIP running at !URL!   (API docs: http://127.0.0.1:%PORT%/docs)
start "" "!URL!"
endlocal
