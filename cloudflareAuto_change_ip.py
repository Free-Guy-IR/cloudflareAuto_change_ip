import argparse
import ipaddress
import logging
import shutil
import socket
import json
import os
import sys
import time
import traceback
from logging.handlers import RotatingFileHandler

import requests
from ping3 import ping
from dotenv import load_dotenv

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.table import Table
from rich import box

console = Console()
ENV_FILE = '.env'


def mask_secret(value):
    value = value or ""
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def prompt_nonempty(label, password=False):
    while True:
        value = Prompt.ask(label, password=password).strip()
        if value:
            return value
        console.print("  [red]این مقدار نمی‌تواند خالی باشد، دوباره وارد کنید.[/red]")


def prompt_ip(label):
    while True:
        value = Prompt.ask(label).strip()
        try:
            ipaddress.ip_address(value)
            return value
        except ValueError:
            console.print(f"  [red]آدرس IP نامعتبر است: {value}[/red]")


def prompt_port(label, default=None):
    while True:
        value = IntPrompt.ask(label, default=default)
        if 1 <= value <= 65535:
            return value
        console.print("  [red]پورت باید عددی بین 1 تا 65535 باشد.[/red]")


def prompt_positive_int(label, default=None):
    while True:
        value = IntPrompt.ask(label, default=default)
        if value > 0:
            return value
        console.print("  [red]مقدار باید بزرگ‌تر از صفر باشد.[/red]")


def show_banner():
    console.rule("[bold cyan]CloudflareAuto ChangeIP[/bold cyan]", style="cyan")
    console.print(
        Panel.fit(
            "[bold white]ویزارد پیکربندی اولیه[/bold white]\n"
            "[dim]این اطلاعات فقط یک‌بار پرسیده می‌شود و در فایل .env روی همین سرور ذخیره می‌شود.[/dim]\n"
            "[dim]کانال بروزرسانی: https://t.me/Freeguy_IR[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()


def review_and_confirm(summary_rows):
    table = Table(title="خلاصه‌ی تنظیمات وارد شده", box=box.ROUNDED, border_style="green")
    table.add_column("متغیر", style="bold cyan", no_wrap=True)
    table.add_column("مقدار")
    for key, value in summary_rows:
        table.add_row(key, str(value))
    console.print(table)
    console.print()
    return Confirm.ask("[bold]این تنظیمات ذخیره و اعمال شوند؟[/bold]", default=True)


def initialize_env(force=False):
    """
    ویزارد تعاملی برای ساخت فایل .env؛ در صورت نیاز به تغییر تنظیمات، اجرای دستی با
    `python3 cloudflareAuto_change_ip.py --reconfigure` این تابع را دوباره فعال می‌کند.
    """
    env_exists = os.path.exists(ENV_FILE) and os.path.getsize(ENV_FILE) > 0

    if env_exists and not force:
        console.print(
            Panel.fit(
                "[yellow]فایل .env از قبل موجود است.[/yellow]",
                border_style="yellow",
            )
        )
        if not Confirm.ask("می‌خواهید تنظیمات را از نو وارد کنید؟", default=False):
            return False

    while True:
        console.clear()
        show_banner()
        env_lines = []
        summary_rows = []

        console.print("[bold cyan]۱) دامنه‌ها (Zones)[/bold cyan]")
        num_zones = prompt_positive_int("چند دامنه (Zone) دارید؟", default=1)
        for i in range(1, num_zones + 1):
            zone_id = prompt_nonempty(f"  Zone ID دامنه {i}")
            env_lines.append(f"ZONE_{i}_ID={zone_id}")
            summary_rows.append((f"Zone {i}", zone_id))

        console.print("\n[bold cyan]۲) سرورهای بکاپ (ایران)[/bold cyan]")
        num_servers = prompt_positive_int("چند سرور دارید؟", default=1)
        for i in range(1, num_servers + 1):
            ip = prompt_ip(f"  آی‌پی سرور {i}")
            port = prompt_port(f"  پورت TCP تانل‌شده‌ی سرور {i}", default=443)
            priority = prompt_positive_int(f"  اولویت سرور {i} (1 = بیشترین اولویت)", default=i)
            env_lines += [
                f"SERVER_{i}_IP={ip}",
                f"SERVER_{i}_PORT={port}",
                f"SERVER_{i}_PRIORITY={priority}",
            ]
            summary_rows.append((f"Server {i}", f"{ip}:{port}  (priority={priority})"))

        console.print("\n[bold cyan]۳) Cloudflare[/bold cyan]")
        email = prompt_nonempty("  ایمیل اکانت Cloudflare")
        api_key = prompt_nonempty("  Global API Key", password=True)
        env_lines += [f"CLOUDFLARE_EMAIL={email}", f"CLOUDFLARE_API_KEY={api_key}"]
        summary_rows += [("Cloudflare Email", email), ("Cloudflare API Key", mask_secret(api_key))]

        console.print("\n[bold cyan]۴) تلگرام[/bold cyan]")
        telegram_token = prompt_nonempty("  توکن ربات تلگرام", password=True)
        chat_id = prompt_nonempty("  Chat ID تلگرام")
        env_lines += [f"TELEGRAM_TOKEN={telegram_token}", f"CHAT_ID={chat_id}"]
        summary_rows += [("Telegram Token", mask_secret(telegram_token)), ("Telegram Chat ID", chat_id)]

        console.print("\n[bold cyan]۵) بازه‌ی بررسی[/bold cyan]")
        interval = prompt_positive_int("  فاصله‌ی بررسی سرورها (ثانیه)", default=120)
        env_lines.append(f"INTERVAL={interval}")
        summary_rows.append(("Interval", f"{interval} ثانیه"))

        console.print()
        if review_and_confirm(summary_rows):
            if env_exists:
                shutil.copy(ENV_FILE, ENV_FILE + ".bak")
            with open(ENV_FILE, "w") as env_file:
                env_file.write("\n".join(env_lines) + "\n")
            console.print(
                Panel.fit(
                    "[bold green]✔ پیکربندی با موفقیت در .env ذخیره شد.[/bold green]",
                    border_style="green",
                )
            )
            return True

        console.print("[yellow]دوباره از ابتدا شروع می‌کنیم...[/yellow]\n")
        env_exists = os.path.exists(ENV_FILE) and os.path.getsize(ENV_FILE) > 0


def parse_args():
    parser = argparse.ArgumentParser(description="CloudflareAuto ChangeIP")
    parser.add_argument(
        "--setup", "-s", action="store_true",
        help="فقط ویزارد پیکربندی (.env) را اجرا کن و بدون شروع مانیتورینگ خارج شو",
    )
    parser.add_argument(
        "--reconfigure", action="store_true",
        help="حتی اگر .env موجود است، ویزارد پیکربندی را دوباره اجرا کن",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="اتصال به Cloudflare، سرورهای بکاپ و ربات تلگرام را تست کن و خارج شو",
    )
    return parser.parse_args()


args = parse_args()

if args.check:
    # --check فرض می‌کند .env از قبل موجود است؛ اجرای بدون تعامل، بدون فراخوانی ویزارد
    if not (os.path.exists(ENV_FILE) and os.path.getsize(ENV_FILE) > 0):
        console.print(
            Panel.fit(
                "[red]فایل .env یافت نشد. ابتدا با --setup پیکربندی کنید.[/red]",
                border_style="red",
            )
        )
        sys.exit(1)
else:
    try:
        initialize_env(force=args.reconfigure)
    except KeyboardInterrupt:
        console.print("\n[yellow]پیکربندی لغو شد.[/yellow]")
        sys.exit(1)

    if args.setup:
        console.print(
            "\n[dim]برای شروع مانیتورینگ:[/dim] [bold]python3 cloudflareAuto_change_ip.py[/bold]\n"
        )
        sys.exit(0)

load_dotenv()

EMAIL = os.getenv('CLOUDFLARE_EMAIL')
API_KEY = os.getenv('CLOUDFLARE_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
STATUS_FILE = 'status.json'
ERROR_LOG_FILE = 'error_log.txt'
ADDRESSES = []
ZONE_IDS = []
MAX_ATTEMPTS = 3
INTERVAL = int(os.getenv('INTERVAL', 120))

for i in range(1, 100):
    zone_id = os.getenv(f"ZONE_{i}_ID")
    if not zone_id:
        break
    ZONE_IDS.append(zone_id)

for i in range(1, 100):
    ip = os.getenv(f"SERVER_{i}_IP")
    port = os.getenv(f"SERVER_{i}_PORT")
    priority = os.getenv(f"SERVER_{i}_PRIORITY")
    if not ip or not port or not priority:
        break
    ADDRESSES.append((int(port), ip, int(priority)))


_error_logger = logging.getLogger("cloudflareAuto")
_error_logger.setLevel(logging.INFO)
_log_handler = RotatingFileHandler(ERROR_LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_log_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_error_logger.addHandler(_log_handler)


def log_error(error_message):
    _error_logger.error(error_message)


def get_subdomains(zone_id):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    headers = {
        'X-Auth-Email': EMAIL,
        'X-Auth-Key': API_KEY,
        'Content-Type': 'application/json'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        records = response.json()['result']
        allowed_ips = {ip for _, ip, _ in ADDRESSES}
        return {
            record['name']: record['content']
            for record in records
            if record['type'] == 'A' and record['content'] in allowed_ips
        }
    else:
        error_message = f"Error fetching subdomains for zone {zone_id}: {response.status_code}"
        print(error_message)
        log_error(error_message)
        return {}


def check_ping(ip):
    try:
        response_time = ping(ip, timeout=2)
        if response_time is not None:
            response_time *= 1000
            response_time = round(response_time, 2)
        return response_time
    except Exception as e:
        error_message = f"Error pinging {ip}: {e}"
        print(error_message)
        log_error(error_message)
        return None


def check_tcp(ip, port):
    try:
        with socket.create_connection((ip, port), timeout=5):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        error_message = f"TCP connection to {ip}:{port} failed: {e}"
        print(error_message)
        log_error(error_message)
        return False


def update_dns_record(zone_id, record_id, name, new_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    headers = {
        'X-Auth-Email': EMAIL,
        'X-Auth-Key': API_KEY,
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
        error_message = f"Error updating DNS record for {name} to {new_ip} in zone {zone_id}: {response.status_code}"
        print(error_message)
        log_error(error_message)
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


def select_best_backup(exclude_ips):
    """
    از بین سرورهای بکاپ در دسترس (پینگ موفق)، سروری با کمترین تاخیر (ping) انتخاب می‌شود؛
    در صورت تساوی پینگ، اولویت تعریف‌شده (priority) به عنوان معیار تصمیم دوم استفاده می‌شود.
    """
    candidates = []
    for port, address, priority in ADDRESSES:
        if address in exclude_ips:
            continue
        ping_time = check_ping(address)
        if ping_time is not None:
            candidates.append((ping_time, priority, address))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))
    return candidates[0][2]


def check_subdomain_status(zone_id, subdomain, ip, last_status, change_summary, status_summary):
    ping_time = check_ping(ip)
    if subdomain not in last_status:
        last_status[subdomain] = {
            'original_ip': ip,
            'ping_failures': 0,
            'tcp_failures': 0,
            'new_ip': None,
            'is_restored': False
        }
    subdomain_status = last_status[subdomain]
    if ping_time is None:
        subdomain_status['ping_failures'] += 1
        if subdomain_status['ping_failures'] >= MAX_ATTEMPTS:
            new_ip = select_best_backup({subdomain_status['original_ip'], subdomain_status['new_ip']})
            if new_ip:
                update_ip_for_subdomain(zone_id, subdomain, new_ip, subdomain_status, last_status, change_summary)
            else:
                change_summary.append(
                    f"❌ {subdomain} (IP: {ip}) - Ping: None ms | Ping Failed after {MAX_ATTEMPTS} attempts. No alternative IP found."
                )
        else:
            status_summary.append(
                f"⚠️ {subdomain} (IP: {ip}) - Ping: None ms | Ping Failed (Attempt {subdomain_status['ping_failures']}/{MAX_ATTEMPTS})"
            )
    else:
        subdomain_status['ping_failures'] = 0
        tcp_status = None
        for port, address, priority in ADDRESSES:
            if address == ip:
                tcp_status = check_tcp(ip, port)
                break
        if tcp_status:
            subdomain_status['tcp_failures'] = 0
            status_summary.append(f"✅ {subdomain} (IP: {ip}) - Ping: {ping_time} ms | TCP: Success")
        else:
            subdomain_status['tcp_failures'] += 1
            if subdomain_status['tcp_failures'] >= MAX_ATTEMPTS:
                new_ip = select_best_backup({subdomain_status['original_ip'], subdomain_status['new_ip']})
                if new_ip:
                    update_ip_for_subdomain(zone_id, subdomain, new_ip, subdomain_status, last_status, change_summary)
                else:
                    change_summary.append(
                        f"❌ {subdomain} (IP: {ip}) - TCP: Failed after {MAX_ATTEMPTS} attempts. No alternative IP found."
                    )
            else:
                status_summary.append(
                    f"⚠️ {subdomain} (IP: {ip}) - Ping: {ping_time} ms | TCP: Failed (Attempt {subdomain_status['tcp_failures']}/{MAX_ATTEMPTS})"
                )
        write_status_file(last_status)


def check_for_revert_to_original_ip(zone_id, subdomain, last_status, change_summary):
    subdomain_status = last_status[subdomain]
    original_ip = subdomain_status['original_ip']
    if subdomain_status['new_ip'] is not None:
        successful_pings = all(check_ping(original_ip) is not None for _ in range(3))
        successful_tcps = all(check_tcp(original_ip, port) for port, ip, _ in ADDRESSES if ip == original_ip)
        if successful_pings and successful_tcps:
            update_ip_for_subdomain(zone_id, subdomain, original_ip, subdomain_status, last_status, change_summary)
            subdomain_status['new_ip'] = None
            change_summary.append(
                f"✅ {subdomain} (IP: {original_ip}) - Successfully reverted to original IP after recovery."
            )
            write_status_file(last_status)


def update_ip_for_subdomain(zone_id, subdomain, new_ip, subdomain_status, last_status, change_summary):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    headers = {
        'X-Auth-Email': EMAIL,
        'X-Auth-Key': API_KEY,
        'Content-Type': 'application/json'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        records = response.json()['result']
        for record in records:
            if record['name'] == subdomain:
                record_id = record['id']
                if update_dns_record(zone_id, record_id, subdomain, new_ip):
                    if new_ip == subdomain_status['original_ip']:
                        subdomain_status['new_ip'] = None
                        change_summary.append(
                            f"✅ {subdomain} (IP: {new_ip}) - Successfully reverted to original IP after 3 successful ping and TCP tests."
                        )
                    else:
                        old_ip = subdomain_status['original_ip']
                        subdomain_status['new_ip'] = new_ip
                        change_summary.append(
                            f"❌ {subdomain} (IP: {old_ip}) - Updated to new IP: {new_ip}"
                        )
                    break
        write_status_file(last_status)
    else:
        log_error(f"Error fetching DNS records for zone {zone_id}. Response Code: {response.status_code}")


def run_check():
    """
    اتصال به هر Zone در Cloudflare، وضعیت پینگ/TCP هر سرور بکاپ و اعتبار ربات تلگرام را
    تست می‌کند و یک جدول خلاصه چاپ می‌کند؛ برای عیب‌یابی سریع بدون منتظر ماندن برای یک
    چرخه‌ی کامل مانیتورینگ.
    """
    console.print(Panel.fit("[bold cyan]بررسی سلامت پیکربندی[/bold cyan]", border_style="cyan"))
    table = Table(box=box.ROUNDED, border_style="cyan")
    table.add_column("مورد", style="bold")
    table.add_column("وضعیت")
    table.add_column("جزئیات")
    all_ok = True

    headers = {'X-Auth-Email': EMAIL, 'X-Auth-Key': API_KEY, 'Content-Type': 'application/json'}
    for idx, zone_id in enumerate(ZONE_IDS, start=1):
        try:
            resp = requests.get(f"https://api.cloudflare.com/client/v4/zones/{zone_id}", headers=headers, timeout=10)
            body = resp.json()
            if resp.status_code == 200 and body.get('success'):
                table.add_row(f"Zone {idx}", "[green]✔ متصل[/green]", body['result']['name'])
            else:
                all_ok = False
                table.add_row(f"Zone {idx}", "[red]✘ خطا[/red]", f"HTTP {resp.status_code}")
        except Exception as e:
            all_ok = False
            table.add_row(f"Zone {idx}", "[red]✘ خطا[/red]", str(e))

    for idx, (port, ip, priority) in enumerate(ADDRESSES, start=1):
        ping_time = check_ping(ip)
        tcp_ok = check_tcp(ip, port)
        online = ping_time is not None and tcp_ok
        if not online:
            all_ok = False
        status = "[green]✔ آنلاین[/green]" if online else "[red]✘ قطع[/red]"
        detail = f"ping={ping_time if ping_time is not None else 'timeout'}ms | tcp={'ok' if tcp_ok else 'fail'}"
        table.add_row(f"Server {idx} ({ip}:{port})", status, detail)

    try:
        resp = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe", timeout=10)
        body = resp.json()
        if resp.status_code == 200 and body.get('ok'):
            table.add_row("Telegram Bot", "[green]✔ معتبر[/green]", f"@{body['result'].get('username')}")
            send_telegram_message("✅ تست اتصال از دستور --check با موفقیت انجام شد.")
        else:
            all_ok = False
            table.add_row("Telegram Bot", "[red]✘ خطا[/red]", f"HTTP {resp.status_code}")
    except Exception as e:
        all_ok = False
        table.add_row("Telegram Bot", "[red]✘ خطا[/red]", str(e))

    console.print(table)
    if all_ok:
        console.print(Panel.fit("[bold green]همه‌چیز سالم است ✔[/bold green]", border_style="green"))
    else:
        console.print(Panel.fit("[bold red]برخی موارد نیاز به بررسی دارند ✘[/bold red]", border_style="red"))
    return all_ok


def main():
    last_status = read_status_file()
    try:
        from telegram_manager import start_telegram_manager
        start_telegram_manager(TELEGRAM_TOKEN, CHAT_ID, EMAIL, API_KEY, ZONE_IDS, log_error)
        send_telegram_message(
            "🤖 مانیتورینگ شروع شد. برای مشاهده و مدیریت رکوردهای DNS دستور /domains را ارسال کنید."
        )
    except Exception:
        log_error(f"Failed to start Telegram DNS manager: {traceback.format_exc()}")
    console.print(
        Panel.fit(
            f"[bold green]مانیتورینگ شروع شد[/bold green]  [dim](هر {INTERVAL} ثانیه بررسی می‌شود)[/dim]",
            border_style="green",
        )
    )
    while True:
        try:
            start_time = time.time()
            for zone_id in ZONE_IDS:
                subdomains = get_subdomains(zone_id)
                if not subdomains:
                    print(f"No subdomains found for zone {zone_id}.")
                    continue
                status_summary = []
                change_summary = []
                for subdomain, ip in subdomains.items():
                    check_subdomain_status(zone_id, subdomain, ip, last_status, change_summary, status_summary)
                    check_for_revert_to_original_ip(zone_id, subdomain, last_status, change_summary)
                if change_summary:
                    message = f"Zone ID: {zone_id}\n" + "\n".join(change_summary)
                    send_telegram_message(message)
                if status_summary:
                    message = f"Zone ID: {zone_id}\n" + "\n".join(status_summary)
                    send_telegram_message(message)
            elapsed_time = time.time() - start_time
            sleep_time = max(0, INTERVAL - elapsed_time)
            time.sleep(sleep_time)
        except KeyboardInterrupt:
            console.print("\n[yellow]متوقف شد توسط کاربر.[/yellow]")
            break
        except Exception as e:
            error_message = traceback.format_exc()
            log_error(error_message)
            print(f"An error occurred: {error_message}")


if __name__ == "__main__":
    if args.check:
        sys.exit(0 if run_check() else 1)
    else:
        main()
