# Malaria dashboard monitor (ONT fragment monitoring). Author: Khadim Gueye
# Opens the dashboard in its own window (Edge or Chrome app window) and maximizes it.
# Windows that were already open are left as they are; the user can make the new one smaller.
param([Parameter(Mandatory = $true)][string]$Url, [string]$Title = 'ONT Fragment Monitoring', [int]$Seconds = 25)
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class DashboardWindow {
  delegate bool EnumProc(IntPtr hwnd, IntPtr param);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr p);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
  public static List<long> Find(string title) {
    var found = new List<long>();
    EnumWindows((h, p) => {
      if (IsWindowVisible(h)) {
        var sb = new StringBuilder(512);
        GetWindowText(h, sb, 512);
        if (sb.ToString().StartsWith(title)) found.Add(h.ToInt64());
      }
      return true;
    }, IntPtr.Zero);
    return found;
  }
  public static void Maximize(long h) { ShowWindow(new IntPtr(h), 3); SetForegroundWindow(new IntPtr(h)); }
}
'@
$before = @{}
foreach ($h in [DashboardWindow]::Find($Title)) { $before[$h] = $true }

$browsers = @(
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$exe = $browsers | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($exe) { Start-Process -FilePath $exe -ArgumentList "--app=$Url", '--start-maximized' }
else { Start-Process $Url; exit 0 }

$deadline = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $deadline) {
  $new = [DashboardWindow]::Find($Title) | Where-Object { -not $before.ContainsKey($_) }
  if ($new) { foreach ($h in $new) { [DashboardWindow]::Maximize($h) }; break }
  Start-Sleep -Milliseconds 250
}
