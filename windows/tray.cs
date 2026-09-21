// Claude Switcher tray app (Windows). Built by install.ps1 with the csc.exe that ships with Windows
// (.NET Framework 4, C# 5), so nothing extra has to be installed.
//
// It mirrors the macOS menu bar app: a tinted Claude symbol per account, a menu to switch or add accounts,
// the Ctrl+Alt+PageDown hotkey, and the background work launchd does on macOS (sync every 20 s,
// "open the account used last", finishing "Add account…").
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Management;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class Profile { public string key; public string label; public string data_dir; public bool primary; }

class HotkeyWindow : NativeWindow, IDisposable {
    [DllImport("user32.dll")] static extern bool RegisterHotKey(IntPtr h, int id, uint mods, uint vk);
    [DllImport("user32.dll")] static extern bool UnregisterHotKey(IntPtr h, int id);
    public event EventHandler Pressed;
    public bool Ok;
    public HotkeyWindow() {
        CreateHandle(new CreateParams());
        // MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, VK_NEXT (Page Down). Ctrl+PageDown alone is the browser's next-tab key.
        Ok = RegisterHotKey(Handle, 1, 0x1 | 0x2 | 0x4000, 0x22);
    }
    protected override void WndProc(ref Message m) {
        if (m.Msg == 0x312 && Pressed != null) Pressed(this, EventArgs.Empty);
        base.WndProc(ref m);
    }
    public void Dispose() { UnregisterHotKey(Handle, 1); DestroyHandle(); }
}

class Tray : ApplicationContext {
    static readonly string Base = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "claude-switcher");
    static readonly string AppExe = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"AnthropicClaude\claude.exe");
    static readonly Color[] Palette = {
        Color.FromArgb(0xD9, 0x78, 0x57), Color.FromArgb(0x26, 0xBF, 0xA4), Color.FromArgb(0x4A, 0x8F, 0xED),
        Color.FromArgb(0x9C, 0x6B, 0xE6), Color.FromArgb(0xE8, 0x61, 0x9E), Color.FromArgb(0xE6, 0xB8, 0x33) };

    NotifyIcon icon = new NotifyIcon();
    HotkeyWindow hotkey = new HotkeyWindow();
    List<Profile> profiles = new List<Profile>();
    Dictionary<int, Icon> icons = new Dictionary<int, Icon>();
    Icon idle;
    string cur = "none";
    Process syncProc;
    int tick;

    Tray() {
        idle = MakeIcon(Color.Gray);
        icon.Icon = idle;
        icon.Text = "Claude Switcher";
        icon.Visible = true;
        icon.ContextMenuStrip = new ContextMenuStrip();
        icon.ContextMenuStrip.Opening += delegate { BuildMenu(); };
        icon.MouseUp += delegate(object s, MouseEventArgs e) {
            if (e.Button == MouseButtons.Left) typeof(NotifyIcon).GetMethod("ShowContextMenu",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic).Invoke(icon, null);
        };
        hotkey.Pressed += delegate { Py(false, "claude_switch.py"); };
        LoadProfiles();
        Poll();
        var t = new System.Windows.Forms.Timer { Interval = 3000 };
        t.Tick += delegate { tick++; Background(); Poll(); };
        t.Start();
    }

    // ---------- helpers ----------
    static string Norm(string p) {
        try { p = Path.GetFullPath(p.Trim().Trim('"')); } catch { }
        return p.TrimEnd('\\').ToLowerInvariant();
    }

    // pythonw.exe path written by install.ps1; runs the CLI without a console window
    static string Python() { return File.ReadAllText(Path.Combine(Base, "python.txt")).Trim(); }

    static Process Py(bool capture, string script, params string[] args) {
        var psi = new ProcessStartInfo(Python()) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = capture };
        psi.Arguments = "\"" + Path.Combine(Base, "lib", script) + "\"";
        foreach (var a in args) psi.Arguments += " \"" + a + "\"";
        try { return Process.Start(psi); } catch { return null; }
    }

    void LoadProfiles() {
        var p = Py(true, "claude_switch.py", "profiles", "--json");
        if (p == null) return;
        string json = p.StandardOutput.ReadToEnd();
        p.WaitForExit(15000);
        try { profiles = new JavaScriptSerializer().Deserialize<List<Profile>>(json); } catch { }
    }

    string Running() {
        var found = new HashSet<string>();
        try {
            using (var q = new ManagementObjectSearcher("SELECT CommandLine FROM Win32_Process WHERE Name='claude.exe'"))
                foreach (ManagementObject o in q.Get()) {
                    string cmd = (o["CommandLine"] as string) ?? "";
                    if (cmd.ToLowerInvariant().IndexOf(@"\anthropicclaude\") < 0 || cmd.Contains("--type=")) continue;
                    var m = Regex.Match(cmd, "--user-data-dir=(.*?)(?:\"|\\s--|$)");
                    string dir = Norm(m.Success ? m.Groups[1].Value : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Claude"));
                    foreach (var pr in profiles) if (Norm(pr.data_dir) == dir) found.Add(pr.key);
                }
        } catch { return cur; }
        if (found.Count > 1) return "many";
        foreach (var k in found) return k;
        return "none";
    }

    int Index(string key) { for (int i = 0; i < profiles.Count; i++) if (profiles[i].key == key) return i; return -1; }
    string Label(string key) { int i = Index(key); return i < 0 ? key : profiles[i].label; }

    void Poll() {
        string now = Running();
        int i = Index(now);
        // The Start menu, a login item or a reboot always open the default account. If another one was used
        // last, `restore` switches to it (no-op otherwise, or with "restore_last": false).
        if (cur == "none" && i >= 0 && profiles[i].primary) Py(false, "claude_switch.py", "restore");
        cur = now;
        if (i < 0) { icon.Icon = idle; icon.Text = now == "many" ? "Claude Switcher: several accounts running" : "Claude Switcher: Claude is not running"; return; }
        if (!icons.ContainsKey(i)) icons[i] = MakeIcon(Palette[i % Palette.Length]);
        icon.Icon = icons[i];
        string t = "Claude Switcher: " + profiles[i].label;
        icon.Text = t.Length > 63 ? t.Substring(0, 63) : t;
    }

    void Background() {
        if (tick % 7 == 0 && (syncProc == null || syncProc.HasExited)) syncProc = Py(false, "cs_sync.py");  // ~20 s
        if (tick % 5 == 0) {  // ~15 s: finish "Add account…" once the new account has opened its Code tab
            if (File.Exists(Path.Combine(Base, "pending-setup"))) {
                var p = Py(false, "claude_switch.py", "setup", "--quiet");
                if (p != null) { p.WaitForExit(30000); LoadProfiles(); }
            } else if (tick % 20 == 0) LoadProfiles();
        }
    }

    void BuildMenu() {
        var m = icon.ContextMenuStrip;
        m.Items.Clear();
        m.Items.Add(new ToolStripMenuItem("Now: " + (cur == "none" ? "not running" : cur == "many" ? "several running" : Label(cur))) { Enabled = false });
        var next = new ToolStripMenuItem("Switch to next account");
        next.ShortcutKeyDisplayString = hotkey.Ok ? "Ctrl+Alt+PgDn" : "";
        next.Click += delegate { Py(false, "claude_switch.py"); };
        m.Items.Add(next);
        m.Items.Add(new ToolStripSeparator());
        for (int i = 0; i < profiles.Count; i++) {
            var p = profiles[i];
            if (!icons.ContainsKey(i)) icons[i] = MakeIcon(Palette[i % Palette.Length]);
            var it = new ToolStripMenuItem(p.label + "  (" + p.key + ")", icons[i].ToBitmap()) { Checked = p.key == cur };
            string key = p.key;
            it.Click += delegate { Py(false, "claude_switch.py", key); };
            m.Items.Add(it);
        }
        m.Items.Add(new ToolStripSeparator());
        var add = new ToolStripMenuItem("Add account…");
        add.Click += delegate { Py(false, "claude_switch.py", "add"); };
        m.Items.Add(add);
        var quit = new ToolStripMenuItem("Quit Claude Switcher");
        quit.Click += delegate { icon.Visible = false; hotkey.Dispose(); ExitThread(); };
        m.Items.Add(quit);
    }

    // ---------- icon: the installed app's own symbol, tinted per account ----------
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern uint PrivateExtractIcons(string file, int index, int cx, int cy, IntPtr[] icons, int[] ids, uint n, uint flags);
    [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr h);

    static Bitmap AppBitmap(int size) {
        var h = new IntPtr[1];
        var ids = new int[1];
        if (!File.Exists(AppExe) || PrivateExtractIcons(AppExe, 0, size, size, h, ids, 1, 0) == 0 || h[0] == IntPtr.Zero) return null;
        var bmp = (Bitmap)Icon.FromHandle(h[0]).ToBitmap().Clone();
        DestroyIcon(h[0]);
        return bmp;
    }

    // The symbol is the saturated (orange) part of the app icon; everything else becomes transparent.
    // No usable icon: a plain dot in the account colour.
    public static Bitmap Tinted(Color c, int size) {
        var src = AppBitmap(size);
        var dst = new Bitmap(size, size, PixelFormat.Format32bppArgb);
        int hits = 0;
        if (src != null)
            for (int y = 0; y < size; y++)
                for (int x = 0; x < size; x++) {
                    Color p = src.GetPixel(x, y);
                    int max = Math.Max(p.R, Math.Max(p.G, p.B)), min = Math.Min(p.R, Math.Min(p.G, p.B));
                    double sat = max == 0 ? 0 : (max - min) / (double)max;
                    int a = sat < 0.25 ? 0 : (int)(p.A * Math.Min(1.0, (sat - 0.25) / 0.25));
                    if (a > 0) { hits++; dst.SetPixel(x, y, Color.FromArgb(a, c)); }
                }
        if (hits < size * size / 40) {
            using (var g = Graphics.FromImage(dst)) {
                g.Clear(Color.Transparent);
                g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                using (var b = new SolidBrush(c)) g.FillEllipse(b, size / 8, size / 8, size * 3 / 4, size * 3 / 4);
            }
        }
        return dst;
    }

    static Icon MakeIcon(Color c) { return Icon.FromHandle(Tinted(c, 32).GetHicon()); }

    [STAThread]
    static void Main(string[] args) {
        if (args.Length == 2 && args[0] == "--render-icons") {  // CI / debugging: write the tinted icons as PNG
            Directory.CreateDirectory(args[1]);
            for (int i = 0; i < Palette.Length; i++) Tinted(Palette[i], 64).Save(Path.Combine(args[1], "account-" + i + ".png"), ImageFormat.Png);
            var raw = AppBitmap(64);
            if (raw != null) raw.Save(Path.Combine(args[1], "app-icon.png"), ImageFormat.Png);
            return;
        }
        bool first;
        using (new Mutex(true, "ClaudeSwitcherTray", out first)) {
            if (!first) return;
            Application.EnableVisualStyles();
            Application.Run(new Tray());
        }
    }
}
