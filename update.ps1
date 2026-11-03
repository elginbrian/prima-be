$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "      Updating Prima Backend to AWS        " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/4] Preparing update package..." -ForegroundColor Yellow
if (Test-Path "prima-terraform\deploy.zip") {
    Remove-Item -Force "prima-terraform\deploy.zip"
}
tar.exe -a -c -f prima-terraform/deploy.zip `
    --exclude=prima-terraform `
    --exclude=.git `
    --exclude=venv `
    --exclude=.venv `
    --exclude=__pycache__ `
    --exclude=.pytest_cache `
    --exclude=*.log .

Write-Host "Update package created." -ForegroundColor Green
Write-Host ""

Write-Host "[2/4] Getting server details from Terraform..." -ForegroundColor Yellow
Set-Location -Path prima-terraform
$PUBLIC_IP = (terraform output -raw instance_public_ip)
Set-Location -Path ..

if (-not $PUBLIC_IP) {
    Write-Host "Error: Could not find Public IP. Ensure Terraform deployment was successful." -ForegroundColor Red
    exit 1
}
Write-Host "Server IP: $PUBLIC_IP" -ForegroundColor Green
Write-Host ""

Write-Host "[3/4] Uploading new code to server..." -ForegroundColor Yellow
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i prima-terraform/prima-be-key.pem prima-terraform/deploy.zip ubuntu@${PUBLIC_IP}:/home/ubuntu/deploy.zip
Write-Host "Upload complete." -ForegroundColor Green
Write-Host ""

Write-Host "[4/4] Applying updates & restarting services on server..." -ForegroundColor Yellow
$remoteCommands = @(
    "unzip -o /home/ubuntu/deploy.zip -d /home/ubuntu/prima-be",
    "cd /home/ubuntu/prima-be",
    "source venv/bin/activate",
    "pip install -r requirements.txt",
    "alembic upgrade head",
    "sudo systemctl restart fastapi"
)
$commandString = $remoteCommands -join " && "

ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i prima-terraform/prima-be-key.pem ubuntu@${PUBLIC_IP} $commandString
Write-Host ""

# Health Check verification
Write-Host "Verifying backend health..." -ForegroundColor Yellow
$healthy = $false
for ($i = 1; $i -le 15; $i++) {
    try {
        $res = Invoke-RestMethod -Uri "http://$PUBLIC_IP/api/v1/health" -Method Get -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($res.status -eq "healthy") {
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
if ($healthy) {
    Write-Host "         Update Successfully Applied!      " -ForegroundColor Green
} else {
    Write-Host "         Update Applied (Starting Up)     " -ForegroundColor Yellow
}
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  API URL     : http://${PUBLIC_IP}"
Write-Host "  Domain URL  : https://prima-be.elginbrian.com"
Write-Host "  Docs URL    : http://${PUBLIC_IP}/docs"
Write-Host ""
