Option Explicit

Const APP_PORT = 8793
Const WAIT_STEP_MS = 100
Const MAX_WAIT_MS = 12000

Dim fso, shell, root, parent, appPath, pythonwPath, url, chromePath
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
parent = fso.GetParentFolderName(root)
appPath = fso.BuildPath(root, "app.py")
pythonwPath = fso.BuildPath(parent, ".venv\Scripts\pythonw.exe")
url = "http://127.0.0.1:" & APP_PORT

' Start only when the local service is not already available.
If Not IsServiceReady(url) Then
    If Not fso.FileExists(pythonwPath) Then
        pythonwPath = "pythonw.exe"
    End If
    shell.Run Quote(pythonwPath) & " " & Quote(appPath) & " --port " & APP_PORT, 0, False
End If

' Poll for readiness instead of always sleeping for a fixed two seconds.
WaitForService url, MAX_WAIT_MS, WAIT_STEP_MS

' Open Chrome when possible; otherwise use the default browser.
chromePath = FindChrome(shell, fso)
If Len(chromePath) > 0 Then
    shell.Run Quote(chromePath) & " --new-window " & Quote(url), 0, False
Else
    shell.Run url, 0, False
End If

Function IsServiceReady(targetUrl)
    Dim request
    IsServiceReady = False
    On Error Resume Next
    Set request = CreateObject("WinHttp.WinHttpRequest.5.1")
    request.SetTimeouts 50, 50, 100, 100
    request.Open "GET", targetUrl, False
    request.Send
    IsServiceReady = (Err.Number = 0 And request.Status >= 200 And request.Status < 500)
    Err.Clear
    On Error GoTo 0
End Function

Sub WaitForService(targetUrl, maxWait, stepMs)
    Dim elapsed
    For elapsed = 0 To maxWait Step stepMs
        If IsServiceReady(targetUrl) Then Exit Sub
        WScript.Sleep stepMs
    Next
End Sub

Function FindChrome(shellObject, fileSystem)
    Dim candidates, candidate, i
    candidates = Array( _
        shellObject.ExpandEnvironmentStrings("%ProgramFiles%") & "\Google\Chrome\Application\chrome.exe", _
        shellObject.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Google\Chrome\Application\chrome.exe", _
        shellObject.ExpandEnvironmentStrings("%LocalAppData%") & "\Google\Chrome\Application\chrome.exe" _
    )
    FindChrome = ""
    For i = 0 To UBound(candidates)
        candidate = candidates(i)
        If fileSystem.FileExists(candidate) Then
            FindChrome = candidate
            Exit Function
        End If
    Next
End Function

Function Quote(value)
    Quote = Chr(34) & Replace(value, Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function

