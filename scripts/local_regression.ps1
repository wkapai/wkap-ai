$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  $Python = "python"
}

Push-Location $Root
try {
  & $Python manage.py migrate --noinput
  & $Python manage.py check
  & $Python manage.py test
  & $Python manage.py wkap --json run-regression
}
finally {
  Pop-Location
}
