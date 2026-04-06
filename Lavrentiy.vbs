Set ws = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
scriptDir = fs.GetParentFolderName(WScript.ScriptFullName)

' Check if engine is already running
engineRunning = False
On Error Resume Next
http.Open "GET", "http://127.0.0.1:7878/api/state", False
http.setTimeouts 2000, 2000, 2000, 2000
http.Send
If http.Status = 200 Then engineRunning = True
On Error GoTo 0

If engineRunning Then
    ' Engine already running — open dashboard directly
    ws.Run "msedge --app=http://127.0.0.1:7878", 1, False
Else
    ' Engine not running — kill stale, start engine, open splash with game
    ws.Run "taskkill /F /IM pythonw.exe", 0, True
    WScript.Sleep 500
    ws.CurrentDirectory = scriptDir & "\engine"
    ws.Run """" & scriptDir & "\python\pythonw.exe"" """ & scriptDir & "\engine\lavrentiy.py""", 0, False
    ' Open LOCAL splash.html (always loads instantly, no server needed)
    ' Splash has tic-tac-toe game + polls engine + auto-redirects when ready
    ws.Run "msedge --app=""file:///" & Replace(scriptDir, "\", "/") & "/engine/splash.html""", 1, False
End If
