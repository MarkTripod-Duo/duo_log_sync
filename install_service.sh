#!/usr/bin/env bash
# ============================================================
#  Duo Log Sync - Linux Service Installer
#  Detects the init system and installs the appropriate service.
#
#  Usage: sudo ./install_service.sh [path-to-config.yml]
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="${SCRIPT_DIR}/service"
SERVICE_USER="duologsync"
SERVICE_GROUP="duologsync"
CONFIG_DIR="/etc/duologsync"

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

die() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

info() {
    printf '==> %s\n' "$1"
}

ensure_root() {
    if [ "$(id -u)" -ne 0 ]; then
        die "This script must be run as root (use sudo)."
    fi
}

# ------------------------------------------------------------------
# Detect init system
# ------------------------------------------------------------------

detect_init_system() {
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        echo "systemd"
    elif command -v rc-service >/dev/null 2>&1; then
        echo "openrc"
    elif [ -f /lib/lsb/init-functions ]; then
        echo "sysvinit"
    else
        die "Could not detect a supported init system (systemd, OpenRC, SysVinit)."
    fi
}

# ------------------------------------------------------------------
# Create service user
# ------------------------------------------------------------------

create_service_user() {
    if id "${SERVICE_USER}" >/dev/null 2>&1; then
        info "Service user '${SERVICE_USER}' already exists."
    else
        info "Creating system user '${SERVICE_USER}'..."
        if command -v useradd >/dev/null 2>&1; then
            useradd --system --no-create-home --shell /usr/sbin/nologin \
                --user-group "${SERVICE_USER}"
        elif command -v adduser >/dev/null 2>&1; then
            # Alpine / BusyBox
            adduser -S -D -H -s /sbin/nologin -G "${SERVICE_GROUP}" "${SERVICE_USER}" 2>/dev/null \
                || addgroup -S "${SERVICE_GROUP}" && adduser -S -D -H -s /sbin/nologin -G "${SERVICE_GROUP}" "${SERVICE_USER}"
        else
            die "Cannot create user: neither useradd nor adduser found."
        fi
    fi
}

# ------------------------------------------------------------------
# Install config file
# ------------------------------------------------------------------

install_config() {
    local config_src="$1"

    if [ ! -f "${config_src}" ]; then
        die "Config file not found: ${config_src}"
    fi

    info "Installing config to ${CONFIG_DIR}/config.yml..."
    mkdir -p "${CONFIG_DIR}"
    cp "${config_src}" "${CONFIG_DIR}/config.yml"
    chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${CONFIG_DIR}"
    chmod 750 "${CONFIG_DIR}"
    chmod 640 "${CONFIG_DIR}/config.yml"
}

# ------------------------------------------------------------------
# Init-system-specific installers
# ------------------------------------------------------------------

install_systemd() {
    local unit_file="${SERVICE_DIR}/duologsync.service"
    [ -f "${unit_file}" ] || die "systemd unit file not found: ${unit_file}"

    info "Installing systemd service..."
    cp "${unit_file}" /etc/systemd/system/duologsync.service
    systemctl daemon-reload
    systemctl enable duologsync.service
    systemctl start duologsync.service

    info "Service status:"
    systemctl --no-pager status duologsync.service || true
}

install_openrc() {
    local init_script="${SERVICE_DIR}/duologsync.openrc"
    [ -f "${init_script}" ] || die "OpenRC script not found: ${init_script}"

    info "Installing OpenRC service..."
    cp "${init_script}" /etc/init.d/duologsync
    chmod 755 /etc/init.d/duologsync
    rc-update add duologsync default
    rc-service duologsync start

    info "Service status:"
    rc-service duologsync status || true
}

install_sysvinit() {
    local init_script="${SERVICE_DIR}/duologsync.sysvinit"
    [ -f "${init_script}" ] || die "SysVinit script not found: ${init_script}"

    info "Installing SysVinit service..."
    cp "${init_script}" /etc/init.d/duologsync
    chmod 755 /etc/init.d/duologsync

    if command -v update-rc.d >/dev/null 2>&1; then
        update-rc.d duologsync defaults
    elif command -v chkconfig >/dev/null 2>&1; then
        chkconfig --add duologsync
        chkconfig duologsync on
    fi

    service duologsync start

    info "Service status:"
    service duologsync status || true
}

# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

main() {
    ensure_root

    local init_system
    init_system="$(detect_init_system)"
    info "Detected init system: ${init_system}"

    create_service_user

    # Install config if provided
    if [ $# -ge 1 ]; then
        install_config "$1"
    else
        if [ ! -f "${CONFIG_DIR}/config.yml" ]; then
            die "No config file provided and ${CONFIG_DIR}/config.yml does not exist.\n  Usage: $0 <path-to-config.yml>"
        fi
        info "Using existing config at ${CONFIG_DIR}/config.yml"
    fi

    case "${init_system}" in
        systemd)  install_systemd  ;;
        openrc)   install_openrc   ;;
        sysvinit) install_sysvinit ;;
    esac

    echo
    echo "============================================================"
    echo " DuoLogSync service installed and started successfully."
    echo ""
    echo " Config: ${CONFIG_DIR}/config.yml"
    echo " Init:   ${init_system}"
    echo "============================================================"
}

main "$@"
