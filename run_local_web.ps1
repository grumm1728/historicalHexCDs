Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot
Write-Host "Serving web app at http://localhost:8000"
Write-Host "Press Ctrl+C to stop."
Start-Process "http://localhost:8000"
python -m http.server 8000 --directory web

