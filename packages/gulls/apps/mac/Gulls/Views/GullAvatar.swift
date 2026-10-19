import SwiftUI

/// The deterministic visual identity shared by the web and native clients.
///
/// The hash intentionally iterates UTF-16 code units to match JavaScript's
/// String.charCodeAt implementation. Do not replace this with `String.hash`:
/// Swift's hash is process-seeded and is not stable across launches.
struct GullIdentity: Equatable, Hashable {
    enum WingName: String, CaseIterable {
        case classic
        case glide
        case loop
        case dip
    }

    let handle: String
    let hash: UInt32
    let wingName: WingName
    let tintHue: Double

    init(handle: String) {
        self.handle = handle
        self.hash = Self.javascriptHash(handle)
        self.wingName = WingName.allCases[Int(hash % UInt32(WingName.allCases.count))]
        self.tintHue = Self.tintHues[Int(hash % UInt32(Self.tintHues.count))]
    }

    static func javascriptHash(_ handle: String) -> UInt32 {
        handle.utf16.reduce(UInt32(0)) { hash, codeUnit in
            hash &* 31 &+ UInt32(codeUnit)
        }
    }

    // Matches packages/seagulls/packages/ui/src/gulls.tsx.
    private static let tintHues: [Double] = [245, 155, 75, 335, 25, 195]
}

/// A compact native Gull mark. The wing shape and tint are derived from the
/// complete handle, so display names and list order can change safely.
struct GullAvatar: View {
    let handle: String
    var size: CGFloat = 30

    private var identity: GullIdentity { GullIdentity(handle: handle) }

    var body: some View {
        Circle()
            .fill(identity.tint)
            .overlay {
                GullWing(name: identity.wingName)
                    .stroke(.white, style: StrokeStyle(
                        lineWidth: max(1.5, size * 0.085),
                        lineCap: .round,
                        lineJoin: .round
                    ))
                    .frame(width: size * 0.68, height: size * 0.30)
            }
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

/// Backwards-compatible name used by the existing Mac views.
struct WingAvatar: View {
    let identity: String
    var size: CGFloat = 30

    var body: some View {
        GullAvatar(handle: identity, size: size)
    }
}

extension GullIdentity {
    fileprivate var tint: Color {
        // sRGB conversions of oklch(0.52 0.11 hue), in the same hue order as
        // packages/seagulls/packages/ui/src/gulls.tsx. Values outside sRGB
        // are clipped by the conversion, as they are by CSS rendering.
        switch tintHue {
        case 245: return Color(red: 0.148716, green: 0.431477, blue: 0.641651)
        case 155: return Color(red: 0.148670, green: 0.482603, blue: 0.298000)
        case 75: return Color(red: 0.553894, green: 0.368621, blue: 0.000000)
        case 335: return Color(red: 0.560396, green: 0.307815, blue: 0.509298)
        case 25: return Color(red: 0.621770, green: 0.300449, blue: 0.281711)
        default: return Color(red: 0.000000, green: 0.484641, blue: 0.488008)
        }
    }
}

struct GullWing: Shape {
    let name: GullIdentity.WingName

    func path(in rect: CGRect) -> Path {
        var source = Path()

        switch name {
        case .classic:
            source.move(to: point(1, 12))
            source.addQuadCurve(to: point(16, 11), control: point(8, 2))
            source.addQuadCurve(to: point(31, 12), control: point(24, 2))
        case .glide:
            source.move(to: point(1, 11))
            source.addQuadCurve(to: point(16, 9), control: point(9, 1))
            source.addQuadCurve(to: point(31, 8), control: point(23, 4))
        case .loop:
            source.move(to: point(1, 11))
            source.addQuadCurve(to: point(14.5, 9), control: point(9, 3))
            source.addArc(
                center: point(16, 10.8734993995),
                radius: 2.4,
                startAngle: .radians(Self.loopStartAngle),
                endAngle: .radians(Self.loopStartAngle - Self.loopSweep),
                // CoreGraphics interprets a decreasing numeric angle as the
                // clockwise direction in its path coordinate system. Using
                // false here normalizes the SVG's large negative sweep to a
                // short upper arc.
                clockwise: true
            )
            source.addQuadCurve(to: point(31, 11), control: point(23, 3))
        case .dip:
            source.move(to: point(1, 12))
            source.addQuadCurve(to: point(15, 10), control: point(8, 2))
            source.addLine(to: point(16, 11))
            source.addLine(to: point(17, 10))
            source.addQuadCurve(to: point(31, 12), control: point(24, 2))
        }

        return source.applying(CGAffineTransform(
            a: rect.width / 32,
            b: 0,
            c: 0,
            d: rect.height / 14,
            tx: rect.minX,
            ty: rect.minY
        ))
    }

    private func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
        CGPoint(x: x, y: y)
    }

    private static let loopStartAngle = atan2(-1.8734993995, -1.5)
    private static let loopSweep = 4.9328523847
}
