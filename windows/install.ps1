# Claude Switcher installer (Windows, experimental). Re-running it upgrades in place.
#   powershell -ExecutionPolicy Bypass -File windows\install.ps1
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $PSScriptRoot
$Base = Join-Path $env:LOCALAPPDATA "claude-switcher"
$Lib = Join-Path $Base "lib"
$Bin = Join-Path $Base "bin"
$App = Join-Path $env:LOCALAPPDATA "AnthropicClaude\claude.exe"
function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }

if (-not (Test-Path $App)) {
    throw "Claude desktop app not found at $App. Install it from https://claude.ai/download (the per-user installer)."
}

# Python 3: the py launcher first, then python on PATH. The Microsoft Store "python.exe" stub is not Python.
$py = $null
foreach ($c in @({ py -3 -c "import sys; print(sys.executable)" }, { python -c "import sys; print(sys.executable)" })) {
    try {
        $exe = & $c 2>$null | Select-Object -Last 1
        if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe.Trim())) { $py = $exe.Trim(); break }
    } catch { }
}
if (-not $py) { throw "Python 3 is required. Install it with:  winget install Python.Python.3.12" }
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }

Say "Installing CLI and sync engine"
New-Item -ItemType Directory -Force $Lib, $Bin | Out-Null
Copy-Item (Join-Path $Here "src\*.py") $Lib -Force
Set-Content (Join-Path $Base "python.txt") $pyw -Encoding ASCII
Set-Content (Join-Path $Bin "claude-switch.cmd") "@`"$py`" `"$Lib\claude_switch.py`" %*" -Encoding ASCII
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($userPath -split ";") -notcontains $Bin) {
    [Environment]::SetEnvironmentVariable("Path", (($userPath.TrimEnd(";") + ";" + $Bin).TrimStart(";")), "User")
    Say "Added $Bin to your PATH (open a new terminal to use 'claude-switch')"
}

Say "Building tray app"
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe" }
$exe = Join-Path $Base "ClaudeSwitcher.exe"
Get-Process ClaudeSwitcher -ErrorAction SilentlyContinue | Stop-Process   # our own tray app, safe to restart
Start-Sleep 1
& $csc /nologo /target:winexe /optimize "/out:$exe" /r:System.Management.dll /r:System.Web.Extensions.dll /r:System.Windows.Forms.dll /r:System.Drawing.dll (Join-Path $PSScriptRoot "tray.cs")
if ($LASTEXITCODE -ne 0) { throw "tray app build failed" }

Say "Starting tray app at sign-in"
$startup = [Environment]::GetFolderPath("Startup")
$sh = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $startup "Claude Switcher.lnk"))
$sh.TargetPath = $exe
$sh.Save()
Start-Process $exe

Say "Detecting session folders"
& $py (Join-Path $Lib "claude_switch.py") setup

Write-Host @"

Installed (experimental on Windows). Next:
  1. Add your second account:  claude-switch add      (or tray icon > Add account...)
  2. Log in there and open the Code tab once; the tray app adds it by itself.
  3. Switch with Ctrl+Alt+Page Down, the tray icon, or:  claude-switch
"@
