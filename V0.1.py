import requests
from ping3 import ping
import time
import json
import os
import socket
# Constants
API_TOKEN = 'api_cloudflare'
ZONE_ID = 'domain_zone_id'
ADDRESSES = [
    (8587, 'ip_server_iran1'),
    (8586, 'ip_server_iran2'),
    (8585, 'ip_server_iran3'),
    (8584, 'ip_server_iran4'),
    (8583, 'ip_server_iran5'),
    (8582, 'ip_server_iran6'),
    (8581, 'ip_server_iran7'),
]
TELEGRAM_TOKEN = 'token_telegram'
CHAT_ID = 'admin_id'
STATUS_FILE = 'status.json'

MAX_ATTEMPTS = 3  # تعداد دفعات مجاز برای بررسی هر سرور (چه پینگ و چه TCP)

def get_subdomains():
    url = f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records"
    headers = {
        'Authorization': f'Bearer {API_TOKEN}',
        'Content-Type': 'application/json'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        records = response.json()['result']
        # فیلتر کردن ساب‌دامین‌ها بر اساس آی‌پی‌های موجود در لیست
        allowed_ips = {ip for _, ip in ADDRESSES}
        return {record['name']: record['content'] for record in records if record['type'] == 'A' and record['content'] in allowed_ips}
    else:
        print(f"Error fetching subdomains: {response.status_code}")
        return {}

def check_ping(ip):
    try:
        response_time = ping(ip, timeout=2)
        if response_time is not None:
            response_time *= 1000  # Convert to milliseconds
            response_time = round(response_time, 2)  # Round to 2 decimal places
        return response_time
    except Exception as e:
        print(f"Error pinging {ip}: {e}")
        return None

def check_tcp(ip, port):
    try:
        with socket.create_connection((ip, port), timeout=5):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        print(f"TCP connection to {ip}:{port} failed: {e}")
        return False

def update_dns_record(record_id, name, new_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records/{record_id}"
    headers = {
        'Authorization': f'Bearer {API_TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {
        'type': 'A',
        'name': name,
        'content': new_ip,
    }
    response = requests.put(url, json=data, headers=headers)
    
    if response.status_code == 200:
        return True
    else:
        return False

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        'chat_id': CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }
    response = requests.post(url, data=data)
    print("Telegram Status Code:", response.status_code)
    print("Telegram Response JSON:", response.json())

def read_status_file():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, 'r') as file:
            return json.load(file)
    return {}

def write_status_file(status):
    with open(STATUS_FILE, 'w') as file:
        json.dump(status, file, indent=4)

def check_subdomain_status(subdomain, ip, last_status, change_summary, status_summary):
    ping_time = check_ping(ip)
    
    if subdomain not in last_status:
        last_status[subdomain] = {
            'original_ip': ip,  # ذخیره آی‌پی اصلی
            'ping_failures': 0,
            'tcp_failures': 0,
            'new_ip': None,
            'is_restored': False
        }
    
    subdomain_status = last_status[subdomain]

    # بررسی وضعیت پینگ
    if ping_time is None:
        subdomain_status['ping_failures'] += 1
        if subdomain_status['ping_failures'] >= MAX_ATTEMPTS:
            # Check for alternative IP
            new_ip = None
            for port, address in ADDRESSES:
                if address != subdomain_status['original_ip'] and address != subdomain_status['new_ip'] and check_ping(address) is not None:
                    new_ip = address
                    break
            
            if new_ip:
                update_ip_for_subdomain(subdomain, new_ip, subdomain_status, last_status, change_summary)
            else:
                change_summary.append(f"❌ {subdomain} (IP: {ip}) - Ping: None ms | Ping Failed after {MAX_ATTEMPTS} attempts. No alternative IP found.")
        else:
            status_summary.append(f"⚠️ {subdomain} (IP: {ip}) - Ping: None ms | Ping Failed (Attempt {subdomain_status['ping_failures']}/{MAX_ATTEMPTS})")
    else:
        subdomain_status['ping_failures'] = 0
        
        # بررسی وضعیت TCP برای IP فعلی
        tcp_status = None
        for port, address in ADDRESSES:
            if address == ip:
                tcp_status = check_tcp(ip, port)
                break
        
        if tcp_status:
            subdomain_status['tcp_failures'] = 0

            # در اینجا ما فقط موفقیت را ثبت می‌کنیم، بررسی بازگشت به آی‌پی اصلی جداگانه انجام می‌شود
            status_summary.append(f"✅ {subdomain} (IP: {ip}) - Ping: {ping_time} ms | TCP: Success")
        else:
            subdomain_status['tcp_failures'] += 1
            if subdomain_status['tcp_failures'] >= MAX_ATTEMPTS:
                new_ip = None
                for port, address in ADDRESSES:
                    if address != subdomain_status['original_ip'] and address != subdomain_status['new_ip'] and check_ping(address) is not None:
                        new_ip = address
                        break
                
                if new_ip:
                    update_ip_for_subdomain(subdomain, new_ip, subdomain_status, last_status, change_summary)
                else:
                    change_summary.append(f"❌ {subdomain} (IP: {ip}) - TCP: Failed after {MAX_ATTEMPTS} attempts. No alternative IP found.")
            else:
                status_summary.append(f"⚠️ {subdomain} (IP: {ip}) - Ping: {ping_time} ms | TCP: Failed (Attempt {subdomain_status['tcp_failures']}/{MAX_ATTEMPTS})")
        
        write_status_file(last_status)  # Update the status file after successful ping and TCP check

def check_for_revert_to_original_ip(subdomain, last_status, change_summary):
    subdomain_status = last_status[subdomain]
    original_ip = subdomain_status['original_ip']
    
    if subdomain_status['new_ip'] is not None:
        successful_pings = 0
        successful_tcps = 0
        
        # 3 تلاش برای پینگ
        for _ in range(3):
            if check_ping(original_ip) is not None:
                successful_pings += 1
            time.sleep(2)  # فاصله 2 ثانیه‌ای بین تلاش‌ها
        
        if successful_pings == 3:
            # 3 تلاش برای TCP
            for port, address in ADDRESSES:
                if address == original_ip:
                    for _ in range(3):
                        if check_tcp(original_ip, port):
                            successful_tcps += 1
                        time.sleep(2)  # فاصله 2 ثانیه‌ای بین تلاش‌ها
                    break
            
            if successful_tcps == 3:
                update_ip_for_subdomain(subdomain, original_ip, subdomain_status, last_status, change_summary)
                subdomain_status['new_ip'] = None  # Resetting new_ip after revert
                change_summary.append(f"✅ {subdomain} (IP: {original_ip}) - Successfully reverted to original IP after 3 successful ping and TCP tests.")
                write_status_file(last_status)

def update_ip_for_subdomain(subdomain, new_ip, subdomain_status, last_status, change_summary):
    url = f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records"
    headers = {
        'Authorization': f'Bearer {API_TOKEN}',
        'Content-Type': 'application/json'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        records = response.json()['result']
        for record in records:
            if record['name'] == subdomain:
                record_id = record['id']
                if update_dns_record(record_id, subdomain, new_ip):
                    if new_ip == subdomain_status['original_ip']:
                        subdomain_status['new_ip'] = None  # بازگشت به آی‌پی اصلی و تنظیم new_ip به None
                        change_summary.append(f"✅ {subdomain} (IP: {new_ip}) - Successfully reverted to original IP after 3 successful ping and TCP tests.")
                    else:
                        subdomain_status['new_ip'] = new_ip  # به‌روزرسانی new_ip فقط اگر آی‌پی جدید باشد
                        change_summary.append(f"❌ {subdomain} (IP: {subdomain_status['original_ip']}) - IP جدید: {new_ip} تغییر یافت")
                    break
        write_status_file(last_status)  # Update the status file immediately after IP change
    else:
        print(f"Error fetching DNS records: {response.status_code}")

def main():
    last_status = read_status_file()
    
    while True:
        start_time = time.time()  # ثبت زمان شروع

        subdomains = get_subdomains()
        if not subdomains:
            print("No subdomains found.")
            time.sleep(120)
            continue
        
        status_summary = []
        change_summary = []
        
        for subdomain, ip in subdomains.items():
            check_subdomain_status(subdomain, ip, last_status, change_summary, status_summary)
            # اضافه کردن تابع بررسی بازگشت به آی‌پی اصلی
            check_for_revert_to_original_ip(subdomain, last_status, change_summary)
        
        if change_summary:
            message = "\n".join(change_summary)
            send_telegram_message(message)
        
        if status_summary:
            message = "\n".join(status_summary)
            send_telegram_message(message)
        
        # محاسبه زمان صرف شده در این چرخه
        elapsed_time = time.time() - start_time
        print(f"Cycle time: {elapsed_time:.2f} seconds")

        # محاسبه زمان باقیمانده برای رسیدن به 120 ثانیه
        sleep_time = max(0, 120 - elapsed_time)
        print(f"Next check in {sleep_time:.2f} seconds...")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()
