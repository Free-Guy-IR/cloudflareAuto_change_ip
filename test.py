import requests
from ping3 import ping
import time
import json
import os

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

def get_subdomains():
    url = f"https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/dns_records"
    headers = {
        'Authorization': f'Bearer {API_TOKEN}',
        'Content-Type': 'application/json'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        records = response.json()['result']
        return {record['name']: record['content'] for record in records if record['type'] == 'A'}
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

def main():
    last_status = read_status_file()
    
    while True:
        subdomains = get_subdomains()
        if not subdomains:
            print("No subdomains found.")
            time.sleep(120)
            continue
        
        status_summary = []
        change_summary = []
        
        for subdomain, ip in subdomains.items():
            ping_time = check_ping(ip)
            
            if subdomain not in last_status:
                last_status[subdomain] = {
                    'current_ip': ip,
                    'ping_failures': 0,
                    'new_ip': None,
                    'is_restored': False
                }
            
            subdomain_status = last_status[subdomain]
            
            if ping_time is None:
                subdomain_status['ping_failures'] += 1
                if subdomain_status['ping_failures'] >= 3:
                    # Check for alternative IP
                    new_ip = None
                    for port, address in ADDRESSES:
                        if address != subdomain_status['current_ip'] and check_ping(address) is not None:
                            new_ip = address
                            break
                    
                    if new_ip:
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
                                        subdomain_status['new_ip'] = new_ip
                                        subdomain_status['is_restored'] = False
                                        change_summary.append(f"❌ {subdomain} (IP: {subdomain_status['current_ip']}) - Ping: None ms. IP جدید: {new_ip} تغییر یافت")
                                        break
                            write_status_file(last_status)  # Update the status file immediately after IP change
                        else:
                            print(f"Error fetching DNS records: {response.status_code}")
                else:
                    print(f"{subdomain} (IP: {ip}) - Ping: None ms. IP جدید: None")
            else:
                subdomain_status['ping_failures'] = 0
                status_summary.append(f"✅ {subdomain} (IP: {ip}) - Ping: {ping_time} ms")
                write_status_file(last_status)  # Update the status file after successful ping
        
        # Check IPs that were previously changed
        for subdomain, status in last_status.items():
            if status['new_ip'] and not status['is_restored']:
                # Check the original IP every 20 seconds
                successful_pings = 0
                for _ in range(3):
                    old_ip_ping_time = check_ping(status['current_ip'])
                    if old_ip_ping_time is not None:
                        successful_pings += 1
                    time.sleep(20)
                    
                if successful_pings >= 3:
                    # Restore the original IP
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
                                if update_dns_record(record_id, subdomain, status['current_ip']):
                                    status['new_ip'] = None
                                    status['is_restored'] = True
                                    send_telegram_message(f"✅ {subdomain} (IP: {status['current_ip']}) - Ping: {old_ip_ping_time} ms. IP به حالت قبل برگردانده شد")
                                    break
                        write_status_file(last_status)  # Update the status file after restoring original IP
                    else:
                        print(f"Error fetching DNS records: {response.status_code}")

        if change_summary:
            message = "\n".join(change_summary)
            send_telegram_message(message)
        
        if status_summary:
            message = "\n".join(status_summary)
            send_telegram_message(message)
        
        print("Next check in 120 seconds...")
        time.sleep(120)

if __name__ == "__main__":
    main()
