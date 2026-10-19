import AppKit
import SwiftUI

struct LocalControlView: View {
    @Bindable var control: LocalControlStore
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var reviewRequest: LocalActionRequest?
    @State private var showingAllRecentResults = false

    private let recentResultsLimit = 3

    init(control: LocalControlStore) {
        _control = Bindable(wrappedValue: control)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            header
            accessSection
            foldersSection
            pendingSection
            recentResultsSection
            if let error = control.error, !error.isEmpty {
                errorView(error)
            }
        }
        .padding(.vertical, 12)
        .onAppear { control.refresh() }
        .sheet(item: $reviewRequest) { request in
            LocalActionReviewView(control: control, request: request) {
                reviewRequest = nil
            }
        }
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Local control")
                    .font(.title2.weight(.semibold))
                Text("Allow \(control.config.displayName.isEmpty ? control.config.agentHandle : control.config.displayName) to request actions on this Mac.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 12)
            Button {
                control.refresh()
            } label: {
                Label("Refresh", systemImage: "arrow.clockwise")
                    .labelStyle(.iconOnly)
            }
            .buttonStyle(.borderless)
            .help("Refresh local action requests")
        }
    }

    private var accessSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Toggle("Enable local control", isOn: $control.enabled)
                .font(.headline)
            Text(control.enabled
                 ? "Requests stay paused until you approve each exact action."
                 : "Disabled by default. Requests are read and queued, but cannot run.")
                .font(.callout)
                .foregroundStyle(.secondary)
            Text("Commands run with your Mac user permissions. File actions are limited to the folders selected below.")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
    }

    private var foldersSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text("Allowed folders")
                    .font(.headline)
                Spacer(minLength: 8)
                Button("Add folder") {
                    chooseFolder()
                }
                .buttonStyle(.borderless)
                .foregroundStyle(GullsStyle.accent)
            }
            if control.allowedFolders.isEmpty {
                Text("No folders selected. File reads and writes will remain unavailable.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(control.allowedFolders, id: \.self) { folder in
                    HStack(spacing: 8) {
                        Image(systemName: "folder")
                            .foregroundStyle(.secondary)
                        Text(folder)
                            .font(.callout)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer(minLength: 8)
                        Button {
                            control.removeFolder(folder)
                        } label: {
                            Label("Remove folder", systemImage: "xmark")
                                .labelStyle(.iconOnly)
                        }
                        .buttonStyle(.borderless)
                        .foregroundStyle(.secondary)
                        .help("Remove allowed folder")
                    }
                }
            }
        }
    }

    private var pendingSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text("Needs approval")
                    .font(.headline)
                Text(control.pendingRequests.count == 1
                     ? "1 request"
                     : "\(control.pendingRequests.count) requests")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
                if control.isRunning {
                    ProgressView()
                        .controlSize(.small)
                    Button("Stop") { control.stop() }
                        .buttonStyle(.borderless)
                        .foregroundStyle(.red)
                }
            }
            if control.pendingRequests.isEmpty {
                Text("No local actions are waiting for approval.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(control.pendingRequests) { request in
                    LocalActionRequestRow(request: request, enabled: control.enabled) {
                        reviewRequest = request
                    }
                }
            }
        }
    }

    private var recentResultsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text("Recent results")
                    .font(.headline)
                if !control.recentResults.isEmpty {
                    Text("\(control.recentResults.count)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            if control.recentResults.isEmpty {
                Text("No completed local actions yet.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            } else {
                let results = showingAllRecentResults
                    ? control.recentResults
                    : Array(control.recentResults.prefix(recentResultsLimit))
                ForEach(results) { result in
                    LocalActionResultRow(result: result)
                }
                if control.recentResults.count > recentResultsLimit {
                    Button(showingAllRecentResults ? "Show less" : "Show all \(control.recentResults.count) results") {
                        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.18)) {
                            showingAllRecentResults.toggle()
                        }
                    }
                    .buttonStyle(.borderless)
                    .font(.caption.weight(.medium))
                }
            }
        }
    }

    private func errorView(_ message: String) -> some View {
        Label {
            Text(message)
                .textSelection(.enabled)
        } icon: {
            Image(systemName: "exclamationmark.triangle.fill")
        }
        .font(.callout)
        .foregroundStyle(.red)
    }

    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Allow Folder"
        if panel.runModal() == .OK, let url = panel.url {
            control.addFolder(url)
        }
    }
}

struct LocalActionReviewView: View {
    let control: LocalControlStore
    let request: LocalActionRequest
    let onClose: () -> Void

    @State private var isShowingOriginal = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Review local action")
                        .font(.title2.weight(.semibold))
                    Text("Approve this exact request from \(request.gullHandle).")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 12)
                doneButton
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    detailSection("Action") {
                        detailRow("Kind", kindLabel)
                        if let executable = request.executable {
                            detailRow("Executable", executable)
                        }
                        if let arguments = request.arguments, !arguments.isEmpty {
                            ForEach(Array(arguments.enumerated()), id: \.offset) { index, argument in
                                detailRow("Argument \(index + 1)", argument)
                            }
                        }
                        if let directory = request.workingDirectory {
                            detailRow("Working folder", directory)
                        }
                        if let path = request.path {
                            detailRow("File", path)
                        }
                        detailRow("Requested", formattedDate(request.createdAt))
                    }

                    if request.kind == .command {
                        Text("Commands run with your Mac user permissions in the selected working folder; this folder is not sandboxed by the app.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    if request.kind == .writeFile, let content = request.content {
                        detailSection("Write preview") {
                            Text(content.isEmpty ? "(empty content — this clears the file)" : content)
                                .font(.system(.callout, design: .monospaced))
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(10)
                                .background(GullsStyle.field, in: RoundedRectangle(cornerRadius: 10))
                            if request.reviewedOriginalContent != nil {
                                DisclosureGroup("Compare with existing content", isExpanded: $isShowingOriginal) {
                                    Text(request.reviewedOriginalContent ?? "(empty file)")
                                        .font(.system(.callout, design: .monospaced))
                                        .textSelection(.enabled)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .padding(.top, 8)
                                }
                            } else {
                                Text("No existing text content was captured for comparison.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }

                    if request.kind == .readFile {
                        Text("The file content will be disclosed after approval in the result.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }

                    if let result = control.recentResults.first(where: { $0.requestID == request.requestID }) {
                        LocalActionResultRow(result: result)
                    }
                    if let error = control.error, !error.isEmpty {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .font(.callout)
                            .foregroundStyle(.red)
                            .textSelection(.enabled)
                    }
                }
            }

            HStack(spacing: 10) {
                Button("Reject") {
                    control.reject(request)
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.red)
                .disabled(!isPending || hasResult || control.isRunning)
                if control.isRunning {
                    Button("Stop") { control.stop() }
                        .buttonStyle(.borderless)
                        .foregroundStyle(.red)
                }
                Spacer(minLength: 8)
                Button(control.isRunning ? "Running…" : actionButtonTitle) {
                    Task { await control.approve(request) }
                }
                .buttonStyle(.borderedProminent)
                .tint(GullsStyle.accent)
                .disabled(!control.enabled || control.isRunning || hasResult || !isPending)
            }
        }
        .padding(24)
        .frame(minWidth: 560, idealWidth: 640, minHeight: 420, idealHeight: 560)
        .background(GullsStyle.canvas)
        .interactiveDismissDisabled(control.isRunning)
    }

    private var isPending: Bool {
        control.pendingRequests.contains { $0.requestID == request.requestID }
    }

    private var hasResult: Bool {
        control.recentResults.contains { $0.requestID == request.requestID }
    }

    @ViewBuilder
    private var doneButton: some View {
        if control.isRunning {
            Button("Done") { onClose() }
                .buttonStyle(.borderless)
                .disabled(true)
        } else {
            Button("Done") { onClose() }
                .buttonStyle(.borderless)
                .keyboardShortcut(.cancelAction)
        }
    }

    private var kindLabel: String {
        switch request.kind {
        case .command: return "Run command"
        case .readFile: return "Read file"
        case .writeFile: return "Write file"
        }
    }

    private var actionButtonTitle: String {
        switch request.kind {
        case .command: return "Approve & run"
        case .readFile: return "Approve & read"
        case .writeFile: return "Approve & write"
        }
    }

    private func detailSection<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Text(title)
                .font(.headline)
            content()
        }
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.system(.callout, design: .monospaced))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func formattedDate(_ raw: String) -> String {
        guard let date = GullsDates.parse(raw) else { return raw }
        return date.formatted(date: .abbreviated, time: .standard)
    }
}

private struct LocalActionRequestRow: View {
    let request: LocalActionRequest
    let enabled: Bool
    let onReview: () -> Void

    var body: some View {
        Button(action: onReview) {
            HStack(alignment: .top, spacing: 10) {
                GullAvatar(handle: request.gullHandle, size: 28)
                VStack(alignment: .leading, spacing: 4) {
                    Text(requestTitle)
                        .font(.subheadline.weight(.medium))
                    Text(requestSummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                Spacer(minLength: 8)
                Text(enabled ? "Needs review" : "Disabled")
                    .font(.caption)
                    .foregroundStyle(enabled ? GullsStyle.accent : .secondary)
                Image(systemName: "chevron.right")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.tertiary)
            }
            .foregroundStyle(Color.primary)
            .padding(.vertical, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(requestTitle), \(requestSummary)")
        .accessibilityHint("Review this local action")
    }

    private var requestTitle: String {
        switch request.kind {
        case .command: return "Run command"
        case .readFile: return "Read file"
        case .writeFile: return "Write file"
        }
    }

    private var requestSummary: String {
        switch request.kind {
        case .command:
            let executable = request.executable ?? "(missing executable)"
            let args = request.arguments ?? []
            return ([executable] + args).joined(separator: " ")
        case .readFile, .writeFile:
            return request.path ?? "(missing path)"
        }
    }
}

private struct LocalActionResultRow: View {
    let result: LocalActionResult
    @State private var expanded = false

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            VStack(alignment: .leading, spacing: 8) {
                if let error = result.error { outputBlock("Error", error) }
                if let content = result.content { outputBlock("Content", content) }
                if let stdout = result.stdout, !stdout.isEmpty { outputBlock("Standard output", stdout) }
                if let stderr = result.stderr, !stderr.isEmpty { outputBlock("Standard error", stderr) }
            }
            .padding(.top, 8)
        } label: {
            HStack(spacing: 8) {
                Circle()
                    .fill(resultColor)
                    .frame(width: 7, height: 7)
                Text(result.status.rawValue.capitalized)
                    .font(.subheadline.weight(.medium))
                Text(formattedDate(result.completedAt))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
                if let exitCode = result.exitCode {
                    Text("Exit \(exitCode)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .tint(.primary)
    }

    private var resultColor: Color {
        switch result.status {
        case .succeeded: return .green
        case .failed: return .red
        case .rejected, .cancelled: return .secondary
        }
    }

    private func outputBlock(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.system(.caption, design: .monospaced))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(8)
                .background(GullsStyle.field, in: RoundedRectangle(cornerRadius: 8))
        }
    }

    private func formattedDate(_ raw: String) -> String {
        guard let date = GullsDates.parse(raw) else { return raw }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

struct LocalActionsDashboardSection: View {
    let controls: [LocalControlStore]
    let onReview: (LocalControlStore, LocalActionRequest) -> Void
    var compact: Bool = false

    private struct PendingLocalAction: Identifiable {
        let id: String
        let control: LocalControlStore
        let request: LocalActionRequest
    }

    private var pending: [PendingLocalAction] {
        controls.flatMap { control in
            control.pendingRequests.map {
                PendingLocalAction(
                    id: "\(control.config.profileID):\($0.requestID)",
                    control: control,
                    request: $0
                )
            }
        }
    }

    var body: some View {
        if !pending.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Local actions")
                        .font(.headline.weight(.semibold))
                    Text(pending.count == 1 ? "1 needs you" : "\(pending.count) need you")
                        .font(.caption)
                        .foregroundStyle(GullsStyle.accent)
                    Spacer(minLength: 0)
                }
                ForEach(pending) { item in
                    Button {
                        onReview(item.control, item.request)
                    } label: {
                        HStack(spacing: 10) {
                            GullAvatar(handle: item.request.gullHandle, size: compact ? 26 : 28)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(item.request.gullHandle)
                                    .font(.subheadline.weight(.medium))
                                    .lineLimit(1)
                                Text(requestKind(item.request.kind))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                            .frame(minWidth: 0, maxWidth: .infinity, alignment: .leading)
                            if !compact {
                                Text("Review")
                                    .font(.caption.weight(.medium))
                                    .foregroundStyle(GullsStyle.accent)
                                    .fixedSize()
                            }
                            Image(systemName: "chevron.right")
                                .font(.caption2.weight(.semibold))
                                .foregroundStyle(GullsStyle.accent)
                        }
                        .foregroundStyle(Color.primary)
                        .padding(.vertical, 8)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(item.request.gullHandle), \(requestKind(item.request.kind)), Review")
                }
            }
            .padding(.bottom, 2)
        }
    }

    private func requestKind(_ kind: LocalActionKind) -> String {
        switch kind {
        case .command: return "Command request"
        case .readFile: return "File read request"
        case .writeFile: return "File write request"
        }
    }
}
