$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "      Updating Prima Backend to AWS        " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/4] Preparing update package..." -ForegroundColor Yellow
if (Test-Path "prima-terraform\deploy.zip") {
    Remove-Item -Force "prima-terraform\deploy.zip"
}
tar.exe -a -c -f prima-terraform/deploy.zip --exclude=prima-terraform --exclude=.git --exclude=venv --exclude=__pycache__ .
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
# Disable strict host key checking to prevent manual prompts
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i prima-terraform/prima-be-key.pem prima-terraform/deploy.zip ubuntu@${PUBLIC_IP}:/home/ubuntu/deploy.zip
Write-Host "Upload complete." -ForegroundColor Green
Write-Host ""

Write-Host "[4/4] Restarting services on server..." -ForegroundColor Yellow
$remoteCommands = @(
    "unzip -o /home/ubuntu/deploy.zip -d /home/ubuntu/prima-be",
    "cd /home/ubuntu/prima-be",
    "source venv/bin/activate",
    "pip install -r requirements.txt",
    "alembic upgrade head",
    "python seed_d3.py",
    "sudo systemctl restart fastapi"
)
$commandString = $remoteCommands -join " && "

ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i prima-terraform/prima-be-key.pem ubuntu@${PUBLIC_IP} $commandString
Write-Host ""

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "            Update Complete!               " -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Backend API is live at: http://${PUBLIC_IP}:8000"
