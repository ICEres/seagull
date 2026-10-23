import SwiftUI

struct WorkspaceOwnedGull: Identifiable {
    let handle: String
    let displayName: String
    let status: String
    let profileID: String?
    let bio: String?
    let capabilities: [String]

    var id: String { handle }
}

/// One directory, with ownership kept explicit and secondary metadata in detail.
struct WorkspaceGullsView: View {
    let ownedGulls: [WorkspaceOwnedGull]
    let savedGulls: [SavedGull]
    let selectedHandle: String?
    let compact: Bool
    let canSave: Bool
    let onSelect: (String) -> Void
    let onAdd: () -> Void
    let onSettings: () -> Void

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.gullsWindowControlInset) private var windowControlInset
    @State private var searchText = ""
    @State private var searchScrollOffset: CGFloat = 0
    @State private var isSearchExpanded = false
    @State private var searchFocusRequest = 0

    private let searchHeaderTopPadding: CGFloat = 12
    private let searchHeaderBottomPadding: CGFloat = 4
    private let searchPinDistance: CGFloat = 44
    private var searchCollapseInset: CGFloat { searchHeaderTopPadding + 28 + 8 }

    private var query: String {
        searchText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var isSearchPinned: Bool {
        searchDistanceFromTitle <= searchCollapseInset - searchHeaderTopPadding
    }

    private var searchDistanceFromTitle: CGFloat {
        if #available(macOS 15.0, *) { return max(searchPinDistance - searchScrollOffset, 0) }
        return 0
    }

    private var searchControlsTopInset: CGFloat {
        let scrolledInset = searchHeaderTopPadding + searchDistanceFromTitle
        return isSearchPinned && isSearchExpanded
            ? max(scrolledInset, searchCollapseInset)
            : scrolledInset
    }

    private func matches(_ name: String, handle: String) -> Bool {
        query.isEmpty || name.localizedCaseInsensitiveContains(query) || handle.localizedCaseInsensitiveContains(query)
    }

    private var filteredOwned: [WorkspaceOwnedGull] {
        ownedGulls.filter { matches($0.displayName, handle: $0.handle) }
    }

    private var filteredSaved: [SavedGull] {
        savedGulls.filter { gull in
            matches(gull.displayName, handle: gull.handle)
                || gull.labels.contains { $0.localizedCaseInsensitiveContains(query) }
        }
    }

    var body: some View {
        Group {
            if #available(macOS 26.0, *), !reduceTransparency {
                content
                    .gullsSafeAreaBar(edge: .top, spacing: 0, style: .minimal) { header }
                    .gullsScrollEdges()
            } else {
                content
                    .safeAreaInset(edge: .top, spacing: 0) { header.background(GullsStyle.canvas) }
                    .gullsScrollEdges()
            }
        }
        .background {
            Button("Search Gulls") { searchFocusRequest += 1 }
                .keyboardShortcut("f", modifiers: .command)
                .hidden()
        }
        .overlay(alignment: .topLeading) { stickySearchControls }
    }

    @ViewBuilder
    private var content: some View {
        if #available(macOS 15.0, *) {
            scrollView
                .onScrollGeometryChange(for: CGFloat.self) { geometry in
                    min(max(geometry.contentOffset.y + geometry.contentInsets.top, 0), searchPinDistance)
                } action: { _, offset in
                    searchScrollOffset = offset
                }
        } else {
            scrollView
        }
    }

    private var scrollView: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 4) {
                Color.clear
                    .frame(height: 28)
                    .padding(.bottom, compact ? 10 : 14)
                    .accessibilityHidden(true)

                if !query.isEmpty && filteredOwned.isEmpty && filteredSaved.isEmpty {
                    Text("No matching Gulls")
                        .foregroundStyle(.secondary)
                        .padding(14)
                } else {
                    sectionTitle("My Gulls")
                    if filteredOwned.isEmpty && query.isEmpty {
                        emptySection("Connect a Gull or sign in to see your Gulls.")
                        Button("Open Settings", action: onSettings)
                            .buttonStyle(.borderless)
                            .padding(.horizontal, 10)
                    }
                    ForEach(filteredOwned) { gull in
                        row(handle: gull.handle, name: gull.displayName, subtitle: gull.status)
                    }

                    sectionTitle("Other Gulls")
                        .padding(.top, 20)
                    if filteredSaved.isEmpty && query.isEmpty {
                        emptySection(canSave
                            ? "Save a Gull by its address or from a conversation."
                            : "Sign in to save other Gulls on this Mac.")
                    }
                    ForEach(filteredSaved) { gull in
                        row(handle: gull.handle, name: gull.displayName, subtitle: gull.handle)
                    }
                }
            }
            .padding(.top, 12)
            .padding(.horizontal, compact ? 10 : 14)
            .padding(.bottom, 14)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .frame(minWidth: 260, maxWidth: .infinity, maxHeight: .infinity)
        .gullsHiddenScrollbars()
    }

    private var header: some View {
        HStack(spacing: 8) {
            GullsPageTitle("Gulls")
                .font(.title2.weight(.semibold))
                .lineLimit(1)
            Spacer(minLength: 0)
        }
        .frame(height: 28)
        .padding(.horizontal, compact ? 14 : 28)
        .padding(.top, searchHeaderTopPadding)
        .padding(.bottom, searchHeaderBottomPadding)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var stickySearchControls: some View {
        GeometryReader { geometry in
            let inset: CGFloat = compact ? 14 : 28
            let rowWidth = max(min(geometry.size.width - inset * 2, compact ? .infinity : 860), 0)
            let expandedWidth = max(min(rowWidth - 38, 260), 56)

            HStack(spacing: 10) {
                GullsStickySearchField(
                    prompt: "Search Gulls", text: $searchText,
                    isPinned: isSearchPinned,
                    focusRequest: searchFocusRequest,
                    expandedWidth: expandedWidth,
                    isExpanded: $isSearchExpanded,
                    accessibilityLabel: "Search Gulls",
                    help: "Search names, addresses, or private labels (⌘F)"
                )

                Button(action: onAdd) {
                    Image(systemName: "plus")
                        .frame(width: 28, height: 28)
                }
                .buttonStyle(.borderless)
                .disabled(!canSave)
                .gullsGlass(cornerRadius: 14)
                .accessibilityLabel("Save a Gull")
                .help(canSave ? "Save a Gull by address" : "Sign in to save other Gulls")
            }
            .frame(width: rowWidth, height: 28)
            .offset(x: inset, y: windowControlInset + searchControlsTopInset)
            .animation(reduceMotion ? nil : .spring(response: 0.4, dampingFraction: 0.8), value: isSearchExpanded)
        }
    }

    private func sectionTitle(_ title: String) -> some View {
        Text(title)
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 10)
            .padding(.bottom, 5)
            .accessibilityAddTraits(.isHeader)
    }

    private func emptySection(_ text: String) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
    }

    private func row(handle: String, name: String, subtitle: String) -> some View {
        let selected = selectedHandle == handle
        return Button { onSelect(handle) } label: {
            HStack(spacing: 10) {
                GullAvatar(handle: handle, size: compact ? 28 : 32)
                VStack(alignment: .leading, spacing: 4) {
                    Text(verbatim: name)
                        .font(.subheadline.weight(selected ? .semibold : .medium))
                        .lineLimit(1)
                    Text(verbatim: subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .foregroundStyle(Color.primary)
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(RoundedRectangle(cornerRadius: 10))
        }
        .buttonStyle(GullsListRowButtonStyle(isSelected: selected))
        .accessibilityAddTraits(selected ? .isSelected : [])
        .help(handle)
    }
}
