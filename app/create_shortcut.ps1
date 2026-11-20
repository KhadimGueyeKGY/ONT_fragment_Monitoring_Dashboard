# Malaria dashboard monitor: creates the shortcut on the Desktop and in the Start menu.
# Author: Khadim Gueye
# Run by Start_Dashboard_Windows.bat; it only writes a shortcut that is missing or points elsewhere.
param([switch]$Force)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root 'Malaria dashboard monitor.exe'
if (-not (Test-Path $target)) { $target = Join-Path $root 'Start_Dashboard_Windows.bat' }
$icon = Join-Path $root 'img\logo.ico'
$name = 'Malaria dashboard monitor.lnk'
$shell = New-Object -ComObject WScript.Shell
$places = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
foreach ($dir in $places) {
  if (-not $dir -or -not (Test-Path $dir)) { continue }
  $path = Join-Path $dir $name
  if ((Test-Path $path) -and -not $Force) {
    $old = $shell.CreateShortcut($path)
    if ($old.TargetPath -eq $target -and $old.IconLocation -like "$icon*") { continue }
  }
  $lnk = $shell.CreateShortcut($path)
  $lnk.TargetPath = $target
  $lnk.WorkingDirectory = $root
  $lnk.IconLocation = "$icon,0"
  $lnk.Description = 'ONT fragment monitoring dashboard, Malaria team IGH'
  $lnk.WindowStyle = 1
  $lnk.Save()
  Write-Output "Shortcut created: $path"
}
