import Cocoa
import Carbon.HIToolbox

// Claude Switcher menu bar app. All real work is done by the `claude-switch` CLI.
// Hotkey: ⌘ + Page Down (next account). Icon: the Claude symbol from the installed app, one colour per account.

let cli = NSHomeDirectory() + "/.local/bin/claude-switch"
// One colour per account, in order: A orange, B teal, then blue, purple, pink, yellow.
let palette: [NSColor] = [
    NSColor(srgbRed: 0.85, green: 0.47, blue: 0.34, alpha: 1),  // #D97857
    NSColor(srgbRed: 0.15, green: 0.75, blue: 0.64, alpha: 1),  // #26BFA4
    NSColor(srgbRed: 0.29, green: 0.56, blue: 0.93, alpha: 1),  // #4A8FED
    NSColor(srgbRed: 0.61, green: 0.42, blue: 0.90, alpha: 1),  // #9C6BE6
    NSColor(srgbRed: 0.91, green: 0.38, blue: 0.62, alpha: 1),  // #E8619E
    NSColor(srgbRed: 0.90, green: 0.72, blue: 0.20, alpha: 1),  // #E6B833
]
struct Profile: Decodable { let key: String; let label: String }

func run(_ args: [String]) -> String {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
    p.arguments = [cli] + args
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = pipe
    try? p.run()
    p.waitUntilExit()
    return String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
        .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
}

/// 12 rounded rays of alternating length. Drawn in code so no third-party artwork is shipped.
func starIcon(_ color: NSColor, dimmed: Bool) -> NSImage {
    let size = NSSize(width: 18, height: 18)
    let img = NSImage(size: size, flipped: false) { rect in
        let c = NSPoint(x: rect.midX, y: rect.midY)
        (dimmed ? color.withAlphaComponent(0.35) : color).setStroke()
        for i in 0..<12 {
            let a = CGFloat(i) * .pi / 6 + .pi / 12
            let r: CGFloat = i % 2 == 0 ? 8.2 : 6.4
            let path = NSBezierPath()
            path.lineWidth = 1.9
            path.lineCapStyle = .round
            path.move(to: NSPoint(x: c.x + cos(a) * 1.6, y: c.y + sin(a) * 1.6))
            path.line(to: NSPoint(x: c.x + cos(a) * r, y: c.y + sin(a) * r))
            path.stroke()
        }
        return true
    }
    img.isTemplate = false
    return img
}

/// The real Claude symbol, taken at runtime from the user's own /Applications/Claude.app icon
/// (the repository ships no Anthropic artwork). Returns a mask: white glyph on transparent.
let claudeMask: CGImage? = {
    let icon = NSWorkspace.shared.icon(forFile: "/Applications/Claude.app")
    let side = 256
    var rect = NSRect(x: 0, y: 0, width: side, height: side)
    guard let src = icon.cgImage(forProposedRect: &rect, context: nil, hints: nil) else { return nil }
    var px = [UInt8](repeating: 0, count: side * side * 4)
    guard let ctx = CGContext(data: &px, width: side, height: side, bitsPerComponent: 8, bytesPerRow: side * 4,
                              space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
    else { return nil }
    ctx.draw(src, in: CGRect(x: 0, y: 0, width: side, height: side))
    var mask = [UInt8](repeating: 0, count: side * side)
    var minX = side, minY = side, maxX = -1, maxY = -1
    for y in 0..<side {
        for x in 0..<side {
            let i = (y * side + x) * 4
            guard px[i + 3] > 200 else { continue }
            let dx = Double(x - side / 2), dy = Double(y - side / 2)
            guard dx * dx + dy * dy < Double(side * side) * 0.12 else { continue }  // glyph area only, skip the icon's rim
            let r = Double(px[i]), g = Double(px[i + 1]), b = Double(px[i + 2])
            let l = (max(r, g, b) + min(r, g, b)) / 510      // lightness: glyph ≈ 0.95, background ≈ 0.58
            let v = min(1, max(0, (l - 0.66) / 0.22))
            mask[y * side + x] = UInt8(v * 255)
            if v > 0.5 { minX = min(minX, x); maxX = max(maxX, x); minY = min(minY, y); maxY = max(maxY, y) }
        }
    }
    guard maxX > minX, maxY > minY, (maxX - minX) > side / 4 else { return nil }  // no glyph found → fall back
    let w = maxX - minX + 1, h = maxY - minY + 1, s = max(w, h)
    var sq = [UInt8](repeating: 0, count: s * s)
    for y in 0..<h { for x in 0..<w { sq[(y + (s - h) / 2) * s + x + (s - w) / 2] = mask[(minY + y) * side + minX + x] } }
    guard let provider = CGDataProvider(data: Data(sq) as CFData) else { return nil }
    return CGImage(width: s, height: s, bitsPerComponent: 8, bitsPerPixel: 8, bytesPerRow: s,
                   space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGBitmapInfo(rawValue: 0),
                   provider: provider, decode: nil, shouldInterpolate: true, intent: .defaultIntent)
}()

/// Render once into a real bitmap. Drawing-handler images are drawn lazily, and menus did not show
/// the masked logo that way (the menu bar button did) — a plain bitmap shows everywhere.
func bitmap(_ img: NSImage) -> NSImage {
    let pt = img.size, scale: CGFloat = 2
    guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(pt.width * scale), pixelsHigh: Int(pt.height * scale),
                                     bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                     colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return img }
    rep.size = pt
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    img.draw(in: NSRect(origin: .zero, size: pt))
    NSGraphicsContext.restoreGraphicsState()
    let out = NSImage(size: pt)
    out.addRepresentation(rep)
    return out
}

func logoIcon(_ color: NSColor, dimmed: Bool) -> NSImage {
    guard let m = claudeMask else { return bitmap(starIcon(color, dimmed: dimmed)) }
    return bitmap(NSImage(size: NSSize(width: 18, height: 18), flipped: false) { rect in
        guard let g = NSGraphicsContext.current?.cgContext else { return false }
        // CGImage masks treat white as "draw"; an alpha-style grey mask needs clip(to:mask:) with an image mask.
        guard let imgMask = CGImage(maskWidth: m.width, height: m.height, bitsPerComponent: 8, bitsPerPixel: 8,
                                    bytesPerRow: m.width, provider: m.dataProvider!, decode: [1, 0], shouldInterpolate: true)
        else { return false }
        g.clip(to: rect.insetBy(dx: 0.5, dy: 0.5), mask: imgMask)
        (dimmed ? color.withAlphaComponent(0.35) : color).setFill()
        rect.fill()
        return true
    })
}

final class App: NSObject, NSApplicationDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let menu = NSMenu()
    let stateLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    var busy = false
    var profiles: [Profile] = []
    var previous = "none"

    func applicationDidFinishLaunching(_ n: Notification) {
        item.menu = menu
        rebuildMenu()
        refresh()
        Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in self?.refresh() }
        // After "Add account…", keep re-detecting session folders until the new account's one shows up.
        Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            let flag = NSHomeDirectory() + "/Library/Application Support/claude-switcher/pending-setup"
            guard let self = self, !self.busy, FileManager.default.fileExists(atPath: flag) else { return }
            DispatchQueue.global().async {
                let out = run(["setup", "--quiet"])
                DispatchQueue.main.async {
                    if out.contains("added") { self.rebuildMenu() }
                }
            }
        }
        registerHotKey()
    }

    func color(_ key: String) -> NSColor {
        let i = profiles.firstIndex { $0.key == key } ?? 0
        return palette[i % palette.count]
    }

    /// Menu = current state, "switch to next", one row per account (with its colour), quit.
    func rebuildMenu() {
        let data = run(["profiles", "--json"]).data(using: .utf8) ?? Data()
        profiles = (try? JSONDecoder().decode([Profile].self, from: data)) ?? []
        menu.removeAllItems()
        menu.addItem(stateLine)
        menu.addItem(.separator())
        let next = NSMenuItem(title: "Switch to next account   ⌘ Page Down", action: #selector(toggle), keyEquivalent: "")
        next.target = self
        menu.addItem(next)
        for p in profiles {
            let it = NSMenuItem(title: "Switch to \(p.label)", action: #selector(toProfile(_:)), keyEquivalent: "")
            it.target = self
            it.representedObject = p.key
            // The coloured logo goes inside the title: menu item `image`s were not drawn on this macOS.
            let icon = NSTextAttachment()
            icon.image = logoIcon(color(p.key), dimmed: false)
            icon.bounds = CGRect(x: 0, y: -3, width: 15, height: 15)
            let title = NSMutableAttributedString(attachment: icon)
            title.append(NSAttributedString(string: "  Switch to \(p.label)", attributes: [.font: NSFont.menuFont(ofSize: 0)]))
            it.attributedTitle = title
            menu.addItem(it)
        }
        menu.addItem(.separator())
        let add = NSMenuItem(title: "Add account…", action: #selector(addAccount), keyEquivalent: "")
        add.target = self
        menu.addItem(add)
        menu.addItem(NSMenuItem(title: "Quit Claude Switcher", action: #selector(NSApplication.terminate(_:)), keyEquivalent: ""))
    }

    /// Opens a Claude window with a new data folder for the first login. The new account's session folder
    /// is picked up by `claude-switch setup`, which the timer runs until it appears.
    @objc func addAccount() {
        let out = run(["add"])
        let al = NSAlert()
        al.messageText = "Log in to the new account"
        al.informativeText = out
        al.runModal()
        rebuildMenu()
    }

    func refresh() {
        DispatchQueue.global().async {
            let s = run(["status", "--short"])
            let label = run(["status"])
            // Nothing was running and the default account just opened (Dock icon, login item, reboot):
            // reopen the account used last instead. `restore` is a no-op when that is already the case.
            if !self.busy && self.previous == "none" && s == self.profiles.first?.key {
                DispatchQueue.main.async { self.switchTo(["restore"]) }
            }
            self.previous = s
            DispatchQueue.main.async {
                let known = self.profiles.contains { $0.key == s }
                self.item.button?.image = logoIcon(self.color(known ? s : (self.profiles.first?.key ?? "a")), dimmed: !known)
                self.item.button?.imagePosition = .imageLeading
                self.item.button?.title = self.busy ? " …" : known ? " " + s.uppercased() : ""
                self.item.button?.toolTip = "Claude Switcher — " + label
                self.stateLine.title = "Now: " + label
            }
        }
    }

    func switchTo(_ args: [String]) {
        if busy { return }
        busy = true
        refresh()
        DispatchQueue.global().async {
            let out = run(args)
            DispatchQueue.main.async {
                self.busy = false
                self.rebuildMenu()
                self.refresh()
                if out.contains("More than one") || out.contains("did not quit") || out.contains("not set up") {
                    let al = NSAlert()
                    al.messageText = "Could not switch"
                    al.informativeText = out
                    al.runModal()
                }
            }
        }
    }

    @objc func toggle() { switchTo([]) }
    @objc func toProfile(_ sender: NSMenuItem) { if let k = sender.representedObject as? String { switchTo([k]) } }

    func registerHotKey() {
        var ref: EventHotKeyRef?
        let id = EventHotKeyID(signature: OSType(0x434C5357), id: 1)  // 'CLSW'
        RegisterEventHotKey(UInt32(kVK_PageDown), UInt32(cmdKey), id, GetApplicationEventTarget(), 0, &ref)
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, ctx in
            Unmanaged<App>.fromOpaque(ctx!).takeUnretainedValue().toggle()
            return noErr
        }, 1, &spec, Unmanaged.passUnretained(self).toOpaque(), nil)
    }
}

let app = NSApplication.shared
let delegate = App()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
