#!/usr/bin/env swift

import AppKit
import Foundation

private struct IconSlot {
    let filename: String
    let pixels: Int
}

private let slots = [
    IconSlot(filename: "AppIcon-16.png", pixels: 16),
    IconSlot(filename: "AppIcon-16@2x.png", pixels: 32),
    IconSlot(filename: "AppIcon-32.png", pixels: 32),
    IconSlot(filename: "AppIcon-32@2x.png", pixels: 64),
    IconSlot(filename: "AppIcon-128.png", pixels: 128),
    IconSlot(filename: "AppIcon-128@2x.png", pixels: 256),
    IconSlot(filename: "AppIcon-256.png", pixels: 256),
    IconSlot(filename: "AppIcon-256@2x.png", pixels: 512),
    IconSlot(filename: "AppIcon-512.png", pixels: 512),
    IconSlot(filename: "AppIcon-512@2x.png", pixels: 1024)
]

private func color(_ red: Int, _ green: Int, _ blue: Int, alpha: CGFloat = 1) -> NSColor {
    NSColor(
        calibratedRed: CGFloat(red) / 255,
        green: CGFloat(green) / 255,
        blue: CGFloat(blue) / 255,
        alpha: alpha
    )
}

private func drawLine(
    from start: NSPoint,
    to end: NSPoint,
    width: CGFloat,
    color: NSColor
) {
    let path = NSBezierPath()
    path.move(to: start)
    path.line(to: end)
    path.lineWidth = width
    path.lineCapStyle = .round
    color.setStroke()
    path.stroke()
}

private func fillCircle(center: NSPoint, radius: CGFloat, color: NSColor) {
    color.setFill()
    NSBezierPath(
        ovalIn: NSRect(
            x: center.x - radius,
            y: center.y - radius,
            width: radius * 2,
            height: radius * 2
        )
    ).fill()
}

private func drawKnowledgeNodes() {
    let lineColor = color(153, 246, 228, alpha: 0.34)
    let nodeColor = color(204, 251, 241, alpha: 0.76)
    let points = [
        NSPoint(x: 142, y: 670),
        NSPoint(x: 176, y: 782),
        NSPoint(x: 276, y: 868),
        NSPoint(x: 824, y: 730),
        NSPoint(x: 866, y: 835),
        NSPoint(x: 758, y: 886)
    ]

    drawLine(from: points[0], to: points[1], width: 10, color: lineColor)
    drawLine(from: points[1], to: points[2], width: 10, color: lineColor)
    drawLine(from: points[3], to: points[4], width: 10, color: lineColor)
    drawLine(from: points[4], to: points[5], width: 10, color: lineColor)
    drawLine(from: points[3], to: points[5], width: 10, color: lineColor)

    for (index, point) in points.enumerated() {
        fillCircle(center: point, radius: index.isMultiple(of: 2) ? 18 : 13, color: nodeColor)
    }
}

private func drawDocument() {
    let document = NSBezierPath()
    document.move(to: NSPoint(x: 218, y: 182))
    document.line(to: NSPoint(x: 218, y: 830))
    document.curve(
        to: NSPoint(x: 260, y: 872),
        controlPoint1: NSPoint(x: 218, y: 853),
        controlPoint2: NSPoint(x: 237, y: 872)
    )
    document.line(to: NSPoint(x: 570, y: 872))
    document.line(to: NSPoint(x: 726, y: 716))
    document.line(to: NSPoint(x: 726, y: 224))
    document.curve(
        to: NSPoint(x: 684, y: 182),
        controlPoint1: NSPoint(x: 726, y: 201),
        controlPoint2: NSPoint(x: 707, y: 182)
    )
    document.close()

    NSGraphicsContext.saveGraphicsState()
    let shadow = NSShadow()
    shadow.shadowColor = color(4, 15, 30, alpha: 0.38)
    shadow.shadowBlurRadius = 42
    shadow.shadowOffset = NSSize(width: 0, height: -22)
    shadow.set()
    color(248, 250, 252).setFill()
    document.fill()
    NSGraphicsContext.restoreGraphicsState()

    let paperGradient = NSGradient(colors: [color(255, 255, 255), color(226, 244, 248)])!
    paperGradient.draw(in: document, angle: -65)

    let fold = NSBezierPath()
    fold.move(to: NSPoint(x: 570, y: 872))
    fold.line(to: NSPoint(x: 570, y: 750))
    fold.curve(
        to: NSPoint(x: 606, y: 716),
        controlPoint1: NSPoint(x: 570, y: 731),
        controlPoint2: NSPoint(x: 587, y: 716)
    )
    fold.line(to: NSPoint(x: 726, y: 716))
    fold.close()
    NSGradient(colors: [color(186, 230, 253), color(94, 234, 212)])!
        .draw(in: fold, angle: -45)

    let ink = color(20, 64, 86)
    let mutedInk = color(70, 116, 134, alpha: 0.66)
    let accent = color(13, 148, 136)

    let title = NSBezierPath(roundedRect: NSRect(x: 292, y: 742, width: 218, height: 36), xRadius: 18, yRadius: 18)
    accent.setFill()
    title.fill()

    let rows: [(CGFloat, CGFloat)] = [(630, 290), (530, 326), (430, 255)]
    for (index, row) in rows.enumerated() {
        let y = row.0
        let badge = NSBezierPath(roundedRect: NSRect(x: 286, y: y - 18, width: 38, height: 38), xRadius: 12, yRadius: 12)
        (index == 0 ? accent : color(14, 116, 144, alpha: 0.18)).setFill()
        badge.fill()
        drawLine(from: NSPoint(x: 354, y: y + 8), to: NSPoint(x: 354 + row.1, y: y + 8), width: 20, color: ink)
        drawLine(from: NSPoint(x: 354, y: y - 25), to: NSPoint(x: 354 + row.1 * 0.72, y: y - 25), width: 14, color: mutedInk)
    }

    fillCircle(center: NSPoint(x: 324, y: 294), radius: 47, color: color(34, 197, 94))
    let check = NSBezierPath()
    check.move(to: NSPoint(x: 300, y: 294))
    check.line(to: NSPoint(x: 318, y: 274))
    check.line(to: NSPoint(x: 352, y: 316))
    check.lineWidth = 17
    check.lineCapStyle = .round
    check.lineJoinStyle = .round
    NSColor.white.setStroke()
    check.stroke()
    drawLine(from: NSPoint(x: 392, y: 306), to: NSPoint(x: 544, y: 306), width: 18, color: ink)
    drawLine(from: NSPoint(x: 392, y: 270), to: NSPoint(x: 500, y: 270), width: 13, color: mutedInk)
}

private func drawMagnifier() {
    let center = NSPoint(x: 662, y: 378)
    let radius: CGFloat = 142

    NSGraphicsContext.saveGraphicsState()
    let shadow = NSShadow()
    shadow.shadowColor = color(3, 20, 35, alpha: 0.5)
    shadow.shadowBlurRadius = 32
    shadow.shadowOffset = NSSize(width: 0, height: -14)
    shadow.set()
    fillCircle(center: center, radius: radius + 17, color: color(8, 47, 73))
    NSGraphicsContext.restoreGraphicsState()

    fillCircle(center: center, radius: radius - 8, color: color(207, 250, 254, alpha: 0.28))

    let ring = NSBezierPath(ovalIn: NSRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2))
    ring.lineWidth = 38
    color(94, 234, 212).setStroke()
    ring.stroke()

    drawLine(
        from: NSPoint(x: 762, y: 278),
        to: NSPoint(x: 878, y: 162),
        width: 70,
        color: color(8, 47, 73)
    )
    drawLine(
        from: NSPoint(x: 762, y: 278),
        to: NSPoint(x: 878, y: 162),
        width: 42,
        color: color(56, 189, 248)
    )

    fillCircle(center: NSPoint(x: 620, y: 425), radius: 18, color: color(255, 255, 255, alpha: 0.72))
    drawLine(
        from: NSPoint(x: 649, y: 425),
        to: NSPoint(x: 705, y: 425),
        width: 14,
        color: color(255, 255, 255, alpha: 0.42)
    )
}

private func renderIcon(pixels: Int, destination: URL) throws {
    guard let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: pixels,
        pixelsHigh: pixels,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ), let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
        throw NSError(domain: "IconGenerator", code: 1, userInfo: [NSLocalizedDescriptionKey: "Could not create bitmap context"])
    }

    bitmap.size = NSSize(width: pixels, height: pixels)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    context.shouldAntialias = true
    context.cgContext.scaleBy(x: CGFloat(pixels) / 1024, y: CGFloat(pixels) / 1024)

    NSColor.clear.setFill()
    NSRect(x: 0, y: 0, width: 1024, height: 1024).fill()

    let tile = NSBezierPath(roundedRect: NSRect(x: 66, y: 66, width: 892, height: 892), xRadius: 212, yRadius: 212)
    NSGraphicsContext.saveGraphicsState()
    let tileShadow = NSShadow()
    tileShadow.shadowColor = color(2, 12, 27, alpha: 0.48)
    tileShadow.shadowBlurRadius = 48
    tileShadow.shadowOffset = NSSize(width: 0, height: -24)
    tileShadow.set()
    color(10, 38, 61).setFill()
    tile.fill()
    NSGraphicsContext.restoreGraphicsState()

    NSGradient(colors: [color(16, 42, 67), color(8, 105, 112), color(14, 116, 144)])!
        .draw(in: tile, angle: -42)

    NSGraphicsContext.saveGraphicsState()
    tile.addClip()
    fillCircle(center: NSPoint(x: 820, y: 820), radius: 245, color: color(56, 189, 248, alpha: 0.08))
    fillCircle(center: NSPoint(x: 160, y: 170), radius: 210, color: color(94, 234, 212, alpha: 0.07))
    NSGraphicsContext.restoreGraphicsState()

    drawKnowledgeNodes()
    drawDocument()
    drawMagnifier()

    let border = NSBezierPath(roundedRect: NSRect(x: 70, y: 70, width: 884, height: 884), xRadius: 208, yRadius: 208)
    border.lineWidth = 7
    color(255, 255, 255, alpha: 0.15).setStroke()
    border.stroke()

    NSGraphicsContext.restoreGraphicsState()

    guard let data = bitmap.representation(using: .png, properties: [.compressionFactor: 1]) else {
        throw NSError(domain: "IconGenerator", code: 2, userInfo: [NSLocalizedDescriptionKey: "Could not encode PNG"])
    }
    try data.write(to: destination, options: .atomic)
}

let projectRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath, isDirectory: true)
let outputDirectory = projectRoot
    .appendingPathComponent("ISOStandardsKB/Resources/Assets.xcassets/AppIcon.appiconset", isDirectory: true)
try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)

for slot in slots {
    let destination = outputDirectory.appendingPathComponent(slot.filename)
    try renderIcon(pixels: slot.pixels, destination: destination)
    print("Generated \(slot.filename) (\(slot.pixels)x\(slot.pixels))")
}
