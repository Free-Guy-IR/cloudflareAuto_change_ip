#!/bin/bash
#
# CloudflareAuto ChangeIP - updater
# باید از داخل پوشه‌ی پروژه (cloudflareAuto_change_ip) اجرا شود:
#   cd cloudflareAuto_change_ip && bash update.sh

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${CYAN}➤${NC} $1"; }
success() { echo -e "${GREEN}✔${NC} $1"; }
warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
fail()    { echo -e "${RED}✘ $1${NC}"; exit 1; }

SERVICE_NAME="cloudflare-auto-ip"

[ -d ".git" ] || fail "این اسکریپت باید از داخل پوشه‌ی پروژه (cloudflareAuto_change_ip) اجرا شود."

info "دریافت آخرین تغییرات از گیت‌هاب..."
git pull --quiet || fail "بروزرسانی مخزن با خطا مواجه شد."
success "کد پروژه بروزرسانی شد."

if [ ! -d "venv" ]; then
    python3 -m venv venv || fail "ساخت venv با خطا مواجه شد."
fi

info "بروزرسانی کتابخانه‌های پایتون..."
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt || fail "نصب کتابخانه‌ها با خطا مواجه شد."
success "کتابخانه‌ها بروزرسانی شدند."

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "${SERVICE_NAME}.service" >/dev/null 2>&1 \
    && systemctl is-enabled --quiet "${SERVICE_NAME}.service" 2>/dev/null; then
    info "ری‌استارت سرویس ${SERVICE_NAME}..."
    if [ "$(id -u)" -eq 0 ]; then
        systemctl restart "${SERVICE_NAME}.service"
    else
        sudo systemctl restart "${SERVICE_NAME}.service"
    fi
    success "سرویس با موفقیت ری‌استارت شد."
else
    warn "سرویس systemd یافت نشد. اگر برنامه را داخل screen اجرا کرده‌اید، آن را دستی ری‌استارت کنید:"
    echo -e "  ${CYAN}venv/bin/python3 cloudflareAuto_change_ip.py${NC}"
fi

success "بروزرسانی کامل شد."
