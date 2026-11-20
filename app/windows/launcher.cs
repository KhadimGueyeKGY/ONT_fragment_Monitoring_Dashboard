// Malaria dashboard monitor, Windows launcher.
// Author: Khadim Gueye
//
// Starts the dashboard without a console window: a small start window with the logo shows the
// progress, then the dashboard opens in its own window and an icon stays near the clock
// (Open dashboard, Show log, Quit). If WSL is missing or not usable, Start_Dashboard_Windows.bat
// is opened instead, because it explains how to install it.
// Build: app\windows\build_launcher.bat
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Malaria dashboard monitor")]
[assembly: System.Reflection.AssemblyProduct("Malaria dashboard monitor")]
[assembly: System.Reflection.AssemblyCompany("Institute of Genomics and Global Health")]
[assembly: System.Reflection.AssemblyCopyright("Khadim Gueye")]

static class Program
{
    [STAThread]
    static void Main()
    {
        bool first;
        using (var mutex = new Mutex(true, "MalariaDashboardMonitorLauncher", out first))
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            if (!first)
            {
                // Already running: the dashboard itself reopens its window.
                Launcher.StartHidden(root, true);
                return;
            }
            if (!Launcher.WslReady())
            {
                string bat = Path.Combine(root, "Start_Dashboard_Windows.bat");
                Process.Start(new ProcessStartInfo(bat) { UseShellExecute = true, WorkingDirectory = root });
                return;
            }
            Application.Run(new Launcher(root));
        }
    }
}

class Launcher : Form
{
    readonly string root;
    readonly string logPath;
    readonly Label status = new Label();
    readonly NotifyIcon tray = new NotifyIcon();
    readonly StringBuilder tail = new StringBuilder();
    Process proc;
    string url;
    bool ready, quitting;

    public Launcher(string root)
    {
        this.root = root;
        string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MalariaDashboardMonitor");
        Directory.CreateDirectory(dir);
        logPath = Path.Combine(dir, "dashboard.log");
        File.WriteAllText(logPath, "");

        Text = "Malaria dashboard monitor";
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.CenterScreen;
        Size = new Size(440, 300);
        BackColor = Color.White;
        ShowInTaskbar = true;
        string ico = Path.Combine(root, "img", "logo.ico");
        if (File.Exists(ico)) Icon = new Icon(ico);

        var border = new Panel { Dock = DockStyle.Fill, Padding = new Padding(1), BackColor = Color.FromArgb(29, 78, 216) };
        var inner = new Panel { Dock = DockStyle.Fill, BackColor = Color.White };
        border.Controls.Add(inner);
        Controls.Add(border);

        var logo = new PictureBox { SizeMode = PictureBoxSizeMode.Zoom, Size = new Size(110, 110), Location = new Point(165, 22) };
        string png = Path.Combine(root, "img", "icon_256.png");
        if (File.Exists(png)) logo.Image = Image.FromFile(png);
        var title = new Label
        {
            Text = "Malaria dashboard monitor", Font = new Font("Segoe UI Semibold", 15f), ForeColor = Color.FromArgb(15, 23, 42),
            AutoSize = false, TextAlign = ContentAlignment.MiddleCenter, Size = new Size(438, 34), Location = new Point(0, 140)
        };
        status.Text = "Starting...";
        status.Font = new Font("Segoe UI", 9.5f);
        status.ForeColor = Color.FromArgb(91, 107, 129);
        status.AutoSize = false;
        status.TextAlign = ContentAlignment.MiddleCenter;
        status.Size = new Size(400, 40);
        status.Location = new Point(19, 178);
        var bar = new ProgressBar { Style = ProgressBarStyle.Marquee, MarqueeAnimationSpeed = 25, Size = new Size(320, 6), Location = new Point(59, 230) };
        var by = new Label
        {
            Text = "Khadim Gueye, Institute of Genomics and Global Health", Font = new Font("Segoe UI", 8f),
            ForeColor = Color.FromArgb(148, 163, 184), AutoSize = false, TextAlign = ContentAlignment.MiddleCenter,
            Size = new Size(438, 20), Location = new Point(0, 262)
        };
        inner.Controls.AddRange(new Control[] { logo, title, status, bar, by });

        tray.Icon = Icon ?? SystemIcons.Application;
        tray.Text = "Malaria dashboard monitor";
        var menu = new ContextMenuStrip();
        menu.Items.Add("Open dashboard", null, (s, e) => OpenDashboard());
        menu.Items.Add("Show log", null, (s, e) => Process.Start(new ProcessStartInfo("notepad.exe", "\"" + logPath + "\"")));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Quit", null, (s, e) => Quit());
        tray.ContextMenuStrip = menu;
        tray.DoubleClick += (s, e) => OpenDashboard();
        tray.Visible = true;

        TopMost = true;
        Shown += (s, e) => { Activate(); BringToFront(); StartBackend(); };
        FormClosing += (s, e) => { if (!quitting && ready) { e.Cancel = true; Hide(); } };
    }

    public static bool WslReady()
    {
        return Run("wsl.exe", "-l -q") == 0 && Run("wsl.exe", "-e bash -c \"exit 0\"") == 0;
    }

    static int Run(string exe, string args)
    {
        try
        {
            var p = Process.Start(new ProcessStartInfo(exe, args) { CreateNoWindow = true, UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true });
            p.StandardOutput.ReadToEnd();
            if (!p.WaitForExit(30000)) return -1;
            return p.ExitCode;
        }
        catch { return -1; }
    }

    public static Process StartHidden(string root, bool waitShort)
    {
        var psi = new ProcessStartInfo("wsl.exe", "--cd \"" + root + "\\.\" -- bash ./app/bootstrap.sh")
        {
            CreateNoWindow = true, UseShellExecute = false, WorkingDirectory = root,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        var p = Process.Start(psi);
        if (waitShort) { p.StandardOutput.ReadToEnd(); p.WaitForExit(60000); }
        return p;
    }

    void StartBackend()
    {
        try
        {
            string shortcut = Path.Combine(root, "app", "create_shortcut.ps1");
            if (File.Exists(shortcut))
                Run("powershell.exe", "-NoProfile -ExecutionPolicy Bypass -File \"" + shortcut + "\"");
        }
        catch { }
        proc = StartHidden(root, false);
        proc.EnableRaisingEvents = true;
        proc.OutputDataReceived += (s, e) => OnLine(e.Data);
        proc.ErrorDataReceived += (s, e) => OnLine(e.Data);
        proc.Exited += (s, e) => BeginInvoke((Action)OnExit);
        proc.BeginOutputReadLine();
        proc.BeginErrorReadLine();
    }

    void OnLine(string line)
    {
        if (line == null) return;
        line = line.Replace("\r", " ").Trim();
        if (line.Length == 0) return;
        var w = Regex.Match(line, @"working (\d+)s\s*$");
        if (w.Success)
        {
            string secs = w.Groups[1].Value;
            BeginInvoke((Action)(() => { if (!status.Text.EndsWith("s)")) status.Text += " (0s)"; status.Text = Regex.Replace(status.Text, @"\(\d+s\)$", "(" + secs + "s)"); }));
            return;
        }
        try { File.AppendAllText(logPath, line + Environment.NewLine); } catch { }
        lock (tail) { tail.AppendLine(line); if (tail.Length > 6000) tail.Remove(0, tail.Length - 6000); }

        string shown = null;
        if (line.StartsWith("[1/4]")) shown = "Checking conda...";
        else if (line.StartsWith("[2/4]")) shown = "Checking the software environment...";
        else if (line.Contains("Creating it")) shown = "Installing the software environment.\nThis is done once and takes a few minutes.";
        else if (line.Contains("Updating it")) shown = "Updating the software environment...";
        else if (line.Contains("Downloading Miniforge")) shown = "Downloading conda (first start only)...";
        else if (line.StartsWith("[4/4]")) shown = "Starting the dashboard...";
        var m = Regex.Match(line, @"(?:running|already running) at (http://127\.0\.0\.1:\d+)");
        if (m.Success)
        {
            url = m.Groups[1].Value;
            BeginInvoke((Action)OnReady);
        }
        if (shown != null) BeginInvoke((Action)(() => status.Text = shown));
    }

    void OnReady()
    {
        if (ready) return;
        ready = true;
        Hide();
        tray.ShowBalloonTip(4000, "Malaria dashboard monitor is running",
            "Use this icon near the clock to open the dashboard or to quit.", ToolTipIcon.Info);
    }

    void OnExit()
    {
        int code = proc.ExitCode;
        tray.Visible = false;
        if (code != 0 && !quitting)
        {
            string text;
            lock (tail) { text = tail.ToString(); }
            if (text.Length > 1500) text = "..." + text.Substring(text.Length - 1500);
            MessageBox.Show("The dashboard stopped with an error.\n\n" + text + "\n\nFull log: " + logPath,
                            "Malaria dashboard monitor", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        quitting = true;
        Close();
        Application.Exit();
    }

    void OpenDashboard()
    {
        if (url == null) { Show(); Activate(); return; }
        string script = Path.Combine(root, "app", "windows", "open_window.ps1");
        if (File.Exists(script))
        {
            Process.Start(new ProcessStartInfo("powershell.exe",
                "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + script + "\" -Url " + url)
                { CreateNoWindow = true, UseShellExecute = false });
            return;
        }
        string[] browsers = {
            @"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            @"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            @"C:\Program Files\Google\Chrome\Application\chrome.exe",
            @"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" };
        foreach (var b in browsers)
            if (File.Exists(b)) { Process.Start(b, "--app=" + url + " --start-maximized"); return; }
        Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
    }

    void Quit()
    {
        if (MessageBox.Show("Close the Malaria dashboard monitor? Monitoring in progress will stop.",
                            "Malaria dashboard monitor", MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK) return;
        quitting = true;
        try
        {
            if (url != null)
            {
                using (var wc = new WebClient())
                {
                    wc.Headers[HttpRequestHeader.ContentType] = "application/json";
                    wc.UploadString(url + "/api/quit", "{}");
                }
            }
        }
        catch { }
        ThreadPool.QueueUserWorkItem(_ =>
        {
            if (proc != null && !proc.WaitForExit(15000)) { try { proc.Kill(); } catch { } }
        });
    }
}
