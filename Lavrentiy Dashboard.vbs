Set ws = CreateObject("WScript.Shell")
ws.Run """C:\Users\mykik\OneDrive\Desktop\Voice to Text_Lavrentiy 1.0.0\Voice to Text_Lavrentiy 1.0.0\new\lavrentiy.exe""", 0, False
WScript.Sleep 3000
ws.Run "msedge --app=http://localhost:7878", 1, False
