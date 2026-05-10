' Lavrentiy launcher (v1.6.1+).
'
' Behavior:
'   1. Sets LAV_NO_BROWSER=1 so the engine does NOT auto-open the default
'      browser (which was popping a Chrome tab on every launch).
'   2. Starts Lavrentiy.exe hidden — no cmd flash, no extra windows.
'   3. Polls localhost:7878 until the engine binds (max 30s).
'   4. Opens the dashboard in chromeless --app mode via Edge -> Chrome ->
'      default browser (in that fallback order).
'
' Result: one window, chromeless, native-feeling. Engine running underneath.
Option Explicit

Dim sh : Set sh = CreateObject("WScript.Shell")
Dim fso : Set fso = CreateObject("Scripting.FileSystemObject")
Dim scriptDir : scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Dim exePath : exePath = scriptDir & "\Lavrentiy.exe"
Dim url : url = "http://localhost:7878/"

' Tell the engine: do NOT auto-open the default browser; this script owns the dashboard window.
sh.Environment("Process")("LAV_NO_BROWSER") = "1"

' Start engine hidden and don't wait. SW_HIDE = 0.
If fso.FileExists(exePath) Then
    sh.Run """" & exePath & """", 0, False
End If

' Wait for /api/state to respond (max 30s, 250ms poll).
Dim t0, http
t0 = Timer
Do While (Timer - t0) < 30
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.Open "GET", url & "api/state", False
    http.Send
    If Err.Number = 0 And http.Status = 200 Then
        On Error Goto 0
        Exit Do
    End If
    Err.Clear
    On Error Goto 0
    WScript.Sleep 250
Loop

' Open dashboard in --app mode. Try Edge -> Chrome -> default browser.
Dim browsers, p, launched
launched = False
browsers = Array( _
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", _
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe", _
    "C:\Program Files\Google\Chrome\Application\chrome.exe", _
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" _
)
For Each p In browsers
    If fso.FileExists(p) Then
        sh.Run """" & p & """ --app=" & url & " --window-size=1100,780", 1, False
        launched = True
        Exit For
    End If
Next
If Not launched Then sh.Run url, 1, False
