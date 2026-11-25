# Uruchomienie calego projektu:
#   Redis (Docker) + Eureka (Docker Compose z pakietu lab3-support) + Membership 8101, Trainer 8102, Class 8103:
#   powershell -ExecutionPolicy Bypass -File .\start.ps1                   # dane zostaja z poprzedniego uruchomienia
#   powershell -ExecutionPolicy Bypass -File .\start.ps1 -Fresh            # od czystych baz (dane startowe)
#   ... -SupportDir C:\sciezka\lab3-support                                # jesli lab3-support nie lezy obok repo
# Zatrzymanie: Ctrl+C w oknach uslug; Eureka: docker compose down (w katalogu lab3-support)

param([string]$SupportDir = (Join-Path $PSScriptRoot '..\lab3-support'), [switch]$Fresh)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

$services = @(
    @{ Dir = 'membership-service'; Port = 8101; Name = 'MEMBERSHIP-SERVICE'; Db = 'app.db' },
    @{ Dir = 'trainer-service';    Port = 8102; Name = 'TRAINER-SERVICE';    Db = 'trainer.db' },
    @{ Dir = 'class-service';      Port = 8103; Name = 'CLASS-SERVICE';      Db = 'class.db' }
)

Write-Host '== Srodowiska Pythona (.venv)'
foreach ($s in $services) {
    $dir = Join-Path $root $s.Dir
    if (-not (Test-Path (Join-Path $dir '.venv\Scripts\python.exe'))) {
        Write-Host "  $($s.Dir): brak .venv - tworze i instaluje requirements.txt (chwile potrwa)"
        Push-Location $dir
        try {
            python -m venv .venv
            if ($LASTEXITCODE -ne 0) { Write-Host '  Nie udalo sie utworzyc .venv - czy python jest w PATH?'; exit 1 }
            & '.\.venv\Scripts\python.exe' -m pip install -q -r requirements.txt
            if ($LASTEXITCODE -ne 0) { Write-Host "  pip install nie powiodl sie w $($s.Dir)"; exit 1 }
        } finally { Pop-Location }
    } else {
        Write-Host "  $($s.Dir): .venv jest"
    }
}

docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Host 'Docker nie dziala. Uruchom Docker Desktop i odpal skrypt ponownie.'; exit 1 }

Write-Host '== Redis'
$exists = docker ps -a --format '{{.Names}}' | Where-Object { $_ -eq 'lab2-redis' }
if ($exists) { docker start lab2-redis | Out-Null }
else { docker run --name lab2-redis -p 127.0.0.1:6379:6379 -d redis:7-alpine | Out-Null }

Write-Host '== Eureka'
$compose = Join-Path $SupportDir 'compose.yaml'
if (-not (Test-Path $compose)) { Write-Host "Nie ma $compose - rozpakuj lab3-support obok repo albo podaj -SupportDir."; exit 1 }
docker compose -f $compose up --build -d eureka
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
    try { Invoke-WebRequest 'http://127.0.0.1:8761/eureka/apps' -UseBasicParsing -TimeoutSec 3 | Out-Null; $ready = $true; break }
    catch { Start-Sleep -Seconds 2 }
}
if (-not $ready) { Write-Host 'Eureka nie odpowiada - przerywam.'; exit 1 }

foreach ($s in $services) {
    $dir = Join-Path $root $s.Dir
    if ($Fresh) { Remove-Item (Join-Path $dir $s.Db) -ErrorAction Ignore }
    $cmd = "Set-Location '$dir'; " +
           "`$host.UI.RawUI.WindowTitle = '$($s.Name) :$($s.Port)'; " +
           "`$env:EUREKA_SERVER_URL = 'http://127.0.0.1:8761'; " +
           "`$env:SERVICE_NAME = '$($s.Name)'; " +
           "`$env:SERVICE_PORT = '$($s.Port)'; " +
           "`$env:CACHE_PREFIX = 'lab2:131428:$($s.Dir)'; " +
           "& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --port $($s.Port)"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))
    Start-Process powershell -ArgumentList '-NoExit', '-EncodedCommand', $encoded
    Write-Host "== $($s.Name): http://localhost:$($s.Port)/docs"
}

Write-Host '== Czekam 35 s, az uslugi zarejestruja sie i pobiora rejestr (odswiezanie co 30 s)...'
Start-Sleep -Seconds 35
Start-Process 'http://localhost:8761/'
foreach ($s in $services) { Start-Process "http://localhost:$($s.Port)/docs" }
Write-Host '== Gotowe.'
