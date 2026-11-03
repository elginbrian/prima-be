$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Red
Write-Host "      Destroying Prima Backend on AWS      " -ForegroundColor Red
Write-Host "==========================================" -ForegroundColor Red
Write-Host ""

$confirm = Read-Host "Are you sure you want to destroy all AWS resources for Prima Backend? (y/N)"
if ($confirm -ne "y" -and $confirm -ne "Y") {
    Write-Host "Destruction canceled." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "[1/2] Destroying AWS Infrastructure via Terraform..." -ForegroundColor Yellow
Set-Location -Path prima-terraform

if (Test-Path "prima-be-key.pem") {
    attrib.exe -r prima-be-key.pem 2>$null
}

terraform destroy -auto-approve
Set-Location -Path ..

Write-Host "Terraform destroy completed." -ForegroundColor Green
Write-Host ""

Write-Host "[2/2] Cleaning up local SSH config and artifacts..." -ForegroundColor Yellow
$SSH_DIR = Join-Path $env:USERPROFILE ".ssh"
$SSH_CONFIG = Join-Path $SSH_DIR "config"
if (Test-Path $SSH_CONFIG) {
    $configContent = Get-Content $SSH_CONFIG -Raw
    $configContent = $configContent -replace '(?sm)^Host prima\r?\n(?:(?!^Host ).*\r?\n?)*', ""
    Set-Content -Path $SSH_CONFIG -Value ($configContent.TrimEnd() + "`r`n")
    Write-Host "Removed 'Host prima' shortcut from ~/.ssh/config." -ForegroundColor Green
}

if (Test-Path "prima-terraform\deploy.zip") {
    Remove-Item -Force "prima-terraform\deploy.zip"
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Red
Write-Host "      All AWS Resources Destroyed!         " -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Red
Write-Host "Billing has stopped. When ready to redeploy, simply run: .\deploy.ps1"
Write-Host ""
