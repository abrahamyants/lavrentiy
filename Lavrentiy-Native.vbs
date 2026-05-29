' Lavrentiy launcher — native pywebview/WebView2 window (v1.6.3+).
'
' Behavior:
'   1. Sets LAV_NATIVE=1 so Lavrentiy.exe enters its pywebview path.
'   2. Starts Lavrentiy.exe hidden (the pywebview window appears on its own).
'   3. No external browser involved — uses Edge WebView2 component via pythonnet.
'
' Result: one chromeless native-feeling window, rendered by the bundled
' WebView2 runtime instead of through the user's installed Chrome/Edge.
'
' Companion shortcut: Lavrentiy.vbs (default) uses Chrome/Edge in --app=
' mode instead. Both produce a chromeless dashboard window.
Option Explicit

Dim sh : Set sh = CreateObject("WScript.Shell")
Dim fso : Set fso = CreateObject("Scripting.FileSystemObject")
Dim scriptDir : scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Dim exePath : exePath = scriptDir & "\Lavrentiy.exe"

' Tell the launcher: take the native pywebview path.
sh.Environment("Process")("LAV_NATIVE") = "1"

' Hidden start (the pywebview window will surface on its own).
If fso.FileExists(exePath) Then
    sh.Run """" & exePath & """ --native", 0, False
End If
