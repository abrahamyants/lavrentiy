Set ws = CreateObject("WScript.Shell")
ws.Run """C:\Users\mykik\Lavrentiy\new\lavrentiy.exe""", 0, False
WScript.Sleep 3000
ws.Run "msedge --app=http://localhost:7878", 1, False
