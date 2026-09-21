# Removes Claude Switcher. Claude's own data folders, logins and sessions are left untouched.
$Base = Join-Path $env:LOCALAPPDATA "claude-switcher"
$Bin = Join-Path $Base "bin"
Get-Process ClaudeSwitcher -ErrorAction SilentlyContinue | Stop-Process
Remove-Item (Join-Path ([Environment]::GetFolderPath("Startup")) "Claude Switcher.lnk") -ErrorAction SilentlyContinue
foreach ($p in "lib", "bin", "ClaudeSwitcher.exe", "python.txt") { Remove-Item (Join-Path $Base $p) -Recurse -Force -ErrorAction SilentlyContinue }
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
[Environment]::SetEnvironmentVariable("Path", (($userPath -split ";") | Where-Object { $_ -and $_ -ne $Bin }) -join ";", "User")
Write-Host "Removed. Kept: $Base (sync log, trash and state) and ~\.config\claude-switcher (your account list)."
