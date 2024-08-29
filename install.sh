#!/bin/bash

echo "Updating package list and installing prerequisites..."
sudo apt-get update

# نصب Python و pip در صورت نیاز
sudo apt-get install -y python3 python3-pip curl git

# کلون کردن مخزن GitHub
if [ -d "cloudflareAuto_change_ip" ]; then
    echo "Repository already exists. Pulling latest changes..."
    cd cloudflareAuto_change_ip
    git pull
else
    echo "Cloning the GitHub repository..."
    git clone https://github.com/mohammadahadpour/cloudflareAuto_change_ip.git
    cd cloudflareAuto_change_ip
fi

# ایجاد فایل requirements.txt
echo "Creating requirements.txt..."
echo "requests" > requirements.txt
echo "aiohttp" > requirements.txt
echo "ping3" >> requirements.txt

# نصب کتابخانه‌های Python
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

# دانلود فایل test.py
echo "Downloading test.py..."
curl -L -o test.py https://raw.githubusercontent.com/mohammadahadpour/cloudflareAuto_change_ip/main/test.py

# دادن مجوز اجرایی به فایل
chmod +x test.py

echo "Installation complete. You can now run your script using 'python3 test.py'."
