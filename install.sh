#!/bin/bash

# به‌روزرسانی پکیج‌ها
sudo apt-get update

# نصب Python و pip در صورت نیاز
sudo apt-get install -y python3 python3-pip

# نصب کتابخانه‌های مورد نیاز
pip3 install requests ping3

# دانلود فایل test.py
curl -L -o test.py https://raw.githubusercontent.com/mohammadahadpour/cloudflareAuto_change_ip/main/test.py

# دادن مجوز اجرایی به فایل
chmod +x test.py

echo "Installation complete. You can now run test.py using 'python3 test.py'."
