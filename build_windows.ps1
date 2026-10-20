param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$version = & $Python -c "from app import VERSION; print(VERSION)"
if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw "Cannot read application version" }
& $Python -m PyInstaller --noconfirm --clean --windowed --onedir --name LinghaoPet --add-data "assets;assets" app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# GitHub's Windows runner includes Inno Setup; local builds use the same compiler.
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
if (-not $iscc) {
    $iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) { throw "Install Inno Setup 6 from https://jrsoftware.org/isinfo.php, then run again." }
New-Item -ItemType Directory -Path release -Force | Out-Null
& $iscc "/DAppVersion=$version" windows_installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Compress-Archive -Path dist\LinghaoPet -DestinationPath "release\LinghaoPet-Windows-x64-Portable-v$version.zip" -Force
Get-ChildItem release -File | Where-Object { $_.Extension -in '.exe', '.zip' } | ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($_.Name)"
} | Set-Content -Encoding ascii "release\SHA256SUMS-Windows-v$version.txt"
Write-Host "Installer and portable package ready in release/ (Windows acceptance still required)."
