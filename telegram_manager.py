"""
مدیریت تعاملی رکوردهای DNS از طریق ربات تلگرام.

با ارسال دستور /domains به ربات، می‌توان تمام دامنه‌ها (Zone) و رکوردهای هرکدام را
مشاهده کرد، مقدار (IP/محتوا) هر رکورد را تغییر داد یا آن را کامل حذف کرد.

دسترسی به این قابلیت‌ها فقط برای CHAT_ID پیکربندی‌شده در فایل .env مجاز است؛ هر پیام یا
دکمه‌ای که از چت دیگری برسد، نادیده گرفته می‌شود.
"""
import ipaddress
import threading
import time
import traceback

import requests

CF_API = "https://api.cloudflare.com/client/v4"
PAGE_SIZE = 8


class TelegramDNSManager:
    def __init__(self, telegram_token, chat_id, email, api_key, zone_ids, log_error):
        self.token = telegram_token
        self.authorized_chat_id = str(chat_id)
        self.email = email
        self.api_key = api_key
        self.zone_ids = zone_ids
        self.log_error = log_error
        self.api_base = f"https://api.telegram.org/bot{self.token}"
        self.offset = 0
        self.record_cache = {}
        self.next_token = 1
        self.pending_edit = {}

    # ---------- Telegram helpers ----------
    def _call(self, method, payload):
        try:
            resp = requests.post(f"{self.api_base}/{method}", json=payload, timeout=20)
            return resp.json()
        except Exception as e:
            self.log_error(f"Telegram API error ({method}): {e}")
            return {}

    def send_message(self, chat_id, text, reply_markup=None):
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call("sendMessage", payload)

    def edit_message(self, chat_id, message_id, text, reply_markup=None):
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call("editMessageText", payload)

    def answer_callback(self, callback_id, text=None):
        payload = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
        self._call("answerCallbackQuery", payload)

    # ---------- Cloudflare helpers ----------
    def _cf_headers(self):
        return {
            "X-Auth-Email": self.email,
            "X-Auth-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def list_records(self, zone_id):
        try:
            resp = requests.get(
                f"{CF_API}/zones/{zone_id}/dns_records",
                headers=self._cf_headers(),
                params={"per_page": 100},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json().get("result", [])
            self.log_error(f"Telegram manager: failed to list records for zone {zone_id}: HTTP {resp.status_code}")
        except Exception as e:
            self.log_error(f"Telegram manager: error listing records for zone {zone_id}: {e}")
        return []

    def update_record(self, zone_id, record):
        url = f"{CF_API}/zones/{zone_id}/dns_records/{record['id']}"
        data = {"type": record["type"], "name": record["name"], "content": record["content"]}
        if record["type"] in ("A", "AAAA"):
            data["proxied"] = record.get("proxied", False)
        resp = requests.put(url, json=data, headers=self._cf_headers(), timeout=15)
        return resp.status_code == 200, resp

    def delete_record(self, zone_id, record_id):
        url = f"{CF_API}/zones/{zone_id}/dns_records/{record_id}"
        resp = requests.delete(url, headers=self._cf_headers(), timeout=15)
        return resp.status_code == 200, resp

    # ---------- caching (برای کوتاه ماندن callback_data زیر محدودیت تلگرام) ----------
    def _cache_record(self, zone_id, record):
        token = str(self.next_token)
        self.next_token += 1
        self.record_cache[token] = {"zone_id": zone_id, "record": record}
        return token

    # ---------- keyboards ----------
    def zones_keyboard(self):
        buttons = [[{"text": f"دامنه {i}", "callback_data": f"zone:{i - 1}"}]
                   for i in range(1, len(self.zone_ids) + 1)]
        return {"inline_keyboard": buttons}

    def records_keyboard(self, zone_index, page=0):
        zone_id = self.zone_ids[zone_index]
        records = self.list_records(zone_id)
        start = page * PAGE_SIZE
        chunk = records[start:start + PAGE_SIZE]
        buttons = []
        for record in chunk:
            token = self._cache_record(zone_id, record)
            label = f"{record['name']} ({record['type']}) → {record['content']}"
            if len(label) > 60:
                label = label[:57] + "..."
            buttons.append([{"text": label, "callback_data": f"rec:{token}"}])
        nav = []
        if page > 0:
            nav.append({"text": "⬅️ قبلی", "callback_data": f"page:{zone_index}:{page - 1}"})
        if start + PAGE_SIZE < len(records):
            nav.append({"text": "➡️ بعدی", "callback_data": f"page:{zone_index}:{page + 1}"})
        if nav:
            buttons.append(nav)
        buttons.append([{"text": "🔙 بازگشت به دامنه‌ها", "callback_data": "domains"}])
        return {"inline_keyboard": buttons}, len(records)

    def record_action_keyboard(self, token):
        return {"inline_keyboard": [
            [{"text": "🔁 تغییر مقدار", "callback_data": f"edit:{token}"}],
            [{"text": "🗑 حذف این رکورد", "callback_data": f"del:{token}"}],
            [{"text": "🔙 بازگشت", "callback_data": "domains"}],
        ]}

    def confirm_delete_keyboard(self, token):
        return {"inline_keyboard": [
            [{"text": "✅ بله، حذف کن", "callback_data": f"delok:{token}"},
             {"text": "❌ انصراف", "callback_data": f"rec:{token}"}],
        ]}

    # ---------- update handling ----------
    def handle_message(self, message):
        chat_id = str(message["chat"]["id"])
        if chat_id != self.authorized_chat_id:
            return
        text = (message.get("text") or "").strip()

        if chat_id in self.pending_edit:
            token = self.pending_edit.pop(chat_id)
            entry = self.record_cache.get(token)
            if not entry:
                self.send_message(chat_id, "این درخواست منقضی شده؛ دوباره از /domains شروع کنید.")
                return
            record = entry["record"]
            if record["type"] in ("A", "AAAA") and not self._is_valid_ip(text):
                self.send_message(chat_id, "مقدار واردشده یک IP معتبر نیست. دوباره ارسال کنید یا /domains را بزنید.")
                self.pending_edit[chat_id] = token
                return
            record["content"] = text
            ok, resp = self.update_record(entry["zone_id"], record)
            if ok:
                self.send_message(chat_id, f"✅ رکورد <b>{record['name']}</b> به‌روزرسانی شد:\n<code>{text}</code>")
            else:
                self.send_message(chat_id, f"❌ به‌روزرسانی ناموفق بود (HTTP {resp.status_code}).")
            return

        if text in ("/start", "/domains", "/list"):
            self.send_message(chat_id, "یکی از دامنه‌ها را انتخاب کنید:", self.zones_keyboard())

    def handle_callback(self, callback):
        chat_id = str(callback["message"]["chat"]["id"])
        message_id = callback["message"]["message_id"]
        data = callback.get("data", "")
        self.answer_callback(callback["id"])

        if chat_id != self.authorized_chat_id:
            return

        if data == "domains":
            self.edit_message(chat_id, message_id, "یکی از دامنه‌ها را انتخاب کنید:", self.zones_keyboard())
            return

        if data.startswith("zone:"):
            zone_index = int(data.split(":")[1])
            keyboard, count = self.records_keyboard(zone_index, page=0)
            self.edit_message(chat_id, message_id, f"رکوردهای دامنه {zone_index + 1} ({count} رکورد):", keyboard)
            return

        if data.startswith("page:"):
            _, zone_index, page = data.split(":")
            keyboard, count = self.records_keyboard(int(zone_index), page=int(page))
            self.edit_message(chat_id, message_id, f"رکوردهای دامنه {int(zone_index) + 1} ({count} رکورد):", keyboard)
            return

        if data.startswith("rec:"):
            token = data.split(":")[1]
            entry = self.record_cache.get(token)
            if not entry:
                self.edit_message(chat_id, message_id, "این رکورد دیگر در دسترس نیست. /domains را دوباره بزنید.")
                return
            record = entry["record"]
            text = (
                f"<b>{record['name']}</b>\n"
                f"نوع: {record['type']}\n"
                f"مقدار: <code>{record['content']}</code>\n"
                f"Proxied: {'بله' if record.get('proxied') else 'خیر'}"
            )
            self.edit_message(chat_id, message_id, text, self.record_action_keyboard(token))
            return

        if data.startswith("edit:"):
            token = data.split(":")[1]
            entry = self.record_cache.get(token)
            if not entry:
                self.edit_message(chat_id, message_id, "این رکورد دیگر در دسترس نیست. /domains را دوباره بزنید.")
                return
            self.pending_edit[chat_id] = token
            self.edit_message(
                chat_id, message_id,
                f"مقدار جدید برای <b>{entry['record']['name']}</b> را در یک پیام جدید ارسال کنید:",
            )
            return

        if data.startswith("delok:"):
            token = data.split(":")[1]
            entry = self.record_cache.pop(token, None)
            if not entry:
                self.edit_message(chat_id, message_id, "این رکورد دیگر در دسترس نیست. /domains را دوباره بزنید.")
                return
            ok, resp = self.delete_record(entry["zone_id"], entry["record"]["id"])
            if ok:
                self.edit_message(chat_id, message_id, f"🗑 رکورد <b>{entry['record']['name']}</b> حذف شد.")
            else:
                self.edit_message(chat_id, message_id, f"❌ حذف ناموفق بود (HTTP {resp.status_code}).")
            return

        if data.startswith("del:"):
            token = data.split(":")[1]
            entry = self.record_cache.get(token)
            if not entry:
                self.edit_message(chat_id, message_id, "این رکورد دیگر در دسترس نیست. /domains را دوباره بزنید.")
                return
            record = entry["record"]
            self.edit_message(
                chat_id, message_id,
                f"⚠️ آیا از حذف <b>{record['name']}</b> ({record['type']}) مطمئن هستید؟ این عملیات قابل بازگشت نیست.",
                self.confirm_delete_keyboard(token),
            )
            return

    @staticmethod
    def _is_valid_ip(value):
        try:
            ipaddress.ip_address(value)
            return True
        except ValueError:
            return False

    # ---------- main loop ----------
    def _skip_pending_backlog(self):
        try:
            resp = requests.get(f"{self.api_base}/getUpdates", params={"offset": -1}, timeout=15)
            result = resp.json().get("result", [])
            if result:
                self.offset = result[-1]["update_id"] + 1
        except Exception as e:
            self.log_error(f"Telegram manager: failed to skip backlog: {e}")

    def run(self):
        self._skip_pending_backlog()
        while True:
            try:
                resp = requests.get(
                    f"{self.api_base}/getUpdates",
                    params={"timeout": 30, "offset": self.offset},
                    timeout=40,
                )
                for update in resp.json().get("result", []):
                    self.offset = update["update_id"] + 1
                    if "callback_query" in update:
                        self.handle_callback(update["callback_query"])
                    elif "message" in update:
                        self.handle_message(update["message"])
            except Exception:
                self.log_error(f"Telegram manager loop error: {traceback.format_exc()}")
                time.sleep(5)


def start_telegram_manager(telegram_token, chat_id, email, api_key, zone_ids, log_error):
    manager = TelegramDNSManager(telegram_token, chat_id, email, api_key, zone_ids, log_error)
    thread = threading.Thread(target=manager.run, daemon=True)
    thread.start()
    return manager
