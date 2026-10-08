$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "      Deploying Prima Backend to AWS       " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/4] Preparing deployment package..." -ForegroundColor Yellow
if (Test-Path "prima-terraform\deploy.zip") {
    Remove-Item -Force "prima-terraform\deploy.zip"
}
# Pack the files, excluding terraform state, git, cache, and virtual environments
tar.exe -a -c -f prima-terraform/deploy.zip --exclude=prima-terraform --exclude=.git --exclude=venv --exclude=__pycache__ .
Write-Host "Deployment package created." -ForegroundColor Green
Write-Host ""

Write-Host "[2/4] Initializing Terraform..." -ForegroundColor Yellow
Set-Location -Path prima-terraform
terraform init
Write-Host "Terraform initialized." -ForegroundColor Green
Write-Host ""

Write-Host "[3/5] Provisioning AWS Infrastructure..." -ForegroundColor Yellow
terraform apply -auto-approve
Write-Host ""

Write-Host "[4/5] Setting up 'ssh prima' shortcut..." -ForegroundColor Yellow
$PUBLIC_IP = (terraform output -raw instance_public_ip)
$KEY_PATH = (Resolve-Path "prima-be-key.pem").Path

# Fix Windows permissions for the PEM file (SSH requires strict permissions)
icacls.exe $KEY_PATH /inheritance:r | Out-Null
icacls.exe $KEY_PATH /grant:r "$($env:USERNAME):(R)" | Out-Null

$SSH_DIR = Join-Path $env:USERPROFILE ".ssh"
if (-not (Test-Path $SSH_DIR)) { New-Item -ItemType Directory -Force -Path $SSH_DIR | Out-Null }
$SSH_CONFIG = Join-Path $SSH_DIR "config"

$configContent = if (Test-Path $SSH_CONFIG) { Get-Content $SSH_CONFIG -Raw } else { "" }
# Remove old "Host prima" block if it exists
$configContent = $configContent -replace '(?sm)^Host prima\r?\n(?:(?!^Host ).*\r?\n?)*', ""

$newHostBlock = @"
Host prima
  HostName $PUBLIC_IP
  User ubuntu
  IdentityFile "$KEY_PATH"
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
"@

Set-Content -Path $SSH_CONFIG -Value ($configContent.TrimEnd() + "`r`n`r`n" + $newHostBlock + "`r`n")
Write-Host "Shortcut created! You can now access your server by typing: ssh prima" -ForegroundColor Green
Write-Host ""

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "           Deployment Complete!            " -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Note: It might take a minute or two for the FastAPI server to fully start"
Write-Host "after the instance is running. Check your public IP output above."
Write-Host ""

# Go back to original directory
Set-Location -Path ..
