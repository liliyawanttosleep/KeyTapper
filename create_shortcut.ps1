# Creates a "KeyTapper" shortcut on the desktop that launches the app with its icon.
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyw = Get-Command pythonw -ErrorAction SilentlyContinue
if (-not $pyw) { $pyw = Get-Command pyw -ErrorAction SilentlyContinue }
if (-not $pyw) {
    Write-Host "pythonw was not found on PATH. Install Python first."
    exit 1
}
$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $desktop "KeyTapper.lnk"))
$lnk.TargetPath = $pyw.Source
$lnk.Arguments = '"' + (Join-Path $dir "keytapper.py") + '"'
$lnk.WorkingDirectory = $dir
$lnk.IconLocation = (Join-Path $dir "assets\keytapper.ico") + ",0"
$lnk.Description = "KeyTapper"
$lnk.Save()
Write-Host "Shortcut created on the desktop."
