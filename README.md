Duo Log Sync (v2.5.0)
===================

[![Issues](https://img.shields.io/github/issues/duosecurity/duo_log_sync)](https://github.com/duosecurity/duo_log_sync/issues)
[![Forks](https://img.shields.io/github/forks/duosecurity/duo_log_sync)](https://github.com/duosecurity/duo_log_sync/network/members)
[![Stars](https://img.shields.io/github/stars/duosecurity/duo_log_sync)](https://github.com/duosecurity/duo_log_sync/stargazers)
[![License](https://img.shields.io/badge/License-View%20License-orange)](./LICENSE)

> ## ⚠️ Unofficial Fork Notice
>
> **This repository is a community fork that has diverged substantially from the
> upstream project, [`duosecurity/duo_log_sync`](https://github.com/duosecurity/duo_log_sync).**
>
> The changes in this fork — **`uv`-based packaging**, **local `FILE` output**,
> and **install-as-a-service support** (Linux systemd/OpenRC/SysVinit, macOS
> launchd, and Windows) — are **unofficial, community/maintainer updates that
> are NOT supported by Duo Security**. They have not been reviewed, endorsed, or
> released by Duo.
>
> - For the **official, Duo-supported** product, use the upstream repository and
>   its support channels.
> - For **issues or pull requests specific to this fork's additions**, open them
>   **here in this repository** — not against Duo.
>
> Use in production at your own discretion.

## About
`duologsync` (DLS) is a utility written by Duo Security that supports fetching logs from Duo endpoints and ingesting them to different SIEMs.

---
## Prerequisite

`duologsync` requires credentials for an Admin API application with the "Grant read log" API permission. Create this application before installation and configuration.

To create the Admin API application:

1. Log into the Duo Admin Panel as an administrator with the "Owner" role and navigate to **Applications**.
2. Click **Protect an Application** and locate the entry for **Admin API** in the applications list.
3. Click **Protect** to the far-right to configure the application and get your integration key, secret key, and API hostname. You'll need this information to update the `config.yml` file later.
4. Scroll down to the "Permissions" section of the page and deselect all permission options other than **Grant read log**.
5. Optionally specify which IP addresses or ranges are allowed to use this Admin API application in **Networks for API Access**. If you do not specify any IP addresses or ranges, this Admin API application may be accessed from any network.
6. Click **Save**.

MSP customers gathering logs from linked accounts should create an **Accounts API** Duo application and use that application's information in the `config.yml` file.

### Set Up a Receiving Server

Before running DuoLogSync, you must have a server configured to receive the logs. DuoLogSync sends logs over TCP, TCPSSL (TCP with SSL encryption), or UDP to a specified hostname and port, or writes logs to local files using FILE protocol.

Common receiving systems include:

- SIEM platforms
- Syslog servers
- Log aggregators

Ensure the `hostname` and `port` in your `config.yml` match your receiving server's configuration. Refer to your SIEM or log server documentation for setup instructions.

For FILE output, ensure the configured destination directory is accessible to the DuoLogSync process.

## Installation

### Using uv (Recommended)

[uv](https://docs.astral.sh/uv/) is the recommended way to install and manage DuoLogSync.

1. Make sure you have Python 3.8 or later: `python --version`.
2. [Install uv](https://docs.astral.sh/uv/getting-started/installation/) if you haven't already.
3. Clone this GitHub repository and navigate to the `duo_log_sync` folder.
4. Install dependencies and set up the virtual environment:
   ```
   uv sync
   ```
5. Refer to the `Configuration` section below. You will need to create a `config.yml` file and fill out credentials for the Admin API in the duoclient section as well as other parameters if necessary.
6. Run the application:
   ```
   uv run duologsync <complete/path/to/config.yml>
   ```
7. If a new version of DLS is downloaded from GitHub, run `uv sync` again to update dependencies and reinstall.

### Using pip (Alternative)

1. Make sure you are running Python 3.8 or later: `python --version`.
2. Clone this GitHub repository and navigate to the `duo_log_sync` folder.
3. Install `duologsync` and its dependencies:
   ```
   pip install .
   ```
4. Refer to the `Configuration` section below. You will need to create a `config.yml` file and fill out credentials for the Admin API in the duoclient section as well as other parameters if necessary.
5. Run the application:
   ```
   duologsync <complete/path/to/config.yml>
   ```
6. If a new version of DLS is downloaded from GitHub, run `pip install .` again to reinstall `duologsync` for changes to take effect.
### Compatibility

- Duologsync is compatible with Python versions `3.8`, `3.9`, `3.10`, `3.11`, `3.12`, and `3.13`.
- Duologsync is officially supported on Linux, MacOS, and Windows systems.

### Validating Your Configuration

Before running DuoLogSync, you can validate your configuration file to check for errors:

```
duologsync --validate <complete/path/to/config.yml>
```

Or with uv:

```
uv run duologsync --validate <complete/path/to/config.yml>
```

This checks that the file:
- Can be opened and read
- Contains valid YAML syntax
- Passes schema validation (required fields, correct types, valid values)
- Flags warnings for settings that will be adjusted at runtime (e.g., API timeout below minimum)

The command exits with code `0` on success or `1` if errors are found, making it suitable for use in CI/CD pipelines and pre-deployment checks.

### Windows
- On Windows operating systems, `duologsync` is installed in the `\Scripts\` folder under the Python installation in most cases when using pip. When using uv, the application is available via `uv run duologsync`.

---

## Running as a Service

DuoLogSync can be installed as a system service so it starts automatically and runs in the background.

### Linux (systemd, OpenRC, SysVinit)

An installer script is included that auto-detects your init system and sets everything up:

```
sudo ./install_service.sh /path/to/config.yml
```

This will:
- Create a `duologsync` system user
- Copy your config to `/etc/duologsync/config.yml`
- Install the appropriate service file for your init system
- Enable and start the service

**Managing the service (systemd):**
```
sudo systemctl status duologsync
sudo systemctl stop duologsync
sudo systemctl start duologsync
sudo journalctl -u duologsync -f    # follow logs
```

**Managing the service (OpenRC):**
```
sudo rc-service duologsync status
sudo rc-service duologsync stop
sudo rc-service duologsync start
```

**Managing the service (SysVinit):**
```
sudo service duologsync status
sudo service duologsync stop
sudo service duologsync start
```

The service files are located in the `service/` directory and can be customized before installation. On systemd, environment overrides can be placed in `/etc/default/duologsync`.

### macOS (launchd)

On macOS, the same installer script registers DuoLogSync as a launchd `LaunchDaemon` so it starts at boot and restarts on failure. Make sure the `duologsync` executable is on your `PATH` (e.g. via `uv tool install .` or `pip install .`), then run:

```
sudo ./install_service.sh /path/to/config.yml
```

This will:
- Create a hidden `_duologsync` service account
- Install the config to `/etc/duologsync/config.yml`
- Render and install `/Library/LaunchDaemons/com.duosecurity.duologsync.plist`
- Bootstrap and start the daemon (logs go to `/usr/local/var/log/duologsync/`)

**Managing the service:**
```
sudo launchctl print system/com.duosecurity.duologsync      # status
sudo launchctl kickstart -k system/com.duosecurity.duologsync  # restart
sudo launchctl bootout system/com.duosecurity.duologsync     # stop / uninstall
```

### Windows Service

DuoLogSync can run as a native Windows service using `pywin32`. Install the extra dependency first:

```
pip install .[windows]
```

Then from an **elevated (Administrator) command prompt**:

```
duologsync-service install --config C:\path\to\config.yml
duologsync-service start
```

Or use the convenience script:
```
install_service.bat C:\path\to\config.yml
```

**Managing the service:**
```
net stop DuoLogSync
net start DuoLogSync
duologsync-service remove    # uninstall
duologsync-service debug     # run interactively for troubleshooting
```

The config file path is stored in the Windows registry. The service appears as "Duo Log Sync" in the Services management console.

---

## Logging
- A logging filepath can be specified in `config.yml`. By default, logs will be stored under the `/tmp` folder with name `duologsync.log`.
- These logs are only application/system logs, and not the actual logs retrieved from Duo endpoints.

---

## Features

- Current version supports fetching logs from auth, telephony, activity, and trust monitor endpoints and sending over
  TCP, TCP Encrypted over SSL, UDP, and FILE output to consuming systems.
- Ability to recover data by reading from last known offset through checkpointing files.
- Enabling only certain endpoints through config file.
- Choosing how logs are formatted (JSON, CEF).
- Support for Linux, MacOS, Windows.
- Install as a system service on Linux (systemd, OpenRC, SysVinit), macOS (launchd), and Windows.
- Configurable local file output with retry, disk-backlog recovery, and size/time-based log rotation.
- Support for pulling logs using Accounts API (only for MSP accounts).
- Graceful shutdown support via SIGINT (Ctrl-C) and SIGTERM signals.

### Work in progress

- Adding more log endpoints.
- Adding better skey security.
- Adding CEF and MSP support for the Trust Monitor endpoint.

---

## System Requirements

- Duo Log Sync must be run on a system set to the UTC/GMT Timezone

## Configuration

- See [`template_config.yml`](./template_config.yml) for an example and for extensive, in-depth config explanation.

### Configurations explained
- The `log_format` field is a `dls_settings` setting and it is for how Duo logs should be formatted before being sent to a server/siem. Valid options are CEF, JSON. The default will be JSON.
- The `offset` field is a `api` setting and it is for days in the past from which record retrieval should begin. Maximum logs that can be fetched is `180 days` in past. The default is 180.
- The `timeout` field is a `api` setting and it is for `seconds` to wait between API calls (for fetching Duo logs). If timeout is set to less than 120 seconds, it will be defaulted to 120.
- The `enabled` field is a `checkpointing` setting and it is for whether checkpoint files should be created to save offset information about API calls which will be used to continue fetching of data if utility crashes or is restarted. Valid options are True or False.
- The `directory` field is a `checkpointing` setting is to mention path where checkpoint files will be created. The default is `/tmp`.
- The `proxy_server` is a `proxy` setting and it is a Host/IP for the Http Proxy.
- The `proxy_port` is a `proxy` setting and it is a Port for the Http Proxy.
- The `id` is a `servers` setting and it is a descriptive name for your server. It is a `REQUIRED` field.
- The `hostname` is a `servers` setting and it is a address of TCP/UDP server to which Duo logs will be sent. It is a
  `REQUIRED` field for `TCP`, `TCPSSL`, and `UDP`.
- The `port` is a `servers` setting and it is a Port of server to which logs will be sent. The valid port range is
  1024-65535. It is a `REQUIRED` field for `TCP`, `TCPSSL`, and `UDP`.
- The `protocol` is a `servers` setting and it is a transport protocol used to communicate with the server. The allowed
  options are `TCP`, `TCPSSL`, `UDP`, `FILE`. It is a `REQUIRED` field.
- The `cert_filepath` is a `servers` setting and it is a location of the certificate file used for encrypting communication for TCPSSL. TCPSSL expects that there are .key and .cert files that store keys. For configuration, give path of .cert/.pem file that has keys. It is a `REQUIRED` field if protocol is TCPSSL.
- The `filepath` is a `servers` setting and it is a path to a local file where logs are appended when protocol is
  `FILE`. It is a `REQUIRED` field if protocol is FILE.
- The `queue_max_size` is a `file_output` setting and it controls in-memory buffering for FILE output before backlogging
  to disk.
- The `max_retries` is a `file_output` setting and it controls retry attempts for transient FILE write failures before
  writing to backlog.
- The `retry_backoff_seconds` is a `file_output` setting and it controls the base backoff interval for FILE write
  retries.
- The `enable_test_input` is a `file_output` setting and enables test automation direct payload injection for FILE
  output load/fault-tolerance validation.
- The `ikey` is a `account` setting and it is a integration key of the `Admin API` integration. For MSP accoint, this should have integration key for `Accounts API`. It is a `REQUIRED` field.
- The `skey` is a `account` setting and it is a private key of the `Admin API` integration. For MSP accoint, this should have private key for `Accounts API`. It is a `REQUIRED` field.
- The `hostname` is a `account` setting and it is a api-hostname of the `Admin API` integration on which the server hosting this account's logs. For MSP accoint, this should have api-hostname for `Accounts API`. It is a `REQUIRED` field.
- The `endpoints` field is a `endpoint_server_mappings` setting. It is for defining what endpoints the mapping is for as a list. The valid options are `auth`, `telephony`, `trustmonitor`, `activity`. It is a `REQUIRED` field.
- The `server` field is a `endpoint_server_mappings` setting. It is where you define to what servers the logs of certain endpoints should go.This is done by creating a mapping (start with dash -).It is a `REQUIRED` field.
- The `is_msp` field is to define whether this account is a Duo MSP account with child accounts. If True, then all the child accounts will be accessed and logs will be pulled for each child account. It is a `NOT REQUIRED` field. The default is `False`

### FILE Output Behavior

- FILE output writes logs asynchronously to avoid blocking producers/consumers.
- If the output directory in `filepath` does not exist, DuoLogSync attempts to create it.
- DuoLogSync validates write permissions by performing real write probes on the destination directory and existing output file.
- On transient file write failures, retries use exponential backoff according to `max_retries` and
  `retry_backoff_seconds`.
- If retries are exhausted (and the failure is not disk full), logs are written to checkpoint-directory backlog files named `<log_type>_file_failed_ingestion_logs.txt`.
- On startup, existing FILE backlog files are replayed before live writes and resumed if replay was interrupted.
- If disk-full conditions are detected (`ENOSPC`/quota), retries are skipped and DuoLogSync initiates shutdown immediately with an explicit error message and code.

### Upgrading Your Config File
- From time to time new features and fields will be added to the config file. Updating of the config file is mandatory when config changes are made. To make this easier, Duo has created a script called [`upgrade_config.py`](./upgrade_config.py) which will automatically update your old config for you.
- To use the `upgrade_config.py` script, simply run the following command: `python3 upgrade_config.py <old_config> <new_config>` where `<old_config>` is the filepath or your old configuration file, and `<new_config>` is where you would like the new configuration file to be saved.
- The `upgrade_config.py` script will not delete your old config file, it will be preserved.
- This script is a new feature and has to extrapolate some information, some unexpected issues may occur. For most old configs the script will work just fine. You can check if the new config file works by running it with DLS.
- The `is_msp` field under accounts section is required only when using DLS with the Accounts API. For this reason, the upgrade script won't create that field in new config by default.

---

## Additional Considerations

### MSP customers

- Calling Admin API handlers with Accounts API is mutually exclusive with cross-deployment sub-accounts. Many customers with sub-accounts (especially MSPs) must use cross-deployment sub-accounts and therefore can't use the Accounts API. 

### Trust Monitor Support
- Currently, the Trust Monitor endpoint only supports logging in JSON format, and does not support MSPs. Calling this endpoint (in combination with any other endpoints) using CEF format or MSPs will not allow the program to execute.

## Troubleshooting

### Common Issues

- **API timeout errors**: Ensure the `timeout` setting is at least 120 seconds. DuoLogSync enforces this minimum to
  comply with Duo API rate limits.
- **Checkpoint file errors**: Verify the checkpoint directory exists and has write permissions.
- **FILE backlog replay errors**: Verify the checkpoint directory and FILE destination path are writable. Existing FILE
  backlog files are replayed on startup and resumed if replay is interrupted.
- **FILE permission errors**: Verify the DuoLogSync process user can create directories and write to the configured
  `filepath`.
- **Disk full errors (FILE output)**: When disk-full is detected, DuoLogSync shuts down immediately by design. Free disk
  space/quota and restart.
- **SSL certificate errors**: For TCPSSL protocol, ensure the certificate file path is correct and the file contains
  valid certificates.
- **Timezone issues**: DuoLogSync must run on a system set to UTC/GMT timezone.
- **Logs not appearing**: Verify your receiving server is running and accessible at the configured hostname and port, or
  verify FILE `filepath` points to the expected destination.

---

## Support

For issues and questions:

- Open an issue on [GitHub](https://github.com/duosecurity/duo_log_sync/issues)
- Contact Duo Support at support@duosecurity.com
- Visit the [Duo documentation](https://duo.com/docs) for additional resources
