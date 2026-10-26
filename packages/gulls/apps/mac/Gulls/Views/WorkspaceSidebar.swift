import SwiftUI

/// Mail-style workspace navigation.
///
/// The sidebar owns no selection state. The parent supplies the selected
/// destination and handles navigation. In compact mode it becomes a small
/// icon rail while keeping all three destinations available.
struct WorkspaceSidebar: View {
    let compact: Bool
    let overviewSelected: Bool
    let messagesSelected: Bool
    let gullsSelected: Bool
    let attentionCount: Int
    var scopeName: String? = nil
    var accountName: String = "Your account"
    let onOverview: () -> Void
    let onMessages: () -> Void
    let onGulls: () -> Void

    @Environment(\.openSettings) private var openSettings

    var body: some View {
        VStack(spacing: 0) {
            navigation
            Spacer(minLength: 0)
            accountFooter
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var navigation: some View {
        VStack(spacing: 4) {
            navigationButton(
                title: "Overview",
                systemImage: "square.grid.2x2",
                selected: overviewSelected,
                badge: 0,
                action: onOverview
            )
            navigationButton(
                title: "Messages",
                systemImage: "bubble.left.and.bubble.right",
                selected: messagesSelected,
                badge: attentionCount,
                action: onMessages
            )
            navigationButton(
                title: "Gulls",
                selected: gullsSelected,
                badge: 0,
                action: onGulls
            )
        }
        .padding(.horizontal, compact ? 8 : 10)
        .padding(.top, compact ? 10 : 8)
        .padding(.bottom, compact ? 8 : 4)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func navigationButton(
        title: String,
        systemImage: String? = nil,
        selected: Bool,
        badge: Int,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 9) {
                if compact {
                    ZStack(alignment: .topTrailing) {
                        if let systemImage {
                            Image(systemName: systemImage)
                        } else {
                            GullWing(name: .classic)
                                .stroke(
                                    selected ? Color.primary : Color.secondary,
                                    style: StrokeStyle(lineWidth: 1.7, lineCap: .round, lineJoin: .round)
                                )
                                .frame(width: 20, height: 13)
                        }
                        if badge > 0 {
                            Circle()
                                .fill(GullsStyle.accent)
                                .frame(width: 7, height: 7)
                                .overlay(Circle().stroke(GullsStyle.canvas, lineWidth: 1.5))
                                .offset(x: 3, y: -3)
                        }
                    }
                    .frame(width: 24, height: 24)
                } else if let systemImage {
                    Image(systemName: systemImage)
                        .frame(width: 18)
                } else {
                    GullWing(name: .classic)
                        .stroke(
                            selected ? Color.primary : Color.secondary,
                            style: StrokeStyle(lineWidth: 1.7, lineCap: .round, lineJoin: .round)
                        )
                        .frame(width: 20, height: 13)
                        .frame(width: 18)
                }

                if !compact {
                    Text(title)
                        .font(.subheadline.weight(selected ? .medium : .regular))
                    Spacer(minLength: 4)
                    if badge > 0 {
                        Text(attentionCountLabel(badge))
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
            }
            .foregroundStyle(selected ? Color.primary : Color.secondary)
            .padding(.horizontal, compact ? 0 : 10)
            .padding(.vertical, compact ? 10 : 7)
            .frame(maxWidth: .infinity, alignment: compact ? .center : .leading)
            .background {
                if selected {
                    Capsule().fill(GullsStyle.field)
                }
            }
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .help(title == "Messages" ? "Messages · \(scopeName ?? "All Gulls")" : title)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityLabel(badge > 0 ? "\(title), \(attentionCountLabel(badge))" : title)
        .accessibilityValue(title == "Messages" ? scopeName ?? "All Gulls" : "")
    }

    private var accountFooter: some View {
        Group {
            if compact {
                Button {
                    openSettings()
                } label: {
                    Image(systemName: "gearshape")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .help("Settings (⌘,)")
                .accessibilityLabel("Settings")
            } else {
                HStack(spacing: 10) {
                    Image(systemName: "person.crop.circle")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                    Text(accountName)
                        .font(.subheadline.weight(.medium))
                        .lineLimit(1)
                    Spacer(minLength: 4)
                    Button {
                        openSettings()
                    } label: {
                        Label("Settings", systemImage: "gearshape")
                            .labelStyle(.iconOnly)
                    }
                    .buttonStyle(.borderless)
                    .help("Settings (⌘,)")
                }
                .padding(.vertical, 4)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .accessibilityElement(children: .contain)
        .padding(.horizontal, compact ? 8 : 10)
        .padding(.bottom, compact ? 8 : 10)
    }

    private func attentionCountLabel(_ count: Int) -> String {
        count == 1 ? "1 needs you" : "\(count) need you"
    }
}
