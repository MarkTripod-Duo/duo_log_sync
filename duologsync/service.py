"""
Windows service wrapper for DuoLogSync.

Allows DuoLogSync to run as a native Windows service managed via the
Services MMC snap-in, ``sc.exe``, or ``net start`` / ``net stop``.

Usage (from an elevated command prompt)::

    duologsync-service install --config C:\\path\\to\\config.yml
    duologsync-service start
    duologsync-service stop
    duologsync-service remove
    duologsync-service debug   # run interactively for troubleshooting
"""

import sys

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    import winreg
except ImportError:
    _WIN32_AVAILABLE = False
else:
    _WIN32_AVAILABLE = True

from duologsync.program import Program

# Registry key where we store the config file path for the service.
_REGISTRY_KEY = r"SYSTEM\CurrentControlSet\Services\DuoLogSync\Parameters"
_REGISTRY_VALUE = "ConfigPath"


def _get_config_path_from_registry():
    """Read the config file path from the Windows registry."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REGISTRY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _REGISTRY_VALUE)
            return value
    except OSError as exc:
        raise RuntimeError(
            f"Cannot read config path from registry "
            f"(HKLM\\{_REGISTRY_KEY}\\{_REGISTRY_VALUE}). "
            f"Did you install the service with --config? Error: {exc}"
        ) from exc


def _set_config_path_in_registry(config_path):
    """Write the config file path to the Windows registry."""
    try:
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, _REGISTRY_KEY) as key:
            winreg.SetValueEx(key, _REGISTRY_VALUE, 0, winreg.REG_SZ, config_path)
    except OSError as exc:
        raise RuntimeError(
            f"Cannot write config path to registry. "
            f"Are you running as Administrator? Error: {exc}"
        ) from exc


if _WIN32_AVAILABLE:

    class DuoLogSyncService(win32serviceutil.ServiceFramework):
        """Windows service that runs DuoLogSync continuously."""

        _svc_name_ = "DuoLogSync"
        _svc_display_name_ = "Duo Log Sync"
        _svc_description_ = (
            "Synchronizes authentication and log data from the Duo Admin API "
            "into external systems (SIEMs, log aggregators, or local files)."
        )

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)

        def SvcStop(self):
            """Called by the SCM when the service is asked to stop."""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            Program.initiate_shutdown("Windows service stop requested")
            win32event.SetEvent(self._stop_event)

        def SvcDoRun(self):
            """Called by the SCM when the service is started."""
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )

            try:
                config_path = _get_config_path_from_registry()
            except RuntimeError as exc:
                servicemanager.LogErrorMsg(str(exc))
                return

            # Import here to avoid circular imports at module level
            from duologsync.app import run

            try:
                run(config_path)
            except Exception as exc:
                servicemanager.LogErrorMsg(
                    f"DuoLogSync failed with error: {exc}"
                )

            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STOPPED,
                (self._svc_name_, ""),
            )


def main():
    """
    CLI entry point for managing the DuoLogSync Windows service.

    Intercepts ``install`` to capture ``--config`` before delegating to
    win32serviceutil for standard service operations.
    """
    if not _WIN32_AVAILABLE:
        print(
            "Error: pywin32 is required for Windows service support.\n"
            "Install it with: pip install pywin32",
            file=sys.stderr,
        )
        sys.exit(1)

    # Intercept 'install' to handle --config before passing to pywin32
    if len(sys.argv) >= 2 and sys.argv[1].lower() == "install":
        config_path = None
        filtered_argv = [sys.argv[0]]

        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--config" and i + 1 < len(sys.argv):
                config_path = sys.argv[i + 1]
                i += 2
            else:
                filtered_argv.append(sys.argv[i])
                i += 1

        # Re-add the 'install' command for pywin32
        filtered_argv.insert(1, "install")

        if config_path is None:
            print(
                "Error: --config is required when installing.\n"
                "Usage: duologsync-service install --config C:\\path\\to\\config.yml",
                file=sys.stderr,
            )
            sys.exit(1)

        import os

        config_path = os.path.abspath(config_path)
        if not os.path.isfile(config_path):
            print(
                f"Error: config file not found: {config_path}",
                file=sys.stderr,
            )
            sys.exit(1)

        # Install the service via pywin32
        sys.argv = filtered_argv
        win32serviceutil.HandleCommandLine(DuoLogSyncService)

        # Write the config path to the registry after successful install
        try:
            _set_config_path_in_registry(config_path)
            print(f"Config path saved to registry: {config_path}")
        except RuntimeError as exc:
            print(f"Warning: {exc}", file=sys.stderr)

    else:
        # For all other commands (start, stop, remove, debug, etc.)
        win32serviceutil.HandleCommandLine(DuoLogSyncService)


if __name__ == "__main__":
    main()
