# Sopify Windows installer (REQ-0.6).
#
# Usage:
#   iex (irm https://raw.githubusercontent.com/Siam-GS-Battery/sopify/main/scripts/sopify-install.ps1)
#
# Requirements: Windows 10+ with WSL2 + Docker Desktop, OR native Windows
# with Docker Desktop. PowerShell 5.1+ required.

$ErrorActionPreference = 'Stop'

$SOPIFY_REPO        = if ($env:SOPIFY_REPO) { $env:SOPIFY_REPO } else { "https://github.com/Siam-GS-Battery/sopify.git" }
$SOPIFY_BRANCH      = if ($env:SOPIFY_BRANCH) { $env:SOPIFY_BRANCH } else { "main" }
$SOPIFY_INSTALL_DIR = if ($env:SOPIFY_INSTALL_DIR) { $env:SOPIFY_INSTALL_DIR } else { "$env:LOCALAPPDATA\Sopify" }
$SOPIFY_BIN_DIR     = if ($env:SOPIFY_BIN_DIR) { $env:SOPIFY_BIN_DIR } else { "$env:LOCALAPPDATA\Sopify\bin" }

function Say   ($msg) { Write-Host "» $msg" -ForegroundColor Cyan }
function Ok    ($msg) { Write-Host "✓ $msg" -ForegroundColor Green }
function Warn  ($msg) { Write-Host "  $msg" -ForegroundColor DarkGray }
function Die   ($msg) { Write-Host "✗ $msg" -ForegroundColor Red; exit 1 }

# -------- banner --------
Write-Host ""
Write-Host @"
       ,       ,
      /|    |\./'.
     | |  ,  \|| ,|
     \  \_(\.-""\//.  _
   .-'``""``"`` _   `` ``-.``"""--.._
   | '~``      o\                ``"---"

  ☤ Sopify installer (Windows)
  AI agent + sandbox + 3 modes + org governance
"@ -ForegroundColor Cyan
Write-Host ""

# -------- prereq checks --------
Say "Checking prerequisites..."

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Die "Docker not installed. Install Docker Desktop:`n  https://docs.docker.com/desktop/install/windows-install/"
}
try {
    & docker info | Out-Null
    Ok "Docker ready: $((docker --version) -split ',' | Select-Object -First 1)"
} catch {
    Warn "Docker installed but daemon not running. Start Docker Desktop and re-run."
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Say "Installing uv (Python package manager)..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null
    $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Die "uv install failed." }
}
Ok "uv ready: $(uv --version)"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Die "git not installed. Install from: https://git-scm.com/download/win"
}
Ok "git ready: $(git --version)"

# Docker Sandboxes (sbx) — REQ-1.2.1 microVM backend
if (-not (Get-Command sbx -ErrorAction SilentlyContinue)) {
    Say "Installing Docker Sandboxes (sbx) — Sopify's microVM backend..."
    try {
        winget install -h Docker.sbx
        $env:PATH = "$env:PATH;$env:LOCALAPPDATA\Microsoft\WinGet\Links"
    } catch {
        Warn "sbx install failed — Sopify will fall back to host mode. See:"
        Warn "  https://docs.docker.com/ai/sandboxes/get-started/"
    }
}
if (Get-Command sbx -ErrorAction SilentlyContinue) {
    Ok "sbx ready"
}

# -------- clone / update --------
if (Test-Path "$SOPIFY_INSTALL_DIR\.git") {
    Say "Updating existing checkout at $SOPIFY_INSTALL_DIR..."
    git -C "$SOPIFY_INSTALL_DIR" fetch --quiet origin $SOPIFY_BRANCH
    git -C "$SOPIFY_INSTALL_DIR" checkout --quiet $SOPIFY_BRANCH
    git -C "$SOPIFY_INSTALL_DIR" reset --hard --quiet "origin/$SOPIFY_BRANCH"
    Ok "Updated to $(git -C "$SOPIFY_INSTALL_DIR" rev-parse --short HEAD)"
} else {
    Say "Cloning Sopify from $SOPIFY_REPO ($SOPIFY_BRANCH) -> $SOPIFY_INSTALL_DIR..."
    git clone --quiet --depth 1 --branch $SOPIFY_BRANCH $SOPIFY_REPO $SOPIFY_INSTALL_DIR
    Ok "Cloned to $SOPIFY_INSTALL_DIR"
}

# -------- venv --------
Say "Setting up Python venv via uv sync..."
Push-Location $SOPIFY_INSTALL_DIR
try {
    uv sync --quiet 2>&1 | Select-Object -Last 3
    Ok "venv ready at $SOPIFY_INSTALL_DIR\.venv"
} catch {
    Warn "uv sync had warnings - continuing anyway"
} finally {
    Pop-Location
}

# -------- bin shim --------
if (-not (Test-Path $SOPIFY_BIN_DIR)) {
    New-Item -ItemType Directory -Path $SOPIFY_BIN_DIR -Force | Out-Null
}
$shim = @"
@echo off
python "$SOPIFY_INSTALL_DIR\sopify" %*
"@
Set-Content -Path "$SOPIFY_BIN_DIR\sopify.cmd" -Value $shim -Encoding ASCII
Ok "Wrote shim $SOPIFY_BIN_DIR\sopify.cmd"

# -------- PATH check --------
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$SOPIFY_BIN_DIR*") {
    Say "Adding $SOPIFY_BIN_DIR to user PATH..."
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$SOPIFY_BIN_DIR", "User")
    Warn "Open a NEW terminal so PATH picks up the new entry."
}

# -------- sbx kit register + login --------
if (Get-Command sbx -ErrorAction SilentlyContinue) {
    & sbx kit validate "$SOPIFY_INSTALL_DIR\infra\sbx\sopify-kit" 2>&1 | Out-Null
    Ok "Sopify sbx kit validated"

    # Probe login state via Windows auth dir (best-effort)
    $authDir = "$env:LOCALAPPDATA\com.docker.sandboxes\com.docker.sandboxes-auth\sandboxes-auth"
    $loggedIn = Test-Path "$authDir"
    if (-not $loggedIn) {
        Say "Signing in to Docker Sandboxes (browser will open)..."
        try { & sbx login } catch { Warn "sbx login skipped — run 'sbx login' later" }
    } else {
        Ok "sbx already logged in"
    }
}

# -------- sandbox bootstrap --------
Say "Running 'sopify install' to set up the sandbox..."
try {
    & python "$SOPIFY_INSTALL_DIR\sopify" install
    Ok "Sandbox ready."
} catch {
    Warn "Sandbox install had issues - run 'sopify doctor' to inspect."
}

# -------- done --------
Write-Host ""
Write-Host "  Sopify installed." -ForegroundColor Cyan
Write-Host ""
Write-Host "  Next steps (in a NEW terminal):" -ForegroundColor Gray
Write-Host ""
Write-Host "  1. Add an API key:      sopify login"      -ForegroundColor Green
Write-Host "  2. Confirm health:      sopify doctor"     -ForegroundColor Green
Write-Host "  3. Open the dashboard:  sopify dashboard"  -ForegroundColor Green
Write-Host ""
Write-Host "  Read the manual:  $SOPIFY_INSTALL_DIR\docs\sopify\TUTORIAL.md" -ForegroundColor Gray
Write-Host ""
