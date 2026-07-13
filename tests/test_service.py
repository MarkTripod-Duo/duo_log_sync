"""
Unit tests for the Windows service wrapper (duologsync/service.py).

pywin32 is not installed on the CI platform, so fake win32serviceutil/
win32service/win32event/servicemanager/winreg modules are injected into
sys.modules and the module is reloaded so _WIN32_AVAILABLE is True and the
DuoLogSyncService class exists. The pure Windows event-loop glue is exercised
against these fakes; only the ``__main__`` block is pragma-excluded.
"""

import importlib
import sys
from unittest import TestCase
from unittest.mock import MagicMock, patch

service = None
_saved = {}


class _FakeServiceFramework:
    def __init__(self, args=None):
        self.args = args

    def ReportServiceStatus(self, status):
        self.status = status


def setUpModule():
    global service, _saved
    win32serviceutil = MagicMock()
    win32serviceutil.ServiceFramework = _FakeServiceFramework
    fakes = {
        "win32serviceutil": win32serviceutil,
        "win32service": MagicMock(),
        "win32event": MagicMock(),
        "servicemanager": MagicMock(),
        "winreg": MagicMock(),
    }
    for name, module in fakes.items():
        _saved[name] = sys.modules.get(name)
        sys.modules[name] = module
    sys.modules.pop("duologsync.service", None)
    service = importlib.import_module("duologsync.service")
    service = importlib.reload(service)


def tearDownModule():
    for name, module in _saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module
    # Restore the plain (no-win32) module for any later importers.
    sys.modules.pop("duologsync.service", None)
    importlib.import_module("duologsync.service")


class TestRegistryHelpers(TestCase):
    def test_get_config_path_success(self):
        service.winreg.QueryValueEx.return_value = ("C:\\cfg.yml", 1)
        self.assertEqual(service._get_config_path_from_registry(), "C:\\cfg.yml")

    def test_get_config_path_oserror_becomes_runtimeerror(self):
        service.winreg.OpenKey.side_effect = OSError("access denied")
        with self.assertRaises(RuntimeError):
            service._get_config_path_from_registry()
        service.winreg.OpenKey.side_effect = None

    def test_set_config_path_success(self):
        service.winreg.CreateKey.side_effect = None
        service._set_config_path_in_registry("C:\\cfg.yml")
        service.winreg.SetValueEx.assert_called()

    def test_set_config_path_oserror_becomes_runtimeerror(self):
        service.winreg.CreateKey.side_effect = OSError("not admin")
        with self.assertRaises(RuntimeError):
            service._set_config_path_in_registry("C:\\cfg.yml")
        service.winreg.CreateKey.side_effect = None


class TestMain(TestCase):
    def test_not_available_exits_one(self):
        with patch.object(service, "_WIN32_AVAILABLE", False):
            with patch.object(sys, "argv", ["duologsync-service", "start"]):
                with self.assertRaises(SystemExit) as ctx:
                    service.main()
        self.assertEqual(ctx.exception.code, 1)

    @patch("os.path.isfile", return_value=True)
    @patch("os.path.abspath", side_effect=lambda p: p)
    def test_install_with_config(self, _abspath, _isfile):
        with patch.object(service, "_set_config_path_in_registry") as set_reg:
            with patch.object(service.win32serviceutil, "HandleCommandLine") as handle:
                with patch.object(sys, "argv", ["svc", "install", "--config", "cfg.yml"]):
                    service.main()
        handle.assert_called_once()
        set_reg.assert_called_once_with("cfg.yml")

    def test_install_missing_config_exits_one(self):
        with patch.object(sys, "argv", ["svc", "install"]):
            with self.assertRaises(SystemExit) as ctx:
                service.main()
        self.assertEqual(ctx.exception.code, 1)

    @patch("os.path.isfile", return_value=False)
    @patch("os.path.abspath", side_effect=lambda p: p)
    def test_install_file_not_found_exits_one(self, _abspath, _isfile):
        with patch.object(sys, "argv", ["svc", "install", "--config", "missing.yml"]):
            with self.assertRaises(SystemExit) as ctx:
                service.main()
        self.assertEqual(ctx.exception.code, 1)

    def test_non_install_passthrough(self):
        with patch.object(service.win32serviceutil, "HandleCommandLine") as handle:
            with patch.object(sys, "argv", ["svc", "start"]):
                service.main()
        handle.assert_called_once()

    @patch("os.path.isfile", return_value=True)
    @patch("os.path.abspath", side_effect=lambda p: p)
    def test_install_registry_warning_is_swallowed(self, _abspath, _isfile):
        with patch.object(service, "_set_config_path_in_registry", side_effect=RuntimeError("nope")):
            with patch.object(service.win32serviceutil, "HandleCommandLine"):
                with patch.object(sys, "argv", ["svc", "install", "--config", "cfg.yml"]):
                    service.main()  # RuntimeError caught -> warning printed, no exit


class TestServiceMethods(TestCase):
    def tearDown(self):
        from duologsync.program import Program

        Program._running = True

    def _instance(self):
        return service.DuoLogSyncService(None)

    def test_svc_stop_initiates_shutdown(self):
        from duologsync.program import Program

        svc = self._instance()
        svc.SvcStop()
        self.assertFalse(Program._running)
        service.win32event.SetEvent.assert_called()

    def test_svc_do_run_success(self):
        svc = self._instance()
        with patch.object(service, "_get_config_path_from_registry", return_value="cfg.yml"):
            with patch("duologsync.app.run") as run_mock:
                svc.SvcDoRun()
        run_mock.assert_called_once_with("cfg.yml")

    def test_svc_do_run_config_error_returns(self):
        svc = self._instance()
        with patch.object(service, "_get_config_path_from_registry", side_effect=RuntimeError("no cfg")):
            with patch("duologsync.app.run") as run_mock:
                svc.SvcDoRun()
        run_mock.assert_not_called()
        service.servicemanager.LogErrorMsg.assert_called()

    def test_svc_do_run_app_error_is_logged(self):
        svc = self._instance()
        with patch.object(service, "_get_config_path_from_registry", return_value="cfg.yml"):
            with patch("duologsync.app.run", side_effect=Exception("boom")):
                svc.SvcDoRun()
        service.servicemanager.LogErrorMsg.assert_called()
