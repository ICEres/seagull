import SwiftUI

enum GullsAppearance: String, CaseIterable, Identifiable {
    case system, light, dark

    var id: String { rawValue }
    var title: String { rawValue.capitalized }
    var colorScheme: ColorScheme? {
        switch self {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }
}

enum GullsTheme {
    static let accent = adaptive(
        light: UIColor(red: 0.49, green: 0.23, blue: 0.93, alpha: 1),
        dark: UIColor(red: 0.67, green: 0.48, blue: 1, alpha: 1)
    )
    static let background = adaptive(
        light: UIColor(red: 0.972, green: 0.965, blue: 0.989, alpha: 1),
        dark: UIColor(red: 0.035, green: 0.030, blue: 0.047, alpha: 1)
    )
    static let surface = adaptive(
        light: UIColor(white: 1, alpha: 0.20),
        dark: UIColor(red: 0.095, green: 0.082, blue: 0.12, alpha: 0.20)
    )
    static let incoming = Color.primary.opacity(0.055)
    static let outgoing = accent.opacity(0.12)

    private static func adaptive(light: UIColor, dark: UIColor) -> Color {
        Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? dark : light })
    }
}

struct GullsPageTitle: View {
    let title: String

    init(_ title: String) { self.title = title }

    var body: some View {
        Text("\(title)\(Text(".").foregroundStyle(GullsTheme.accent))")
            .accessibilityLabel(title)
            .accessibilityAddTraits(.isHeader)
    }
}

struct GullsNavigationTitle: ToolbarContent {
    let title: String

    init(_ title: String) { self.title = title }

    var body: some ToolbarContent {
        if #available(iOS 26, *) {
            ToolbarItem(placement: .largeTitle) {
                GullsPageTitle(title)
                    .font(.largeTitle.bold())
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

extension View {
    func gullsSurface() -> some View {
        padding(18)
            .background(GullsTheme.surface, in: .rect(cornerRadius: 22))
    }

    @ViewBuilder
    func gullsGlass(cornerRadius: CGFloat = 24, interactive: Bool = false) -> some View {
        modifier(GullsGlassModifier(cornerRadius: cornerRadius, interactive: interactive))
    }

    func gullsSheet() -> some View {
        modifier(GullsSheetModifier())
    }
}

private struct GullsGlassModifier: ViewModifier {
    let cornerRadius: CGFloat
    let interactive: Bool
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorScheme) private var colorScheme

    @ViewBuilder
    func body(content: Content) -> some View {
        if reduceTransparency {
            content.background(GullsTheme.background, in: .rect(cornerRadius: cornerRadius))
        } else if #available(iOS 26, *) {
            content.glassEffect(.clear.interactive(interactive), in: .rect(cornerRadius: cornerRadius))
                .overlay {
                    RoundedRectangle(cornerRadius: cornerRadius)
                        .strokeBorder(.white.opacity(colorScheme == .dark ? 0.22 : 0.65), lineWidth: 0.75)
                        .allowsHitTesting(false)
                }
                .shadow(color: .black.opacity(0.10), radius: 16, y: 6)
        } else {
            content.background(.ultraThinMaterial, in: .rect(cornerRadius: cornerRadius))
        }
    }
}

private struct GullsSheetModifier: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @AppStorage("gulls.appearance") private var appearance = GullsAppearance.system.rawValue

    @ViewBuilder
    func body(content: Content) -> some View {
        Group {
            if reduceTransparency {
                content.presentationBackground(GullsTheme.background)
            } else if #available(iOS 26, *) {
                content
            } else {
                content.presentationBackground(.ultraThinMaterial)
            }
        }
        .preferredColorScheme(GullsAppearance(rawValue: appearance)?.colorScheme)
    }
}
