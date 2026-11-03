$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "      Deploying Prima Backend to AWS       " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# ----------------------------------------------------
# 1. Prepare Deployment Package
# ----------------------------------------------------
Write-Host "[1/5] Preparing deployment package..." -ForegroundColor Yellow

# Ensure .env has a trailing newline before packing
if (Test-Path ".env") {
    $envContent = Get-Content ".env" -Raw
    if (-not $envContent.EndsWith("`n")) {
        Set-Content -Path ".env" -Value ($envContent.TrimEnd() + "`r`n")
    }
}

if (Test-Path "prima-terraform\deploy.zip") {
    Remove-Item -Force "prima-terraform\deploy.zip"
}

tar.exe -a -c -f prima-terraform/deploy.zip `
    --exclude=prima-terraform `
    --exclude=.git `
    --exclude=venv `
    --exclude=.venv `
    --exclude=.pytest_cache `
    --exclude=__pycache__ `
    --exclude=*.log .

Write-Host "Deployment package created." -ForegroundColor Green
Write-Host ""

# ----------------------------------------------------
# 2. Initialize & Apply Terraform
# ----------------------------------------------------
Write-Host "[2/5] Initializing & Provisioning AWS Infrastructure..." -ForegroundColor Yellow
Set-Location -Path prima-terraform

if (Test-Path "prima-be-key.pem") {
    attrib.exe -r prima-be-key.pem 2>$null
}

terraform init
terraform apply -auto-approve

$PUBLIC_IP = (terraform output -raw instance_public_ip)
$BUCKET_NAME = (terraform output -raw s3_bucket_name)
$AWS_REGION = (terraform output -raw s3_bucket_region)
$KEY_PATH = (Resolve-Path "prima-be-key.pem").Path

Write-Host "Infrastructure provisioned successfully." -ForegroundColor Green
Write-Host "  Public IP : $PUBLIC_IP"
Write-Host "  S3 Bucket : $BUCKET_NAME"
Write-Host ""

# ----------------------------------------------------
# 3. Synchronize Local Configuration & SSH Shortcut
# ----------------------------------------------------
Write-Host "[3/5] Synchronizing local config and SSH shortcut..." -ForegroundColor Yellow

# Fix Windows permissions for the PEM file (SSH requires strict permissions)
icacls.exe $KEY_PATH /inheritance:r | Out-Null
icacls.exe $KEY_PATH /grant:r "$($env:USERNAME):(R)" | Out-Null

$SSH_DIR = Join-Path $env:USERPROFILE ".ssh"
if (-not (Test-Path $SSH_DIR)) { New-Item -ItemType Directory -Force -Path $SSH_DIR | Out-Null }
$SSH_CONFIG = Join-Path $SSH_DIR "config"

$configContent = if (Test-Path $SSH_CONFIG) { Get-Content $SSH_CONFIG -Raw } else { "" }
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
Write-Host "SSH shortcut configured ('ssh prima')." -ForegroundColor Green

# Go back to prima-be root
Set-Location -Path ..

# Sync local .env with newly provisioned S3 Bucket & Region
if (Test-Path ".env") {
    $envRaw = Get-Content ".env" -Raw
    $envRaw = $envRaw -replace '(?m)^S3_BUCKET_NAME=.*$', "S3_BUCKET_NAME=$BUCKET_NAME"
    if ($envRaw -notmatch '(?m)^S3_BUCKET_NAME=') {
        $envRaw = $envRaw.TrimEnd() + "`r`nS3_BUCKET_NAME=$BUCKET_NAME`r`n"
    }
    $envRaw = $envRaw -replace '(?m)^AWS_REGION=.*$', "AWS_REGION=$AWS_REGION"
    if ($envRaw -notmatch '(?m)^AWS_REGION=') {
        $envRaw = $envRaw.TrimEnd() + "`r`nAWS_REGION=$AWS_REGION`r`n"
    }
    Set-Content -Path ".env" -Value $envRaw
    Write-Host "Local .env synced with S3 bucket ($BUCKET_NAME)." -ForegroundColor Green
}

# Sync settings.py default bucket
$settingsPath = "src\infrastructure\config\settings.py"
if (Test-Path $settingsPath) {
    $settingsContent = Get-Content $settingsPath -Raw
    $settingsContent = $settingsContent -replace '(?m)s3_bucket_name:\s*str\s*=\s*"[^"]*"', "s3_bucket_name: str = `"$BUCKET_NAME`""
    Set-Content -Path $settingsPath -Value $settingsContent
}
Write-Host ""

# ----------------------------------------------------
# 4. Cloudflare DNS Automation (Optional Zero-Touch)
# ----------------------------------------------------
Write-Host "[4/5] Checking Cloudflare DNS..." -ForegroundColor Yellow

$cfToken = $env:CLOUDFLARE_API_TOKEN
if (-not $cfToken -and (Test-Path ".env")) {
    $envLines = Get-Content ".env"
    foreach ($line in $envLines) {
        if ($line -match '^\s*CLOUDFLARE_API_TOKEN\s*=\s*["'']?([^"'']+)["'']?') {
            $cfToken = $matches[1]
        }
    }
}

$cfUpdated = $false
if ($cfToken) {
    try {
        $headers = @{
            "Authorization" = "Bearer $cfToken"
            "Content-Type"  = "application/json"
        }
        $zonesRes = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones?name=elginbrian.com" -Headers $headers -Method Get -TimeoutSec 10
        if ($zonesRes.success -and $zonesRes.result.Count -gt 0) {
            $zoneId = $zonesRes.result[0].id
            $recordsRes = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records?name=prima-be.elginbrian.com&type=A" -Headers $headers -Method Get -TimeoutSec 10
            if ($recordsRes.success -and $recordsRes.result.Count -gt 0) {
                $recId = $recordsRes.result[0].id
                $body = @{
                    type    = "A"
                    name    = "prima-be.elginbrian.com"
                    content = $PUBLIC_IP
                    proxied = $true
                } | ConvertTo-Json
                $updRes = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records/$recId" -Headers $headers -Method Put -Body $body -TimeoutSec 10
                if ($updRes.success) {
                    Write-Host "  Cloudflare DNS record 'prima-be.elginbrian.com' automatically updated to $PUBLIC_IP!" -ForegroundColor Green
                    $cfUpdated = $true
                }
            } else {
                $body = @{
                    type    = "A"
                    name    = "prima-be"
                    content = $PUBLIC_IP
                    proxied = $true
                } | ConvertTo-Json
                $createRes = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records" -Headers $headers -Method Post -Body $body -TimeoutSec 10
                if ($createRes.success) {
                    Write-Host "  Cloudflare DNS record 'prima-be.elginbrian.com' created with IP $PUBLIC_IP!" -ForegroundColor Green
                    $cfUpdated = $true
                }
            }
        }
    } catch {
        Write-Host "  Notice: Cloudflare automated update failed: $($_.Exception.Message)" -ForegroundColor Gray
    }
}

if (-not $cfUpdated) {
    Write-Host "  DNS Action: Point A record 'prima-be' in Cloudflare to: $PUBLIC_IP" -ForegroundColor Cyan
    Write-Host "  (Tip: Set CLOUDFLARE_API_TOKEN in prima-be/.env to make DNS updates 100% automated)" -ForegroundColor Gray
}
Write-Host ""

# ----------------------------------------------------
# 5. Automated Health Check Verification
# ----------------------------------------------------
Write-Host "[5/5] Verifying Backend Health..." -ForegroundColor Yellow
$maxRetries = 20
$healthy = $false
for ($i = 1; $i -le $maxRetries; $i++) {
    try {
        $res = Invoke-RestMethod -Uri "http://$PUBLIC_IP/api/v1/health" -Method Get -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($res.status -eq "healthy") {
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 3
    }
    Write-Host "  Waiting for FastAPI to accept requests ($i/$maxRetries)..." -ForegroundColor Gray
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
if ($healthy) {
    Write-Host "      Backend is LIVE and READY!          " -ForegroundColor Green
} else {
    Write-Host "      Deployment Finished (Starting Up)   " -ForegroundColor Yellow
}
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Direct IP URL  : http://${PUBLIC_IP}" -ForegroundColor White
Write-Host "  Domain URL     : https://prima-be.elginbrian.com" -ForegroundColor White
Write-Host "  Swagger Docs   : http://${PUBLIC_IP}/docs" -ForegroundColor White
Write-Host "  Health Check   : http://${PUBLIC_IP}/api/v1/health" -ForegroundColor White
Write-Host "  S3 Storage     : $BUCKET_NAME ($AWS_REGION)" -ForegroundColor White
Write-Host "  SSH Access     : ssh prima" -ForegroundColor White
Write-Host ""
