import AppKit
import SwiftUI

enum GullsStyle {
    static let accent = Color(nsColor: NSColor(name: nil) { appearance in
        if appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua {
            return NSColor(srgbRed: 0.62, green: 0.42, blue: 1, alpha: 1)
        }
        return NSColor(srgbRed: 0.49, green: 0.23, blue: 0.93, alpha: 1)
    })
    static let canvas = Color(nsColor: .textBackgroundColor)
    static let field = Color.primary.opacity(0.045)
}

private struct GullsGlassSurface: ViewModifier {
    let cornerRadius: CGFloat
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    @ViewBuilder
    func body(content: Content) -> some View {
        if reduceTransparency {
            content.background(
                Color(nsColor: .controlBackgroundColor),
                in: RoundedRectangle(cornerRadius: cornerRadius)
            )
        } else if #available(macOS 26.0, *) {
            content.glassEffect(.regular, in: .rect(cornerRadius: cornerRadius))
        } else {
            content.background(.regularMaterial, in: RoundedRectangle(cornerRadius: cornerRadius))
        }
    }
}

extension View {
    func gullsGlass(cornerRadius: CGFloat = 16) -> some View {
        modifier(GullsGlassSurface(cornerRadius: cornerRadius))
    }
}

struct WingAvatar: View {
    let identity: String
    var size: CGFloat = 30

    var body: some View {
        Circle()
            .fill(tint)
            .overlay {
                WingMark()
                    .stroke(.white, style: StrokeStyle(lineWidth: size * 0.055, lineCap: .round, lineJoin: .round))
                    .frame(width: size * 0.64, height: size * 0.28)
            }
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }

    private var tint: Color {
        let colors: [Color] = [GullsStyle.accent, .teal, .orange, .indigo, .brown, .pink]
        let hash = identity.utf8.reduce(UInt32(0)) { ($0 &* 31) &+ UInt32($1) }
        return colors[Int(hash % UInt32(colors.count))]
    }
}

private struct WingMark: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: 1, y: 12))
        path.addQuadCurve(to: CGPoint(x: 16, y: 11), control: CGPoint(x: 8, y: 2))
        path.addQuadCurve(to: CGPoint(x: 31, y: 12), control: CGPoint(x: 24, y: 2))
        return path.applying(
            CGAffineTransform(scaleX: rect.width / 32, y: rect.height / 14)
                .concatenating(CGAffineTransform(translationX: rect.minX, y: rect.minY))
        )
    }
}
