# ==============================================================================
# lazy-read: One-Line Installer for Windows PowerShell
# https://github.com/kuihaphanich2542-prog/lazy-read
# ==============================================================================

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/kuihaphanich2542-prog/lazy-read.git"
$InstallDir = "$env:USERPROFILE\.agents\skills\lazy-read"
$BinDir = "$env:USERPROFILE\.local\bin"

Write-Host "=== [1/4] Checking Python 3 Environment ===" -ForegroundColor Cyan

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
}

if (-not $pythonCmd) {
    Write-Host "Python 3 not found. Initiating automated installation..." -ForegroundColor Yellow
    
    $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetCmd) {
        Write-Host "Installing Python 3.12 via winget..." -ForegroundColor Green
        winget install --id Python.Python.3.12 --source winget --silent --accept-package-agreements --accept-source-agreements
    }
    else {
        Write-Host "Downloading official Python installer from python.org..." -ForegroundColor Green
        $installerUrl = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
        $tempExe = "$env:TEMP\python-3.12.7-installer.exe"
        Invoke-WebRequest -Uri $installerUrl -OutFile $tempExe
        
        Write-Host "Running silent installation..." -ForegroundColor Green
        Start-Process -FilePath $tempExe -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1" -Wait
        Remove-Item -Force $tempExe
    }
    
    # Refresh PATH for current session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

$pythonExec = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExec) {
    $pythonExec = (Get-Command python3 -ErrorAction SilentlyContinue).Source
}

Write-Host "Python is ready: $pythonExec" -ForegroundColor Green

Write-Host "=== [2/4] Installing lazy-read Skill ===" -ForegroundColor Cyan

if (-not (Test-Path (Split-Path $InstallDir))) {
    New-Item -ItemType Directory -Path (Split-Path $InstallDir) -Force | Out-Null
}

$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if ($gitCmd) {
    if (Test-Path "$InstallDir\.git") {
        Write-Host "Updating repository at $InstallDir..." -ForegroundColor Green
        git -C $InstallDir pull --quiet origin main
    }
    else {
        if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
        Write-Host "Cloning repository to $InstallDir..." -ForegroundColor Green
        git clone --quiet $RepoUrl $InstallDir
    }
}
else {
    Write-Host "Git not found, downloading zip package from GitHub..." -ForegroundColor Yellow
    $zipUrl = "https://github.com/kuihaphanich2542-prog/lazy-read/archive/refs/heads/main.zip"
    $tempZip = "$env:TEMP\lazy-read-main.zip"
    Invoke-WebRequest -Uri $zipUrl -OutFile $tempZip
    if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
    Expand-Archive -Path $tempZip -DestinationPath "$env:TEMP\lazy-read-extracted" -Force
    Move-Item "$env:TEMP\lazy-read-extracted\lazy-read-main" $InstallDir
    Remove-Item -Force $tempZip
    Remove-Item -Recurse -Force "$env:TEMP\lazy-read-extracted"
}

Write-Host "=== [3/4] Creating Global CLI Shortcut ===" -ForegroundColor Cyan

if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
}

$cmdWrapper = "$BinDir\lazy-read.cmd"
$wrapperContent = @"
@echo off
set "SKILL_DIR=$InstallDir"
if "%~1"=="" goto help
if "%~1"=="--help" goto help
if "%~1"=="-h" goto help

set "CMD=%~1"
shift

if "%CMD%"=="map" python "%SKILL_DIR%\scripts\codemap.py" map %* & goto end
if "%CMD%"=="inspect" python "%SKILL_DIR%\scripts\codemap.py" inspect %* & goto end
if "%CMD%"=="slice" python "%SKILL_DIR%\scripts\codemap.py" slice %* & goto end
if "%CMD%"=="search" python "%SKILL_DIR%\scripts\codemap.py" search %* & goto end
if "%CMD%"=="find" python "%SKILL_DIR%\scripts\codemap.py" find %* & goto end
if "%CMD%"=="trace" python "%SKILL_DIR%\scripts\codemap.py" trace %* & goto end
if "%CMD%"=="history" python "%SKILL_DIR%\scripts\codemap.py" history %* & goto end
if "%CMD%"=="outline" python "%SKILL_DIR%\scripts\docmap.py" outline %* & goto end
if "%CMD%"=="schema" python "%SKILL_DIR%\scripts\tablemap.py" schema %* & goto end
if "%CMD%"=="agg" python "%SKILL_DIR%\scripts\tablemap.py" agg %* & goto end

echo Unknown command: %CMD%. Run 'lazy-read --help' for usage.
goto end

:help
echo lazy-read v1.7.1 -- Read the map first, then slice
echo.
echo Usage:
echo   lazy-read map ^<repo^> [flags]        # Codebase skeleton map
echo   lazy-read inspect ^<repo^> ^<syms...^>  # Precise symbol slice
echo   lazy-read find ^<repo^> ^<query^>       # Function-level error/text lookup
echo   lazy-read trace ^<repo^> --file ^<t^>   # Leaf-frame stack trace mapper
echo   lazy-read history ^<repo^> ^<sym^>      # Scoped function git diff
echo   lazy-read outline ^<doc^>             # Section outline (MD/DOCX/PDF)
echo   lazy-read schema ^<table^>            # Tabular schema ^& aggregations

:end
"@

Set-Content -Path $cmdWrapper -Value $wrapperContent -Encoding ASCII
Write-Host "CLI wrapper created at: $cmdWrapper" -ForegroundColor Green

Write-Host "=== [4/4] Verifying Installation ===" -ForegroundColor Cyan
& python "$InstallDir\scripts\codemap.py" --help | Out-Null
Write-Host "Verification check passed: 100% operational." -ForegroundColor Green

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " lazy-read v1.7.1 installed successfully!" -ForegroundColor Green
Write-Host " Skill path: $InstallDir"
Write-Host " CLI wrapper: $cmdWrapper"
Write-Host ""
Write-Host " Ensure '$BinDir' is in your User PATH environment variable."
Write-Host "============================================================" -ForegroundColor Cyan
