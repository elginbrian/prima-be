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
  file_permission = "0400"
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

# EC2 Instance
resource "aws_instance" "app_server" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = var.instance_type
  key_name      = aws_key_pair.app_key_pair.key_name
  vpc_security_group_ids = [aws_security_group.app_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name

  root_block_device {
    volume_size = 10
    volume_type = "gp3"
  }

  tags = {
    Name = "Prima-Backend-Server"
  }

  connection {
    type        = "ssh"
    user        = "ubuntu"
    private_key = tls_private_key.app_key.private_key_pem
    host        = self.public_ip
  }

  # 1. Setup instance (Swap, Docker, Python)
  provisioner "remote-exec" {
    inline = [
      "cloud-init status --wait",
      "sudo apt-get update",
      # Create 2GB swap space to prevent OOM
      "sudo fallocate -l 2G /swapfile",
      "sudo chmod 600 /swapfile",
      "sudo mkswap /swapfile",
      "sudo swapon /swapfile",
      "echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab",
      
      # Install dependencies
      "sudo apt-get install -y python3-pip python3-venv docker.io unzip nginx",
      "sudo curl -L \"https://github.com/docker/compose/releases/download/v2.26.1/docker-compose-linux-x86_64\" -o /usr/local/bin/docker-compose",
      "sudo chmod +x /usr/local/bin/docker-compose",
      "sudo systemctl enable docker",
      "sudo systemctl start docker",
      "sudo usermod -aG docker ubuntu",
      
      "mkdir -p /home/ubuntu/prima-be"
    ]
  }

  # 2. Upload source code zip
  provisioner "file" {
    source      = "${path.module}/deploy.zip"
    destination = "/home/ubuntu/deploy.zip"
  }

  # 3. Extract and Run Application
  provisioner "remote-exec" {
    inline = [
      "cd /home/ubuntu",
      "unzip -o deploy.zip -d /home/ubuntu/prima-be",
      "cd /home/ubuntu/prima-be",
      
      # Create .env from example if not exists
      "if [ ! -f .env ]; then cp .env.example .env; fi",
      
      # Run PostgreSQL database
      "sudo docker-compose up -d",
      
      # Wait for database to be ready
      "sleep 10",
      
      # Setup Python environment and run migrations
      "python3 -m venv venv",
      ". venv/bin/activate",
      "pip install -r requirements.txt",
      "alembic upgrade head",
      "python seed_d3.py",
      
      # Setup systemd service for FastAPI
      "echo '[Unit]' | sudo tee /etc/systemd/system/fastapi.service",
      "echo 'Description=Uvicorn instance to serve FastAPI' | sudo tee -a /etc/systemd/system/fastapi.service",
      "echo 'After=network.target' | sudo tee -a /etc/systemd/system/fastapi.service",
      "echo '' | sudo tee -a /etc/systemd/system/fastapi.service",
      "echo '[Service]' | sudo tee -a /etc/systemd/system/fastapi.service",
      "echo 'User=ubuntu' | sudo tee -a /etc/systemd/system/fastapi.service",
      "echo 'Group=www-data' | sudo tee -a /etc/systemd/system/fastapi.service",
      "echo 'WorkingDirectory=/home/ubuntu/prima-be' | sudo tee -a /etc/systemd/system/fastapi.service",
      "echo 'Environment=\"PATH=/home/ubuntu/prima-be/venv/bin\"' | sudo tee -a /etc/systemd/system/fastapi.service",
      "echo 'ExecStart=/home/ubuntu/prima-be/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000' | sudo tee -a /etc/systemd/system/fastapi.service",
      "echo '' | sudo tee -a /etc/systemd/system/fastapi.service",
      "echo '[Install]' | sudo tee -a /etc/systemd/system/fastapi.service",
      "echo 'WantedBy=multi-user.target' | sudo tee -a /etc/systemd/system/fastapi.service",
      
      "sudo systemctl daemon-reload",
      "sudo systemctl start fastapi",
      "sudo systemctl enable fastapi",
      
      # Setup Nginx as Reverse Proxy
      "echo 'server { listen 80 default_server; server_name prima-be.elginbrian.com _; location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme; } }' | sudo tee /etc/nginx/sites-available/default",
      "sudo systemctl restart nginx"
    ]
  }
}
