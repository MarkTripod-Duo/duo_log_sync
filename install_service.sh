#!/usr/bin/env bash
# ============================================================
#  Duo Log Sync - Linux & macOS Service Installer
#  Detects the operating system (and, on Linux, the init system)
#  and installs the appropriate service.
#
#  Linux : systemd / OpenRC / SysVinit
#  macOS : launchd LaunchDaemon
#
#  Usage: sudo ./install_service.sh [path-to-config.yml]
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="${SCRIPT_DIR}/service"
SERVICE_USER="duologsync"
SERVICE_GROUP="duologsync"
CONFIG_DIR="/etc/duologsync"

# macOS-specific settings
LAUNCHD_LABEL="io.github.marktripod-duo.duologsync"
MACOS_SERVICE_USER="_duologsync"
MACOS_SERVICE_GROUP="_duologsync"
MACOS_LOG_DIR="/usr/local/var/log/duologsync"

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
# macOS (launchd) installer
# ------------------------------------------------------------------

resolve_duologsync_bin() {
    local bin
    bin="$(command -v duologsync 2>/dev/null || true)"
    [ -n "${bin}" ] || die "Could not find the 'duologsync' executable on PATH. Install it first (e.g. 'pip install .' or 'uv tool install .')."
    echo "${bin}"
}

macos_create_service_user() {
    if dscl . -read "/Users/${MACOS_SERVICE_USER}" >/dev/null 2>&1; then
        info "Service user '${MACOS_SERVICE_USER}' already exists."
        return
    fi

    info "Creating macOS service user '${MACOS_SERVICE_USER}'..."

    # Find a free UID/GID in the system range (200-400) that is unused by
    # both users and groups.
    local new_id="" candidate
    for candidate in $(seq 200 400); do
        if ! dscl . -list /Users UniqueID | awk '{print $2}' | grep -qx "${candidate}" \
           && ! dscl . -list /Groups PrimaryGroupID | awk '{print $2}' | grep -qx "${candidate}"; then
            new_id="${candidate}"
            break
        fi
    done
    [ -n "${new_id}" ] || die "Could not find a free system UID/GID for the service user."

    dscl . -create "/Groups/${MACOS_SERVICE_GROUP}"
    dscl . -create "/Groups/${MACOS_SERVICE_GROUP}" PrimaryGroupID "${new_id}"

    dscl . -create "/Users/${MACOS_SERVICE_USER}"
    dscl . -create "/Users/${MACOS_SERVICE_USER}" RealName "Duo Log Sync"
    dscl . -create "/Users/${MACOS_SERVICE_USER}" UserShell /usr/bin/false
    dscl . -create "/Users/${MACOS_SERVICE_USER}" UniqueID "${new_id}"
    dscl . -create "/Users/${MACOS_SERVICE_USER}" PrimaryGroupID "${new_id}"
    dscl . -create "/Users/${MACOS_SERVICE_USER}" NFSHomeDirectory /var/empty
    # Hide the service account from the macOS login window.
    dscl . -create "/Users/${MACOS_SERVICE_USER}" IsHidden 1
}

macos_install_config() {
    local config_src="$1"

    if [ ! -f "${config_src}" ]; then
        die "Config file not found: ${config_src}"
    fi

    info "Installing config to ${CONFIG_DIR}/config.yml..."
    mkdir -p "${CONFIG_DIR}"
    cp "${config_src}" "${CONFIG_DIR}/config.yml"
    chown -R "${MACOS_SERVICE_USER}:${MACOS_SERVICE_GROUP}" "${CONFIG_DIR}"
    chmod 750 "${CONFIG_DIR}"
    chmod 640 "${CONFIG_DIR}/config.yml"
}

install_launchd() {
    local template="${SERVICE_DIR}/${LAUNCHD_LABEL}.plist"
    [ -f "${template}" ] || die "launchd plist not found: ${template}"

    local bin
    bin="$(resolve_duologsync_bin)"
    info "Using duologsync executable: ${bin}"

    info "Creating log directory ${MACOS_LOG_DIR}..."
    mkdir -p "${MACOS_LOG_DIR}"
    chown "${MACOS_SERVICE_USER}:${MACOS_SERVICE_GROUP}" "${MACOS_LOG_DIR}"

    local dest="/Library/LaunchDaemons/${LAUNCHD_LABEL}.plist"
    info "Installing launchd daemon to ${dest}..."
    sed -e "s#__DUOLOGSYNC_BIN__#${bin}#g" \
        -e "s#__CONFIG_PATH__#${CONFIG_DIR}/config.yml#g" \
        -e "s#__SERVICE_USER__#${MACOS_SERVICE_USER}#g" \
        -e "s#__SERVICE_GROUP__#${MACOS_SERVICE_GROUP}#g" \
        -e "s#__LOG_DIR__#${MACOS_LOG_DIR}#g" \
        "${template}" > "${dest}"
    chown root:wheel "${dest}"
    chmod 644 "${dest}"

    # Reload if already present, then bootstrap. Prefer the modern subcommands
    # and fall back to legacy load on older macOS.
    launchctl bootout "system/${LAUNCHD_LABEL}" 2>/dev/null || true
    if launchctl bootstrap system "${dest}" 2>/dev/null; then
        info "Daemon bootstrapped."
    else
        launchctl unload "${dest}" 2>/dev/null || true
        launchctl load -w "${dest}"
        info "Daemon loaded."
    fi
    launchctl enable "system/${LAUNCHD_LABEL}" 2>/dev/null || true

    info "Service status:"
    launchctl print "system/${LAUNCHD_LABEL}" 2>/dev/null | head -n 20 \
        || launchctl list | grep "${LAUNCHD_LABEL}" || true
}

install_macos() {
    macos_create_service_user

    if [ $# -ge 1 ]; then
        macos_install_config "$1"
    else
        if [ ! -f "${CONFIG_DIR}/config.yml" ]; then
            die "No config file provided and ${CONFIG_DIR}/config.yml does not exist.\n  Usage: $0 <path-to-config.yml>"
        fi
        info "Using existing config at ${CONFIG_DIR}/config.yml"
    fi

    install_launchd

    echo
    echo "============================================================"
    echo " DuoLogSync launchd daemon installed and started."
    echo ""
    echo " Config: ${CONFIG_DIR}/config.yml"
    echo " Label:  ${LAUNCHD_LABEL}"
    echo " Logs:   ${MACOS_LOG_DIR}/"
    echo ""
    echo " Manage with:"
    echo "   sudo launchctl kickstart -k system/${LAUNCHD_LABEL}   # restart"
    echo "   sudo launchctl bootout system/${LAUNCHD_LABEL}        # stop/remove"
    echo "============================================================"
}

# ------------------------------------------------------------------
# Linux installer
# ------------------------------------------------------------------

install_linux() {
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

# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

main() {
    ensure_root

    local os_name
    os_name="$(uname -s)"

    case "${os_name}" in
        Darwin)
            info "Detected operating system: macOS"
            install_macos "$@"
            ;;
        Linux)
            info "Detected operating system: Linux"
            install_linux "$@"
            ;;
        *)
            die "Unsupported operating system '${os_name}'. This installer supports Linux and macOS. On Windows use install_service.bat."
            ;;
    esac
}

main "$@"
