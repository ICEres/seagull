import AppKit
import CoreImage
import QuartzCore
import SwiftUI

enum GullsAppearance: String, CaseIterable, Identifiable {
    case system
    case light
    case dark

    static let storageKey = "gulls.appearance"

    var id: String { rawValue }
    var title: String { rawValue.capitalized }

    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light: return .light
        case .dark: return .dark
        }
    }
}

enum GullsStyle {
    static let accent = Color(nsColor: NSColor(name: nil) { appearance in
        if appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua {
            return NSColor(srgbRed: 0.62, green: 0.42, blue: 1, alpha: 1)
        }
        return NSColor(srgbRed: 0.49, green: 0.23, blue: 0.93, alpha: 1)
    })
    // Opaque fallback for reduced transparency and scroll bars on older macOS.
    static let canvas = Color(nsColor: NSColor(name: nil) { appearance in
        if appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua {
            return NSColor(srgbRed: 0.030, green: 0.028, blue: 0.038, alpha: 1)
        }
        return NSColor(srgbRed: 0.972, green: 0.965, blue: 0.989, alpha: 1)
    })
    static let field = Color.primary.opacity(0.055)
    static let messageIncoming = Color(nsColor: .controlBackgroundColor).opacity(0.45)
    static let messageOutgoing = accent.opacity(0.16)
}

struct GullsAIIcon: View {
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        GullWing(name: .classic)
            .stroke(
                LinearGradient(colors: colors, startPoint: .topLeading, endPoint: .bottomTrailing),
                style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round)
            )
            .frame(width: 23, height: 15)
            .accessibilityHidden(true)
    }

    private var colors: [Color] {
        if !isEnabled { return [.secondary, .secondary] }
        if contrast == .increased { return [GullsStyle.accent, GullsStyle.accent] }
        return [Color(red: 0.25, green: 0.52, blue: 1), GullsStyle.accent,
                Color(red: 0.81, green: 0.38, blue: 0.85)]
    }
}

private struct GullsWindowBackground: ViewModifier {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    func body(content: Content) -> some View {
        content.background {
            if reduceTransparency {
                GullsStyle.canvas.ignoresSafeArea()
            } else {
                GullsWindowMaterial()
                    .overlay(GullsStyle.canvas.opacity(colorScheme == .dark ? 0.42 : 0.025))
                    .ignoresSafeArea()
            }
        }
    }
}

private struct GullsWindowMaterial: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .underWindowBackground
        view.blendingMode = .behindWindow
        view.state = .active
        return view
    }

    func updateNSView(_ view: NSVisualEffectView, context: Context) {}
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

struct GullsSearchField: View {
    let prompt: String
    @Binding var text: String
    let accessibilityLabel: String
    let help: String
    var handlesSearchShortcut = true
    var focusOnAppear = false
    @FocusState private var isFocused: Bool

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            TextField(prompt, text: $text)
                .textFieldStyle(.plain)
                .focused($isFocused)
                .accessibilityLabel(accessibilityLabel)
                .help(help)
                .onExitCommand {
                    if text.isEmpty { isFocused = false }
                    else { text = "" }
                }
            Button {
                text = ""
                isFocused = true
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(.secondary)
                    .frame(width: 22, height: 22)
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Clear search")
            .help("Clear search")
            .opacity(text.isEmpty ? 0 : 1)
            .disabled(text.isEmpty)
            .accessibilityHidden(text.isEmpty)
        }
        .font(.body)
        .padding(.leading, 11)
        .padding(.trailing, 4)
        .frame(height: 28)
        .background(GullsStyle.field, in: Capsule())
        .background {
            if handlesSearchShortcut {
                Button("Search") { isFocused = true }
                    .keyboardShortcut("f", modifiers: .command)
                    .hidden()
            }
        }
        .onAppear {
            if focusOnAppear { isFocused = true }
        }
    }
}

struct GullsStickySearchField: View {
    var prompt = "Search"
    @Binding var text: String
    let isPinned: Bool
    let focusRequest: Int
    let expandedWidth: CGFloat
    @Binding var isExpanded: Bool
    let accessibilityLabel: String
    let help: String
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @FocusState private var isFocused: Bool

    private var showsField: Bool { !isPinned || isExpanded }

    var body: some View {
        GeometryReader { geometry in
            let width = showsField ? (isPinned ? min(geometry.size.width, expandedWidth) : geometry.size.width) : 28
            HStack(spacing: 0) {
                Button(action: openSearch) {
                    Image(systemName: "magnifyingglass")
                        .frame(width: 28, height: 28)
                        .contentShape(Circle())
                }
                .buttonStyle(.plain)
                .foregroundStyle(text.isEmpty ? Color.secondary : GullsStyle.accent)
                .accessibilityLabel(accessibilityLabel)
                .help(help)

                if showsField {
                    TextField(prompt, text: $text)
                        .textFieldStyle(.plain)
                        .focused($isFocused)
                        .accessibilityLabel(accessibilityLabel)
                        .task {
                            if isPinned && isExpanded {
                                await Task.yield()
                                isFocused = true
                            }
                        }
                        .onExitCommand { closeSearch() }
                        .transition(.opacity)

                    Button(action: closeSearch) {
                        Image(systemName: isPinned ? "xmark" : "xmark.circle.fill")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .frame(width: 28, height: 28)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(isPinned ? "Collapse search" : "Clear search")
                    .help(isPinned ? "Collapse search (Esc)" : "Clear search")
                    .opacity(isPinned || !text.isEmpty ? 1 : 0)
                    .disabled(!isPinned && text.isEmpty)
                    .accessibilityHidden(!isPinned && text.isEmpty)
                    .transition(.opacity)
                }
            }
            .frame(width: max(width, 28), height: 28)
            .gullsGlass(cornerRadius: 14)
            .frame(maxWidth: .infinity, alignment: .trailing)
            .animation(reduceMotion ? nil : .spring(response: 0.4, dampingFraction: 0.8), value: isPinned)
            .animation(reduceMotion ? nil : .spring(response: 0.4, dampingFraction: 0.8), value: isExpanded)
        }
        .frame(height: 28)
        .onChange(of: focusRequest) { _, _ in openSearch() }
        .onChange(of: isPinned) { _, isPinned in
            isExpanded = false
            if isPinned { isFocused = false }
        }
    }

    private func openSearch() {
        if showsField { isFocused = true }
        else { isExpanded = true }
    }

    private func closeSearch() {
        if isPinned {
            isFocused = false
            isExpanded = false
        } else if text.isEmpty {
            isFocused = false
        } else {
            text = ""
            isFocused = true
        }
    }
}

private struct GullsHeaderControlsVisibility: ViewModifier {
    @Binding var isCondensed: Bool

    @ViewBuilder
    func body(content: Content) -> some View {
        if #available(macOS 15.0, *) {
            content.onScrollVisibilityChange(threshold: 0.9) { isVisible in
                isCondensed = !isVisible
            }
        } else {
            // Keep the compact actions available when visibility tracking
            // is unavailable; the full controls still scroll naturally.
            content.onAppear { isCondensed = true }
        }
    }
}

struct GullsListRowButtonStyle: ButtonStyle {
    var isSelected = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorSchemeContrast) private var contrast
    @State private var isHovered = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background {
                RoundedRectangle(cornerRadius: 10)
                    .fill(isSelected
                          ? GullsStyle.accent.opacity((contrast == .increased ? 0.24 : 0.14) + (configuration.isPressed ? 0.06 : 0))
                          : Color.primary.opacity(configuration.isPressed ? 0.10 : isHovered ? 0.055 : 0))
            }
            .onHover { isHovered = $0 }
            .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: isHovered)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: configuration.isPressed)
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
            content.glassEffect(
                .regular,
                in: .rect(cornerRadius: cornerRadius)
            )
        } else {
            content.background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: cornerRadius))
        }
    }
}

enum GullsSafeAreaBarStyle {
    case standard
    case minimal

    var fadeLength: CGFloat {
        switch self {
        case .standard: return 52
        case .minimal: return 16
        }
    }

    var topBlurRadius: CGFloat {
        switch self {
        case .standard: return 0.2
        case .minimal: return 0.1
        }
    }

    var topMinimumOpacity: CGFloat {
        switch self {
        case .standard: return 0.16
        case .minimal: return 0.24
        }
    }
}

@available(macOS 26.0, *)
private struct GullsSafeAreaBar<Bar: View>: ViewModifier {
    let edge: VerticalEdge
    let spacing: CGFloat?
    let style: GullsSafeAreaBarStyle
    let bar: Bar
    @Environment(\.gullsWindowControlInset) private var windowControlInset

    @ViewBuilder
    func body(content: Content) -> some View {
        if #available(macOS 27.0, *) {
            // Separate native hosts let the blur sample scrolling content
            // without the tinted, hard-edged SDK 26 scroll edge on macOS 27.
            GullsHostedSafeAreaBar(content: content, bar: insetBar, edge: edge, spacing: spacing, style: style)
        } else if style == .minimal {
            // Use the scoped host on SDK 26 for the minimal treatment so the
            // native soft edge does not add a second, stronger blur.
            GullsHostedSafeAreaBar(
                content: content.scrollEdgeEffectHidden(true, for: [.top, .bottom]),
                bar: insetBar, edge: edge, spacing: spacing, style: style
            )
        } else {
            content.safeAreaBar(edge: edge, spacing: spacing) { insetBar }
        }
    }

    private var insetBar: some View {
        bar.padding(.top, edge == .top ? windowControlInset : 0)
    }
}

private struct GullsWindowControlInsetKey: EnvironmentKey {
    static let defaultValue: CGFloat = 0
}

extension EnvironmentValues {
    var gullsWindowControlInset: CGFloat {
        get { self[GullsWindowControlInsetKey.self] }
        set { self[GullsWindowControlInsetKey.self] = newValue }
    }
}

private struct GullsBarContent<Content: View>: View {
    var content: Content
    let edge: VerticalEdge
    var spacing: CGFloat?
    var barHeight: CGFloat
    var style: GullsSafeAreaBarStyle
    var environment: EnvironmentValues

    var body: some View {
        content
            .environment(\.self, environment)
            .scrollClipDisabled()
            .safeAreaInset(edge: edge, spacing: spacing) {
                Color.clear.frame(height: barHeight)
            }
            .mask {
                GeometryReader { geometry in
                    let height = max(geometry.size.height, 1)
                    // Keep the content readable near the scroll edge. The
                    // transition is intentionally soft and mostly opacity
                    // based; a strong mask makes the edge read as a panel.
                    let transitionEnd = barHeight + (style == .minimal ? 0 : style.fadeLength)
                    let transitionLength = style.fadeLength + 20
                    let minimumOpacity = edge == .top ? style.topMinimumOpacity : 0.08
                    let fadeStart = min(max(transitionEnd - transitionLength, 0) / height, 1)
                    let fadeEnd = min(transitionEnd / height, 1)
                    let ramp = (0...16).map { index in
                        let t = Double(index) / 16
                        let eased = t * t * t * (t * (t * 6 - 15) + 10)
                        return Gradient.Stop(
                            color: .white.opacity(minimumOpacity + (1 - minimumOpacity) * eased),
                            location: fadeStart + (fadeEnd - fadeStart) * CGFloat(t)
                        )
                    }
                    LinearGradient(stops: [
                        .init(color: .white.opacity(minimumOpacity), location: 0)
                    ] + ramp + [
                        .init(color: .white, location: 1)
                    ], startPoint: edge == .top ? .top : .bottom,
                       endPoint: edge == .top ? .bottom : .top)
                }
            }
    }
}

private struct GullsHostedSafeAreaBar<Content: View, Bar: View>: NSViewRepresentable {
    let content: Content
    let bar: Bar
    let edge: VerticalEdge
    let spacing: CGFloat?
    let style: GullsSafeAreaBarStyle

    func makeNSView(context: Context) -> GullsBarHost<Content, Bar> {
        GullsBarHost(
            content: content, bar: bar, edge: edge, spacing: spacing, style: style,
            environment: context.environment
        )
    }

    func updateNSView(_ view: GullsBarHost<Content, Bar>, context: Context) {
        view.update(content: content, bar: bar, spacing: spacing, style: style, environment: context.environment)
    }
}

private final class GullsBarHost<Content: View, Bar: View>: NSView {
    private let contentHost: NSHostingView<GullsBarContent<Content>>
    private let barController: NSHostingController<GullsBarEnvironment<Bar>>
    private let blurView: GullsScrollEdgeBlur
    private let edge: VerticalEdge
    private var style: GullsSafeAreaBarStyle
    private var barHeight: CGFloat = 1

    init(content: Content, bar: Bar, edge: VerticalEdge, spacing: CGFloat?, style: GullsSafeAreaBarStyle, environment: EnvironmentValues) {
        self.edge = edge
        self.style = style
        contentHost = NSHostingView(rootView: GullsBarContent(
            content: content, edge: edge, spacing: spacing,
            barHeight: 1, style: style, environment: environment
        ))
        barController = NSHostingController(rootView: GullsBarEnvironment(content: bar, environment: environment))
        blurView = GullsScrollEdgeBlur(edge: edge, style: style)
        super.init(frame: .zero)
        contentHost.safeAreaRegions = []
        barController.safeAreaRegions = []
        addSubview(contentHost)
        addSubview(blurView)
        addSubview(barController.view)
    }

    required init?(coder: NSCoder) { nil }

    override func layout() {
        super.layout()
        let measured = barController.sizeThatFits(in: CGSize(width: max(bounds.width, 1), height: 1000)).height
        if measured > 1, abs(measured - barHeight) > 0.5 {
            barHeight = measured
            contentHost.rootView.barHeight = barHeight
            contentHost.needsLayout = true
        }
        contentHost.frame = bounds
        let height = min(barHeight, bounds.height)
        let fade = style.fadeLength
        if edge == .top {
            // Feather below the controls so the more visible part of the
            // scrolling content cannot overlap labels or the search field.
            blurView.frame = NSRect(x: 0, y: bounds.maxY - height - fade, width: bounds.width, height: min(fade * 2, height + fade))
            barController.view.frame = NSRect(x: 0, y: bounds.maxY - height, width: bounds.width, height: height)
        } else {
            blurView.frame = NSRect(x: 0, y: height, width: bounds.width, height: fade)
            barController.view.frame = NSRect(x: 0, y: 0, width: bounds.width, height: height)
        }
        blurView.needsLayout = true
    }

    func update(content: Content, bar: Bar, spacing: CGFloat?, style: GullsSafeAreaBarStyle, environment: EnvironmentValues) {
        var root = contentHost.rootView
        root.content = content
        root.spacing = spacing
        root.style = style
        root.environment = environment
        contentHost.rootView = root
        self.style = style
        blurView.update(style: style)
        barController.rootView = GullsBarEnvironment(content: bar, environment: environment)
        contentHost.needsLayout = true
        barController.view.needsLayout = true
        needsLayout = true
    }
}

private struct GullsBarEnvironment<Content: View>: View {
    let content: Content
    let environment: EnvironmentValues

    var body: some View {
        content.environment(\.self, environment)
    }
}

private final class GullsScrollEdgeBlur: NSView {
    // A longer, lighter transition prevents the backdrop filter from ending
    // on a visible horizontal seam while keeping the scrolled content crisp.
    private let edge: VerticalEdge
    private var style: GullsSafeAreaBarStyle
    private var filterFrame = CGRect.null

    init(edge: VerticalEdge, style: GullsSafeAreaBarStyle) {
        self.edge = edge
        self.style = style
        super.init(frame: .zero)
        wantsLayer = true
        layerUsesCoreImageFilters = true
        // Backdrop filters can extend beyond their mask image. Clip the
        // result to this edge band so the rest of the pane stays sharp.
        layer?.masksToBounds = true
    }

    required init?(coder: NSCoder) { nil }

    func update(style: GullsSafeAreaBarStyle) {
        guard self.style != style else { return }
        self.style = style
        filterFrame = .null
        needsLayout = true
    }

    override func layout() {
        super.layout()
        guard bounds.width > 0, bounds.height > 0, frame != filterFrame else { return }
        let zeroY = edge == .top ? 0 : bounds.height
        let fullY = edge == .top ? bounds.height : 0
        // AppKit supplies the backdrop in superview coordinates. Keep the
        // finite mask aligned with it, including when a top bar moves on resize.
        guard let mask = CIFilter(name: "CISmoothLinearGradient", parameters: [
            "inputPoint0": CIVector(x: 0, y: zeroY),
            "inputPoint1": CIVector(x: 0, y: fullY),
            "inputColor0": CIColor.black,
            "inputColor1": CIColor.white
        ])?.outputImage?.cropped(to: bounds).transformed(by: CGAffineTransform(
            translationX: frame.minX, y: frame.minY
        )), let blur = CIFilter(name: "CIMaskedVariableBlur", parameters: [
            // Keep the backdrop legible. The opacity mask supplies most of
            // the transition; this is only a subtle softening pass.
            kCIInputRadiusKey: edge == .top ? style.topBlurRadius : 0.35,
            "inputMask": mask
        ]) else { return }
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        backgroundFilters = [blur]
        CATransaction.commit()
        filterFrame = frame
    }

    override func viewDidChangeBackingProperties() {
        super.viewDidChangeBackingProperties()
        filterFrame = .null
        needsLayout = true
    }

    override func hitTest(_ point: NSPoint) -> NSView? { nil }
}

extension View {
    func gullsWindowBackground() -> some View {
        modifier(GullsWindowBackground())
    }

    @ViewBuilder
    func gullsWindowChrome(hidesTitleBar: Bool = false, resizable: Bool = false) -> some View {
        if hidesTitleBar {
            background(GullsWindowChrome(hidesTitleBar: true, resizable: resizable).allowsHitTesting(false))
        } else if #available(macOS 26.0, *) {
            background(GullsWindowChrome(resizable: resizable).allowsHitTesting(false))
                .toolbar(removing: .title)
        } else {
            background(GullsWindowChrome(resizable: resizable).allowsHitTesting(false))
        }
    }

    func gullsGlass(cornerRadius: CGFloat = 16) -> some View {
        modifier(GullsGlassSurface(cornerRadius: cornerRadius))
    }

    @available(macOS 26.0, *)
    func gullsSafeAreaBar<Bar: View>(
        edge: VerticalEdge,
        spacing: CGFloat? = nil,
        style: GullsSafeAreaBarStyle = .standard,
        @ViewBuilder content: () -> Bar
    ) -> some View {
        modifier(GullsSafeAreaBar(edge: edge, spacing: spacing, style: style, bar: content()))
    }

    func gullsHiddenScrollbars() -> some View {
        scrollIndicators(.visible)
            .background(GullsScrollbars().allowsHitTesting(false))
    }

    func gullsHeaderControlsVisibility(isCondensed: Binding<Bool>) -> some View {
        modifier(GullsHeaderControlsVisibility(isCondensed: isCondensed))
    }

    /// Match native or compatibility backdrops to the reserved safe-area bars.
    func gullsScrollEdges() -> some View {
        modifier(GullsScrollEdges())
    }
}
private struct GullsWindowChrome: NSViewRepresentable {
    var hidesTitleBar = false
    var resizable = false

    func makeNSView(context: Context) -> Marker {
        let view = Marker()
        view.hidesTitleBar = hidesTitleBar
        view.resizable = resizable
        return view
    }
    func updateNSView(_ view: Marker, context: Context) {}

    final class Marker: NSView {
        var hidesTitleBar = false
        var resizable = false

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            window?.titlebarSeparatorStyle = .none
            window?.titlebarAppearsTransparent = true
            window?.titleVisibility = .hidden
            window?.isOpaque = false
            window?.backgroundColor = .clear
            if resizable { window?.styleMask.insert(.resizable) }
            if hidesTitleBar {
                window?.styleMask.insert(.fullSizeContentView)
                window?.toolbar = nil
                window?.isMovableByWindowBackground = true
            }
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
            } else if #available(macOS 27.0, *) {
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
