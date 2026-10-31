import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

// Keep the classic Gull wing identical to the iOS and web brand mark.
// Run from packages/gulls/apps/mac to regenerate the complete Mac icon set.
let destination = URL(fileURLWithPath: CommandLine.arguments.dropFirst().first
    ?? "Gulls/Assets.xcassets/AppIcon.appiconset", isDirectory: true)
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
var images: [[String: String]] = []

for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let context = CGContext(
            data: nil, width: pixels, height: pixels, bitsPerComponent: 8, bytesPerRow: 0,
            space: colorSpace, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )!
        context.scaleBy(x: CGFloat(pixels) / 1024, y: CGFloat(pixels) / 1024)

        let tile = CGPath(roundedRect: CGRect(x: 100, y: 100, width: 824, height: 824),
                          cornerWidth: 184, cornerHeight: 184, transform: nil)
        context.saveGState()
        context.setShadow(offset: CGSize(width: 0, height: -8), blur: 18,
                          color: CGColor(gray: 0, alpha: 0.20))
        context.setFillColor(CGColor(red: 0.49, green: 0.23, blue: 0.93, alpha: 1))
        context.addPath(tile)
        context.fillPath()
        context.restoreGState()

        context.saveGState()
        context.addPath(tile)
        context.clip()
        let gradient = CGGradient(colorsSpace: colorSpace, colors: [
            CGColor(red: 0.39, green: 0.16, blue: 0.82, alpha: 1),
            CGColor(red: 0.57, green: 0.34, blue: 0.97, alpha: 1)
        ] as CFArray, locations: [0, 1])!
        context.drawLinearGradient(gradient, start: CGPoint(x: 750, y: 100),
                                   end: CGPoint(x: 300, y: 924),
                                   options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        context.restoreGState()

        // Rendering each size from the path keeps Finder's 16pt mark crisp.
        context.translateBy(x: 238, y: 646)
        context.scaleBy(x: 17.125, y: -17.125)
        context.setStrokeColor(CGColor(gray: 1, alpha: 1))
        context.setLineWidth(size <= 32 ? 2.8 : 2.4)
        context.setLineCap(.round)
        context.setLineJoin(.round)
        context.move(to: CGPoint(x: 1, y: 12))
        context.addQuadCurve(to: CGPoint(x: 16, y: 11), control: CGPoint(x: 8, y: 2))
        context.addQuadCurve(to: CGPoint(x: 31, y: 12), control: CGPoint(x: 24, y: 2))
        context.strokePath()

        let filename = "icon_\(size)x\(size)\(scale == 2 ? "@2x" : "").png"
        let file = CGImageDestinationCreateWithURL(
            destination.appendingPathComponent(filename) as CFURL,
            UTType.png.identifier as CFString, 1, nil
        )!
        CGImageDestinationAddImage(file, context.makeImage()!, nil)
        guard CGImageDestinationFinalize(file) else { fatalError("Could not write \(filename)") }
        images.append(["idiom": "mac", "size": "\(size)x\(size)",
                       "scale": "\(scale)x", "filename": filename])
    }
}

let contents: [String: Any] = ["images": images, "info": ["author": "xcode", "version": 1]]
try JSONSerialization.data(withJSONObject: contents, options: [.prettyPrinted, .sortedKeys])
    .write(to: destination.appendingPathComponent("Contents.json"))
