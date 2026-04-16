Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\georg\Documents\GitHub\lavrentiy"
WshShell.Run "pythonw lavrentiy.py", 0, False
