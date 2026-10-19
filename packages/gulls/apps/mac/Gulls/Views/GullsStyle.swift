import AppKit
import QuartzCore
import SwiftUI

enum GullsStyle {
    static let accent = Color(nsColor: NSColor(name: nil) { appearance in
        if appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua {
            return NSColor(srgbRed: 0.62, green: 0.42, blue: 1, alpha: 1)
        }
        return NSColor(srgbRed: 0.49, green: 0.23, blue: 0.93, alpha: 1)
    })
    // Keep the window and sidebar surfaces quiet so the composer remains the
    // only prominent floating surface in the main layout.
    static let canvas = Color(nsColor: .windowBackgroundColor)
    static let field = Color.primary.opacity(0.055)
    static let messageIncoming = Color(nsColor: .controlBackgroundColor).opacity(0.45)
    static let messageOutgoing = accent.opacity(0.16)
}

struct GullsPageTitle: View {
    let title: String

    init(_ title: String) {
        self.title = title
    }

    var body: some View {
        Text("\(title)\(Text(".").foregroundStyle(GullsStyle.accent))")
            .accessibilityLabel(title)
            .accessibilityAddTraits(.isHeader)
    }
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
            // The native scroll edge obscures background text; the glass
            // surface can stay clear without reducing foreground contrast.
            content.glassEffect(
                .clear,
                in: .rect(cornerRadius: cornerRadius)
            )
        } else {
            content.background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: cornerRadius))
        }
    }
}
extension View {
    func gullsWindowChrome() -> some View {
        background(GullsWindowChrome().allowsHitTesting(false))
    }

    func gullsGlass(cornerRadius: CGFloat = 16) -> some View {
        modifier(GullsGlassSurface(cornerRadius: cornerRadius))
    }

    func gullsHiddenScrollbars() -> some View {
        scrollIndicators(.visible)
            .background(GullsScrollbars().allowsHitTesting(false))
    }

    /// Let safe-area bars participate in the native progressive scroll effect.
    func gullsScrollEdges() -> some View {
        modifier(GullsScrollEdges())
    }
}
private struct GullsWindowChrome: NSViewRepresentable {
    func makeNSView(context: Context) -> Marker { Marker() }
    func updateNSView(_ view: Marker, context: Context) {}

    final class Marker: NSView {
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            window?.titlebarSeparatorStyle = .none
        }
    }
}
private struct GullsScrollEdges: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    @ViewBuilder
    func body(content: Content) -> some View {
        if #available(macOS 26.0, *) {
            if reduceTransparency {
                content.scrollEdgeEffectHidden(true, for: [.top, .bottom])
            } else {
                content.scrollEdgeEffectStyle(.soft, for: [.top, .bottom])
            }
        } else {
            content
        }
    }
}
// Keep native scrollers installed so AppKit can render scroll edge effects.
// Mask only their drawing, once, without changing their scroll-time state.
private struct GullsScrollbars: NSViewRepresentable {
    func makeNSView(context: Context) -> Marker { Marker() }
    func updateNSView(_ view: Marker, context: Context) {}

    final class Marker: NSView {
        private var windowObserver: NSObjectProtocol?

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            stopObservingWindow()
            guard let window else { return }
            windowObserver = NotificationCenter.default.addObserver(
                forName: NSWindow.didUpdateNotification, object: window, queue: .main
            ) { [weak self] _ in
                MainActor.assumeIsolated { self?.hideIndicators() }
            }
        }

        deinit {
            if let windowObserver { NotificationCenter.default.removeObserver(windowObserver) }
        }

        private func hideIndicators() {
            guard let content = window?.contentView else { return }
            let scrollers = Self.scrollViews(in: content).flatMap {
                [$0.verticalScroller, $0.horizontalScroller].compactMap { $0 }
            }
            guard !scrollers.isEmpty else { return }
            for scroller in scrollers {
                scroller.wantsLayer = true
                scroller.layer?.mask = CALayer()
            }
            stopObservingWindow()
        }

        private func stopObservingWindow() {
            if let windowObserver { NotificationCenter.default.removeObserver(windowObserver) }
            windowObserver = nil
        }

        private static func scrollViews(in view: NSView) -> [NSScrollView] {
            let current = (view as? NSScrollView).map { [$0] } ?? []
            return current + view.subviews.flatMap { scrollViews(in: $0) }
        }
    }
}
