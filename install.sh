#!/bin/bash
#
# CloudflareAuto ChangeIP - installer
# curl -Ls https://raw.githubusercontent.com/Free-Guy-IR/cloudflareAuto_change_ip/main/install.sh | bash

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}➤${NC} $1"; }
success() { echo -e "${GREEN}✔${NC} $1"; }
warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
fail()    { echo -e "${RED}✘ $1${NC}"; exit 1; }

REPO_URL="https://github.com/Free-Guy-IR/cloudflareAuto_change_ip.git"
REPO_DIR="cloudflareAuto_change_ip"
SERVICE_NAME="cloudflare-auto-ip"

clear 2>/dev/null
echo -e "${CYAN}${BOLD}"
cat <<'BANNER'
╔══════════════════════════════════════════════════╗
║          CloudflareAuto ChangeIP — Installer        ║
║              https://t.me/Freeguy_IR                ║
╚══════════════════════════════════════════════════╝
BANNER
echo -e "${NC}"

# از سودو فقط زمانی استفاده کن که کاربر روت نیست و sudo موجوده
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        fail "برای نصب پکیج‌های سیستمی به دسترسی root یا sudo نیاز است."
    fi
fi

info "بروزرسانی لیست پکیج‌ها و نصب پیش‌نیازها (python3, venv, curl, git)..."
$SUDO apt-get update -qq || fail "بروزرسانی لیست پکیج‌ها با خطا مواجه شد."
$SUDO apt-get install -y -qq python3 python3-pip python3-venv curl git \
    || fail "نصب پیش‌نیازهای سیستمی با خطا مواجه شد."
success "پیش‌نیازهای سیستمی نصب شدند."

if [ -d "$REPO_DIR/.git" ]; then
    info "مخزن از قبل موجود است؛ در حال دریافت آخرین تغییرات..."
    (cd "$REPO_DIR" && git pull --quiet) || fail "بروزرسانی مخزن با خطا مواجه شد."
else
    info "در حال دریافت پروژه از گیت‌هاب..."
    git clone --quiet "$REPO_URL" "$REPO_DIR" || fail "دریافت مخزن با خطا مواجه شد."
fi
cd "$REPO_DIR" || fail "پوشه‌ی پروژه پیدا نشد."

info "ساخت محیط مجازی پایتون (venv)..."
if [ ! -d "venv" ]; then
    python3 -m venv venv || fail "ساخت venv با خطا مواجه شد."
fi

cat > requirements.txt <<'REQS'
requests
ping3
python-dotenv
rich
REQS

info "نصب کتابخانه‌های پایتون داخل venv..."
venv/bin/pip install -q --upgrade pip || fail "بروزرسانی pip با خطا مواجه شد."
venv/bin/pip install -q -r requirements.txt || fail "نصب کتابخانه‌های پایتون با خطا مواجه شد."
success "کتابخانه‌های پایتون نصب شدند."

echo
info "اجرای ویزارد پیکربندی..."
echo
venv/bin/python3 cloudflareAuto_change_ip.py --setup || fail "ویزارد پیکربندی با خطا مواجه شد."

echo
success "پیکربندی کامل شد."
echo

WORKDIR="$(pwd)"

install_service() {
    local service_path="/etc/systemd/system/${SERVICE_NAME}.service"
    cat > "$service_path" <<SERVICE
[Unit]
Description=CloudflareAuto ChangeIP monitor
After=network.target

[Service]
Type=simple
WorkingDirectory=${WORKDIR}
ExecStart=${WORKDIR}/venv/bin/python3 ${WORKDIR}/cloudflareAuto_change_ip.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable --now "${SERVICE_NAME}.service"
}

print_manual_instructions() {
    warn "برای اجرای دائمی (تا با قطع شدن SSH متوقف نشود) از screen استفاده کنید:"
    echo -e "  ${BOLD}screen -S cloudflare-ip${NC}"
    echo -e "  ${BOLD}${WORKDIR}/venv/bin/python3 cloudflareAuto_change_ip.py${NC}"
    echo -e "  ${BOLD}(خروج از screen بدون توقف برنامه: Ctrl+A سپس D)${NC}"
}

if command -v systemctl >/dev/null 2>&1; then
    read -rp "$(echo -e "${BOLD}می‌خواهید برنامه به‌عنوان سرویس systemd نصب شود (اجرای خودکار بعد از ریست سرور)؟ [Y/n]: ${NC}")" svc_answer
    svc_answer=${svc_answer:-Y}
    if [[ "$svc_answer" =~ ^[Yy]$ ]]; then
        if [ "$(id -u)" -eq 0 ] || command -v sudo >/dev/null 2>&1; then
            install_service && success "سرویس نصب و فعال شد. وضعیت: systemctl status ${SERVICE_NAME}" \
                || { warn "نصب سرویس ناموفق بود."; print_manual_instructions; }
        else
            warn "برای نصب سرویس به دسترسی root/sudo نیاز است."
            print_manual_instructions
        fi
    else
        print_manual_instructions
    fi
else
    warn "systemd روی این سرور در دسترس نیست."
    print_manual_instructions
fi

echo
success "نصب کامل شد."
echo -e "${CYAN}برای تغییر بعدی تنظیمات:${NC} ${BOLD}${WORKDIR}/venv/bin/python3 cloudflareAuto_change_ip.py --reconfigure --setup${NC}"
echo -e "${CYAN}لاگ خطاها:${NC} ${WORKDIR}/error_log.txt"
