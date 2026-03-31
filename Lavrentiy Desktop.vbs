Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\georg\Documents\GitHub\lavrentiy"
WshShell.Run "pythonw desktop.py", 0, False
