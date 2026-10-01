// Generate reproducible app icons / 生成可复现的应用图标。
import AppKit
let destination = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
func image(_ size: Int, name: String) throws {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                                 bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                 isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    let scale = CGFloat(size) / 1024
    let transform = NSAffineTransform(); transform.scale(by: scale); transform.concat()
    let canvas = NSBezierPath(rect: NSRect(x: 0, y: 0, width: 1024, height: 1024))
    NSGradient(starting: NSColor(srgbRed: 0.08, green: 0.20, blue: 0.16, alpha: 1),
               ending: NSColor(srgbRed: 0.06, green: 0.48, blue: 0.35, alpha: 1))!.draw(in: canvas, angle: 45)
    NSColor(srgbRed: 0.49, green: 0.82, blue: 0.67, alpha: 0.2).setFill()
    NSBezierPath(ovalIn: NSRect(x: 570, y: 595, width: 410, height: 410)).fill()
    NSColor(srgbRed: 0.62, green: 0.94, blue: 0.77, alpha: 0.35).setFill()
    NSBezierPath(roundedRect: NSRect(x: 130, y: 445, width: 415, height: 320), xRadius: 80, yRadius: 80).fill()
    NSColor(srgbRed: 0.90, green: 0.99, blue: 0.94, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: 250, y: 250, width: 630, height: 450), xRadius: 100, yRadius: 100).fill()
    let tail = NSBezierPath(); tail.move(to: NSPoint(x: 400, y: 300)); tail.line(to: NSPoint(x: 310, y: 160)); tail.line(to: NSPoint(x: 570, y: 270)); tail.close(); tail.fill()
    NSColor(srgbRed: 0.06, green: 0.40, blue: 0.28, alpha: 1).setFill()
    for x in [400, 570, 740] { NSBezierPath(ovalIn: NSRect(x: x - 40, y: 450, width: 80, height: 80)).fill() }
    NSGraphicsContext.restoreGraphicsState()
    try bitmap.representation(using: .png, properties: [:])!.write(to: destination.appendingPathComponent(name))
}
try image(1024, name: "AppIcon.png")
for size in [16, 32, 64, 128, 256, 512] { try image(size, name: "mac-\(size).png") }
