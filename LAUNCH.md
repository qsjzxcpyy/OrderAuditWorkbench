# Launching Order Audit Workbench

Use **LaunchOrderAudit.lnk** to start the application. It targets Windows Script Host directly, so no command prompt window is shown.

`launch_hidden.vbs` starts the local service with `.venv\Scripts\pythonw.exe`, checks `http://127.0.0.1:8793` until it responds, and then opens Chrome. If the service is already running, it does not start a second Python process.

`start.bat` remains available as a console fallback. Double-clicking a `.bat` file can briefly show a Windows command window by design; use the `.lnk` shortcut for a fully hidden launch.

## Why startup is not instant

- Python needs a short time to load the workbook and audit modules.
- Chrome itself needs time to create a window/profile.
- The old launcher always waited two seconds, even if the service was ready earlier.

The new launcher replaces that fixed wait with a fast local readiness check. It opens Chrome as soon as the service is available, so the unnecessary fixed delay is removed.
