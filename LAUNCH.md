# Launching Order Audit Workbench

On Windows, double-click **launch_hidden.vbs** to start the application without a command prompt window. Machine-specific `.lnk` shortcuts are not distributed. To create your own shortcut, point it to `wscript.exe` and pass the full path of `launch_hidden.vbs` on your computer as the argument.

`launch_hidden.vbs` starts the local service with `.venv\Scripts\pythonw.exe`, checks `http://127.0.0.1:8793` until it responds, and then opens Chrome. If the service is already running, it does not start a second Python process.

After updating the source files, restart the existing audit service before using the shortcut. An already-running Python service keeps the code it loaded at startup; opening another browser window does not reload it.

`start.bat` remains available as a console fallback. Double-clicking a `.bat` file can briefly show a Windows command window by design; use `launch_hidden.vbs` or your own shortcut for a fully hidden launch. Install the dependencies from `requirements.txt` first; a console server can also be started with `python app.py --port 8793`.

## Why startup is not instant

- Python needs a short time to load the workbook and audit modules.
- Chrome itself needs time to create a window/profile.
- The old launcher always waited two seconds, even if the service was ready earlier.

The new launcher replaces that fixed wait with a fast local readiness check. It opens Chrome as soon as the service is available, so the unnecessary fixed delay is removed.
