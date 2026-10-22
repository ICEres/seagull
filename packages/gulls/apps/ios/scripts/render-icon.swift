import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

// Render the same classic Gull wing path used by the Mac and web clients.
let destination = CommandLine.arguments.dropFirst().first ?? "Gulls/Assets.xcassets/AppIcon.appiconset/AppIcon.png"
let context = CGContext(
    data: nil, width: 1024, height: 1024, bitsPerComponent: 8, bytesPerRow: 0,
    space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
)!
context.setFillColor(CGColor(red: 0.49, green: 0.23, blue: 0.93, alpha: 1))
context.fill(CGRect(x: 0, y: 0, width: 1024, height: 1024))
context.translateBy(x: 192, y: 662)
context.scaleBy(x: 20, y: -20)
context.setStrokeColor(CGColor(gray: 1, alpha: 1))
context.setLineWidth(2.4)
context.setLineCap(.round)
context.setLineJoin(.round)
context.move(to: CGPoint(x: 1, y: 12))
context.addQuadCurve(to: CGPoint(x: 16, y: 11), control: CGPoint(x: 8, y: 2))
context.addQuadCurve(to: CGPoint(x: 31, y: 12), control: CGPoint(x: 24, y: 2))
context.strokePath()
let image = context.makeImage()!
let url = URL(fileURLWithPath: destination)
let file = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(file, image, nil)
guard CGImageDestinationFinalize(file) else { fatalError("Could not write the app icon.") }

let tab = CGContext(
    data: nil, width: 96, height: 64, bitsPerComponent: 8, bytesPerRow: 0,
    space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
)!
tab.translateBy(x: 0, y: 56)
tab.scaleBy(x: 3, y: -3)
tab.setStrokeColor(CGColor(gray: 0, alpha: 1))
tab.setLineWidth(2.3)
tab.setLineCap(.round)
tab.move(to: CGPoint(x: 1, y: 12))
tab.addQuadCurve(to: CGPoint(x: 16, y: 11), control: CGPoint(x: 8, y: 2))
tab.addQuadCurve(to: CGPoint(x: 31, y: 12), control: CGPoint(x: 24, y: 2))
tab.strokePath()
let tabURL = url.deletingLastPathComponent().deletingLastPathComponent()
    .appendingPathComponent("GullTab.imageset/GullTab.png")
let tabFile = CGImageDestinationCreateWithURL(tabURL as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(tabFile, tab.makeImage()!, [kCGImagePropertyDPIWidth: 216, kCGImagePropertyDPIHeight: 216] as CFDictionary)
guard CGImageDestinationFinalize(tabFile) else { fatalError("Could not write the tab icon.") }
