# Docker Commands for VideoTester

## Build and Push Docker Image

### 1. Build the Docker image
```bash
# Using the build script
./build.sh

# Or manually
docker build -t content-analysis .
```

### 2. Tag the image (optional)
```bash
docker tag content-analysis content-analysis:latest
```

### 3. Login to Docker Hub
```bash
docker login
```
(Enter your Docker Hub username and password)

### 4. Push the image to Docker Hub (if using)
```bash
docker push your-dockerhub-user/content-analysis:latest
```

## Docker Compose

### Development (Local testing with hot-reload)
```bash
docker-compose -f docker-compose.dev.yml up -d
```

### Production (Deploying on EC2)
```bash
docker-compose up -d --build
```

### Useful Commands
- **View logs**: `docker-compose logs -f`
- **Stop everything**: `docker-compose down`
- **Reset database**: `rm backend/media_validator.db` (then restart containers)

## EC2 Commands

### 1. SSH into your EC2 instance
```bash
ssh -i your-key.pem ec2-user@your-ec2-ip
```

### 2. Install Docker on EC2 (if not already installed)
```bash
# For Amazon Linux 2
sudo yum update -y
sudo yum install docker -y
sudo service docker start
sudo usermod -a -G docker ec2-user

# Log out and log back in for group changes to take effect
```

### 3. Pull the Docker image
```bash
docker pull technurdd/videotester:latest
```

### 4. Run the container
```bash
docker run -d \
  --name videotester \
  -p 6969:6969 \
  --restart unless-stopped \
  technurdd/videotester:latest
```

### 5. Run with volume for persistent database (recommended)
```bash
docker run -d \
  --name content-analysis-api \
  -p 6969:6969 \
  -v content-analysis-data:/app/backend \
  --restart unless-stopped \
  content-analysis:latest
```

### 6. View logs
```bash
docker logs videotester
```

### 7. Follow logs in real-time
```bash
docker logs -f videotester
```

### 8. Stop the container
```bash
docker stop videotester
```

### 9. Start the container
```bash
docker start videotester
```

### 10. Remove the container
```bash
docker stop videotester
docker rm videotester
```

## Security Group Configuration

Make sure your EC2 security group allows inbound traffic on port 6969:
- Type: Custom TCP
- Port: 6969
- Source: 0.0.0.0/0 (or your specific IP for better security)

## Access the Application

After running the container, access the application at:
```
http://your-ec2-public-ip:6969
```
