provider "aws" {
  region  = var.aws_region
  profile = "research-account"
}

# Generate an SSH key pair
resource "tls_private_key" "app_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "app_key_pair" {
  key_name   = "prima-be-key"
  public_key = tls_private_key.app_key.public_key_openssh
}

resource "local_file" "private_key" {
  content         = tls_private_key.app_key.private_key_pem
  filename        = "${path.module}/prima-be-key.pem"
  file_permission = "0600"
}

# Get the latest Ubuntu 22.04 LTS AMI (x86_64)
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Security Group
resource "aws_security_group" "app_sg" {
  name        = "prima-be-sg"
  description = "Security group for Prima Backend"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "FastAPI"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# IAM Role for EC2 to access S3
resource "aws_iam_role" "ec2_s3_role" {
  name = "prima-be-ec2-s3-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ec2_s3_policy" {
  role       = aws_iam_role.ec2_s3_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "prima-be-ec2-profile"
  role = aws_iam_role.ec2_s3_role.name
}

# Upload deployment bundle to S3 over HTTPS (avoids SSH port 22 firewall issues)
resource "aws_s3_object" "deploy_package" {
  bucket = aws_s3_bucket.prima_storage.id
  key    = "deployments/deploy.zip"
  source = "${path.module}/deploy.zip"
  etag   = filemd5("${path.module}/deploy.zip")
}

# EC2 Instance provisioned via cloud-init user_data
resource "aws_instance" "app_server" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  key_name                    = aws_key_pair.app_key_pair.key_name
  vpc_security_group_ids      = [aws_security_group.app_sg.id]
  iam_instance_profile        = aws_iam_instance_profile.ec2_profile.name
  user_data_replace_on_change = true

  depends_on = [
    aws_s3_object.deploy_package,
    aws_iam_role_policy_attachment.ec2_s3_policy
  ]

  root_block_device {
    volume_size = 10
    volume_type = "gp3"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -ex
    exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

    # 1. Create 2GB swap space to prevent OOM
    if [ ! -f /swapfile ]; then
      fallocate -l 2G /swapfile
      chmod 600 /swapfile
      mkswap /swapfile
      swapon /swapfile
      echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi

    # 2. Install dependencies
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y python3-pip python3-venv python3-boto3 docker.io unzip nginx curl

    curl -L "https://github.com/docker/compose/releases/download/v2.26.1/docker-compose-linux-x86_64" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    systemctl enable docker
    systemctl start docker
    usermod -aG docker ubuntu

    mkdir -p /home/ubuntu/prima-be

    # 3. Download deploy.zip from S3 (etag: ${aws_s3_object.deploy_package.etag})
    python3 -c "import boto3; boto3.client('s3', region_name='${var.aws_region}').download_file('${aws_s3_bucket.prima_storage.id}', 'deployments/deploy.zip', '/home/ubuntu/deploy.zip')"

    unzip -o /home/ubuntu/deploy.zip -d /home/ubuntu/prima-be
    sed -i 's/\r$//' /home/ubuntu/prima-be/.env 2>/dev/null || true
    sed -i 's/\r$//' /home/ubuntu/prima-be/.env.example 2>/dev/null || true

    cd /home/ubuntu/prima-be
    if [ ! -f .env ]; then cp .env.example .env; fi
    sed -i '/^S3_BUCKET_NAME=/d' .env
    sed -i '/^AWS_REGION=/d' .env
    echo '' >> .env
    echo 'S3_BUCKET_NAME=${aws_s3_bucket.prima_storage.id}' >> .env
    echo 'AWS_REGION=${var.aws_region}' >> .env
    chown -R ubuntu:ubuntu /home/ubuntu/prima-be

    # 4. Start PostgreSQL database
    docker-compose up -d
    for i in $(seq 1 30); do
      if docker exec prima_db pg_isready -U postgres > /dev/null 2>&1; then
        echo 'Postgres is ready!'
        break
      fi
      echo 'Waiting for Postgres...'
      sleep 2
    done

    # 5. Setup Python virtual environment, run migrations and seed
    sudo -u ubuntu python3 -m venv venv
    sudo -u ubuntu ./venv/bin/pip install -r requirements.txt
    sudo -u ubuntu ./venv/bin/alembic upgrade head
    sudo -u ubuntu ./venv/bin/python seed_all.py

    # 6. Configure systemd service for FastAPI
    cat << 'SERVICE' > /etc/systemd/system/fastapi.service
    [Unit]
    Description=Uvicorn instance to serve FastAPI
    After=network.target

    [Service]
    User=ubuntu
    Group=www-data
    WorkingDirectory=/home/ubuntu/prima-be
    Environment="PATH=/home/ubuntu/prima-be/venv/bin"
    ExecStart=/home/ubuntu/prima-be/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
    Restart=always

    [Install]
    WantedBy=multi-user.target
    SERVICE

    systemctl daemon-reload
    systemctl enable fastapi
    systemctl restart fastapi

    # 7. Configure Nginx Reverse Proxy with 25M body limit & 120s AI timeout
    cat << 'NGINX' > /etc/nginx/sites-available/default
    server {
        listen 80 default_server;
        server_name prima-be.elginbrian.com _;
        client_max_body_size 25M;
        location / {
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;
            proxy_connect_timeout 120s;
            proxy_send_timeout 120s;
        }
    }
    NGINX
    systemctl restart nginx
  EOF

  tags = {
    Name = "Prima-Backend-Server"
  }
}
