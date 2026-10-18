' Launch a batch file with no visible window.
' Usage: wscript run_hidden.vbs <full-path-to-bat>
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
If WScript.Arguments.Count < 1 Then WScript.Quit 1
target = WScript.Arguments(0)
If Not fso.FileExists(target) Then
  target = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), target)
End If
sh.CurrentDirectory = fso.GetParentFolderName(target)
sh.Run "cmd /c """ & target & """", 0, False
