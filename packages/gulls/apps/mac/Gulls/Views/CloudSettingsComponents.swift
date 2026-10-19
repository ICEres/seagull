import SwiftUI

struct CloudSettingsSection<Content: View>: View {
    let title: String
    let detail: String?
    @ViewBuilder let content: Content

    init(_ title: String, detail: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.detail = detail
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                if let detail {
                    Text(detail).font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            content
        }
    }
}

struct CloudSettingsRow<Content: View>: View {
    let title: String
    let detail: String?
    @ViewBuilder let content: Content

    init(_ title: String, detail: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.detail = detail
        self.content = content()
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.subheadline.weight(.medium))
                if let detail {
                    Text(detail).font(.caption).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(width: 150, alignment: .leading)
            Spacer(minLength: 12)
            content
        }
    }
}

struct CloudSettingsStatus: View {
    let message: String
    let isError: Bool

    var body: some View {
        Label(message, systemImage: isError ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
            .font(.caption)
            .foregroundStyle(isError ? .red : .green)
            .textSelection(.enabled)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

enum CloudSettingsDate {
    static func label(_ value: String?) -> String {
        guard let value else { return "Date unavailable" }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var date = formatter.date(from: value)
        if date == nil {
            formatter.formatOptions = [.withInternetDateTime]
            date = formatter.date(from: value)
        }
        guard let date else { return "Date unavailable" }
        if Calendar.current.isDateInToday(date) {
            return "Today, \(date.formatted(.dateTime.hour().minute()))"
        }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

struct CloudUsageProgressStyle: ProgressViewStyle {
    func makeBody(configuration: Configuration) -> some View {
        GeometryReader { geometry in
            Capsule()
                .fill(Color.primary.opacity(0.07))
                .overlay(alignment: .leading) {
                    Capsule()
                        .fill(GullsStyle.accent)
                        .frame(width: geometry.size.width * CGFloat(configuration.fractionCompleted ?? 0))
                }
        }
        .frame(height: 6)
    }
}

struct CloudAllowanceProgress: View {
    let title: String
    let available: Int
    let total: Int
    var usedLabel = "used"

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(title).font(.subheadline.weight(.medium))
                Spacer()
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text(available.formatted()).font(.title2.weight(.semibold)).monospacedDigit()
                    Text("credits left").font(.caption).foregroundStyle(.secondary)
                }
            }
            if total > 0 {
                ProgressView(value: Double(min(max(available, 0), total)), total: Double(total))
                    .progressViewStyle(CloudUsageProgressStyle())
                    .accessibilityLabel(title)
                    .accessibilityValue("\(available.formatted()) of \(total.formatted()) credits remaining")
                HStack {
                    Text("\(max(total - available, 0).formatted()) \(usedLabel)")
                    Spacer()
                    Text("\(total.formatted()) total added")
                }
                .font(.caption).monospacedDigit().foregroundStyle(.secondary)
            } else {
                Text(available > 0 ? "Total allowance is unavailable." : "No allowance yet.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

extension View {
    func cloudSettingsField() -> some View {
        self
            .textFieldStyle(.plain)
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .gullsGlass(cornerRadius: 11)
            .overlay {
                RoundedRectangle(cornerRadius: 11)
                    .strokeBorder(Color.primary.opacity(0.12), lineWidth: 0.75)
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
            }
    }
}

extension CloudRuntimeMode {
    var label: String {
        switch self {
        case .cloud: return "Cloud"
        case .local: return "Local"
        case .manual: return "Manual"
        }
    }
}

extension CloudAgentProfile {
    var statusLabel: String { status.isEmpty ? "Unknown" : status.capitalized }
}
