Option Explicit

Dim shell, fso, appDir, executable, command, index, argument
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
executable = fso.BuildPath(appDir, "safevault.exe")
command = """" & executable & """"

For index = 0 To WScript.Arguments.Count - 1
  argument = Replace(WScript.Arguments(index), """", """""")
  command = command & " """ & argument & """"
Next

shell.Run command, 0, False
