# Malaria dashboard monitor (ONT fragment monitoring). Author: Khadim Gueye
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

BARCODE_RE = re.compile(r"^(barcode\d+|unclassified)$", re.IGNORECASE)
READ_SUFFIXES = (".fastq", ".fastq.gz", ".fq", ".fq.gz")


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def os_label() -> str:
    if is_wsl():
        return "Windows (WSL)"
    return {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}.get(platform.system(), platform.system())


def _wslpath(flag: str, value: str) -> str | None:
    if not shutil.which("wslpath"):
        return None
    try:
        out = subprocess.run(["wslpath", flag, value], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def to_display_path(path: Path) -> str:
    """Path as the user knows it: C:\\... on Windows, POSIX elsewhere."""
    if is_wsl():
        win = _wslpath("-w", str(path))
        if win:
            return win
    return str(path)


def normalize_path(raw: str) -> Path:
    """Accept a path written for Windows, WSL, macOS or Linux and return a local path."""
    text = (raw or "").strip().strip('"').strip("'").strip()
    if text.lower().startswith("file://"):
        from urllib.parse import unquote, urlparse
        parsed = urlparse(text)
        text = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:", text):
            text = text[1:]
    if not text:
        raise ValueError("Empty path.")

    unc = re.match(r"^[\\/]{2}(wsl\$|wsl\.localhost)[\\/][^\\/]+(.*)$", text, re.IGNORECASE)
    if unc:
        text = unc.group(2).replace("\\", "/") or "/"

    drive = re.match(r"^([A-Za-z]):(?:[\\/](.*))?$", text)
    if drive:
        if is_wsl():
            converted = _wslpath("-u", text.replace("/", "\\"))
            if converted:
                return Path(converted)
            rest = (drive.group(2) or "").replace("\\", "/")
            return Path(f"/mnt/{drive.group(1).lower()}/{rest}")
        if platform.system() == "Windows":
            return Path(text)
        raise ValueError("This is a Windows path, but the dashboard is running on " + os_label() + ".")

    if text.startswith("\\\\"):
        raise ValueError("Network paths (\\\\server\\share) are not supported. Map the share to a drive letter first.")

    text = text.replace("\\", "/") if "\\" in text and "/" not in text else text
    return Path(os.path.expanduser(text))


def list_read_files(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.is_file() and p.name.lower().endswith(READ_SUFFIXES))
    except OSError:
        return []


def barcode_dirs(fastq_pass: Path, include_unclassified: bool = False) -> list[Path]:
    try:
        dirs = [p for p in fastq_pass.iterdir() if p.is_dir() and BARCODE_RE.match(p.name)]
    except OSError:
        return []
    if not include_unclassified:
        dirs = [p for p in dirs if p.name.lower() != "unclassified"]
    return sorted(dirs, key=lambda p: natural_key(p.name))


def natural_key(text: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def _looks_like_fastq_pass(folder: Path) -> bool:
    return bool(barcode_dirs(folder, include_unclassified=True)) or bool(list_read_files(folder))


def resolve_fastq_pass(raw: str) -> dict:
    """Find the fastq_pass folder from whatever the user selected."""
    path = normalize_path(raw)
    if not path.exists():
        raise ValueError(f"Folder not found: {to_display_path(path)}")
    if path.is_file():
        path = path.parent
    note = ""
    if BARCODE_RE.match(path.name) and _looks_like_fastq_pass(path.parent):
        path, note = path.parent, "A barcode folder was selected, its parent is used."

    found = path if (path.name == "fastq_pass" or _looks_like_fastq_pass(path)) else None
    candidates: list[Path] = []
    if found is None:
        deadline, visited = time.time() + 4, 0
        for root, dirs, _files in os.walk(path):
            visited += 1
            if visited > 3000 or time.time() > deadline:
                break
            depth = len(Path(root).relative_to(path).parts)
            if depth >= 4:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if "fastq_pass" in dirs:
                candidates.append(Path(root) / "fastq_pass")
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            found = candidates[0]
            note = "fastq_pass was found inside the selected folder."
            if len(candidates) > 1:
                note = f"{len(candidates)} fastq_pass folders found, the most recent one is used."
    if found is None:
        raise ValueError("No fastq_pass folder and no barcode folders were found here.")

    barcodes = barcode_dirs(found)
    return {
        "path": str(found),
        "display": to_display_path(found),
        "barcodes": len(barcodes),
        "unbarcoded": not barcodes and bool(list_read_files(found)),
        "note": note,
        "others": [to_display_path(c) for c in candidates[1:6]],
    }


def browse_roots() -> list[dict]:
    roots: list[dict] = []
    home = Path.home()
    if is_wsl():
        mnt = Path("/mnt")
        for d in sorted(mnt.iterdir()) if mnt.exists() else []:
            if len(d.name) == 1 and d.is_dir():
                roots.append({"label": f"{d.name.upper()}:\\", "path": str(d)})
        roots.append({"label": "Linux home", "path": str(home)})
    elif platform.system() == "Darwin":
        roots.append({"label": "Home", "path": str(home)})
        roots.append({"label": "Volumes", "path": "/Volumes"})
        roots.append({"label": "MinKNOW data", "path": "/Library/MinKNOW/data"})
    else:
        roots.append({"label": "Home", "path": str(home)})
        for p in ("/data", "/var/lib/minknow/data", "/media", "/mnt"):
            if Path(p).exists():
                roots.append({"label": p, "path": p})
        roots.append({"label": "/", "path": "/"})
    return [r for r in roots if Path(r["path"]).exists()]


def list_dirs(raw: str) -> dict:
    path = normalize_path(raw)
    if not path.is_dir():
        raise ValueError(f"Not a folder: {raw}")
    entries = []
    try:
        for child in sorted(path.iterdir(), key=lambda p: natural_key(p.name)):
            if child.name.startswith(".") or child.name.startswith("$"):
                continue
            try:
                if child.is_dir():
                    entries.append({"name": child.name, "path": str(child)})
            except OSError:
                continue
    except PermissionError:
        raise ValueError("Permission denied.")
    parent = str(path.parent) if path.parent != path else None
    return {
        "path": str(path),
        "display": to_display_path(path),
        "parent": parent,
        "entries": entries[:2000],
        "is_fastq_pass": path.name == "fastq_pass" or bool(barcode_dirs(path)),
    }


# Windows: the Explorer style folder window (address bar, search, quick access). If it cannot be
# created, the older folder tree window is used instead.
_PS_PICKER = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false; Opacity=0; StartPosition='CenterScreen'}
$owner.Show(); $owner.Activate()
$title = 'Select the fastq_pass folder of the run'
$picked = $null
try {
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ExplorerFolderPicker {
  [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")] class FileOpenDialog {}
  [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IFileOpenDialog {
    [PreserveSig] int Show(IntPtr owner);
    void SetFileTypes(); void SetFileTypeIndex(); void GetFileTypeIndex(); void Advise(); void Unadvise();
    void SetOptions(uint options); void GetOptions(); void SetDefaultFolder(); void SetFolder(); void GetFolder();
    void GetCurrentSelection(); void SetFileName(); void GetFileName();
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
    void SetFileNameLabel();
    void GetResult(out IShellItem item);
  }
  [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellItem {
    void BindToHandler(); void GetParent();
    void GetDisplayName(uint sigdn, [MarshalAs(UnmanagedType.LPWStr)] out string name);
  }
  public static string Pick(IntPtr owner, string title) {
    IFileOpenDialog dialog = (IFileOpenDialog)new FileOpenDialog();
    dialog.SetOptions(0x20 | 0x40 | 0x800);
    dialog.SetTitle(title);
    dialog.SetOkButtonLabel("Select folder");
    if (dialog.Show(owner) != 0) return "";
    IShellItem item; dialog.GetResult(out item);
    string path; item.GetDisplayName(0x80058000, out path);
    return path;
  }
}
'@
  $picked = [ExplorerFolderPicker]::Pick($owner.Handle, $title)
} catch {
  $d = New-Object System.Windows.Forms.FolderBrowserDialog
  $d.Description = $title
  $d.ShowNewFolderButton = $false
  if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { $picked = $d.SelectedPath }
}
$owner.Close()
if ($picked) { Write-Output $picked }
"""


def pick_folder() -> str | None:
    """Open the native folder dialog of the operating system. Returns None if cancelled."""
    system = platform.system()
    if is_wsl() or system == "Windows":
        ps = shutil.which("powershell.exe") or "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        out = subprocess.run([ps, "-NoProfile", "-STA", "-Command", _PS_PICKER],
                             capture_output=True, timeout=600, cwd="/mnt/c" if is_wsl() else None)
        value = out.stdout.decode("utf-8", errors="replace").strip()
        return value or None
    if system == "Darwin":
        out = subprocess.run(["osascript", "-e", 'POSIX path of (choose folder with prompt "Select the fastq_pass folder of the run")'],
                             capture_output=True, text=True, timeout=600)
        return out.stdout.strip() or None
    for cmd in (["zenity", "--file-selection", "--directory", "--title=Select the fastq_pass folder"],
                ["kdialog", "--getexistingdirectory", str(Path.home())]):
        if shutil.which(cmd[0]):
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            return out.stdout.strip() or None
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        value = filedialog.askdirectory(title="Select the fastq_pass folder")
        root.destroy()
        return value or None
    except Exception:
        raise RuntimeError("No folder dialog is available on this system. Use the built-in browser or paste the path.")


def open_in_file_manager(path: Path) -> None:
    if is_wsl():
        win = _wslpath("-w", str(path)) or str(path)
        subprocess.Popen(["explorer.exe", win], cwd="/mnt/c")
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(path)])
    elif platform.system() == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


_WIN_APP_BROWSERS = (
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
)


def open_browser(url: str) -> None:
    if is_wsl():
        # Edge or Chrome in app mode: its own window with the logo, no tabs and no address bar,
        # opened full screen (maximized) by open_window.ps1. The user can make it smaller.
        script = Path(__file__).resolve().parent / "windows" / "open_window.ps1"
        ps = shutil.which("powershell.exe") or "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        win_script = _wslpath("-w", str(script)) if script.exists() else None
        if win_script and os.path.exists(ps):
            try:
                subprocess.Popen([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                                  "-File", win_script, "-Url", url], cwd="/mnt/c",
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                pass
        for exe in _WIN_APP_BROWSERS:
            if os.path.exists(exe):
                try:
                    subprocess.Popen([exe, f"--app={url}", "--start-maximized"], cwd="/mnt/c",
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
                except OSError:
                    continue
        for cmd in (["cmd.exe", "/c", "start", "", url], ["explorer.exe", url]):
            if shutil.which(cmd[0]):
                try:
                    subprocess.Popen(cmd, cwd="/mnt/c", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
                except OSError:
                    continue
    elif platform.system() == "Darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"):
            if Path(f"/Applications/{app}.app").exists():
                try:
                    subprocess.Popen(["open", "-na", app, "--args", f"--app={url}"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
                except OSError:
                    continue
    elif platform.system() == "Linux":
        for exe in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"):
            if shutil.which(exe):
                try:
                    subprocess.Popen([exe, f"--app={url}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                    return
                except OSError:
                    continue
    try:
        webbrowser.open(url, new=2)
    except Exception:
        print(f"Open {url} in your browser.", file=sys.stderr)
