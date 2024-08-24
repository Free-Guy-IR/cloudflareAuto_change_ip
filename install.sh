#!/bin/bash

# بروزرسانی و نصب پیش‌نیازها
echo "Updating package list and installing prerequisites..."
sudo apt-get update
sudo apt-get install -y git python3 python3-pip

# کلون کردن مخزن GitHub
echo "Cloning the GitHub repository..."
git clone https://github.com/mohammadahadpour/cloudflareAuto_change_ip.git

# ورود به دایرکتوری پروژه
cd cloudflareAuto_change_ip

# ایجاد فایل requirements.txt
echo "Creating requirements.txt..."
echo "requests" > requirements.txt
echo "ping3" >> requirements.txt

# نصب وابستگی‌های Python
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

# پیغام موفقیت
echo "Installation complete. You can now run your script."

# پایان اسکریپت
exit 0
