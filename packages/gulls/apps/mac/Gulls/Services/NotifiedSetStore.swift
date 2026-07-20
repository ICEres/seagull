import Foundation

// App-private persistence of which delivery IDs have already produced a
// banner (~/Library/Application Support/Gulls/notified-deliveries.json).
// Deliberately separate from the CLI's seen-deliveries.json — see InboxStore
// for why the app never mutates the CLI's watch state.
//
// The set is read once at init; writes snapshot the set onto a serial queue
// so the main actor never blocks on disk.
final class NotifiedSetStore {

    static var defaultURL: URL {
        FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Gulls/notified-deliveries.json")
    }

    // False on a fresh install (or wiped app support). The first inbox
    // snapshot is then seeded silently instead of bannering every
    // pre-existing delivery at once.
    let existedOnDisk: Bool

    private(set) var ids: Set<String>
    private let url: URL
    private let writeQueue = DispatchQueue(label: "ai.gulls.mac.notified-set", qos: .utility)

    init(url: URL = NotifiedSetStore.defaultURL) {
        self.url = url
        existedOnDisk = FileManager.default.fileExists(atPath: url.path)
        if existedOnDisk,
           let data = try? Data(contentsOf: url),
           let stored = try? JSONDecoder().decode([String].self, from: data) {
            ids = Set(stored)
        } else {
            ids = []
        }
    }

    func contains(_ id: String) -> Bool {
        ids.contains(id)
    }

    // Marks IDs as notified. Persists only when something actually changed.
    func insert(_ newIDs: some Sequence<String>) {
        let before = ids.count
        ids.formUnion(newIDs)
        if ids.count != before {
            persist()
        }
    }

    // First-run seeding: mark the whole current snapshot as already handled.
    // Persists even when the snapshot is empty so the file exists and the
    // next launch doesn't seed again.
    func seed(_ snapshot: some Sequence<String>) {
        ids.formUnion(snapshot)
        persist()
    }

    private func persist() {
        let snapshot = ids.sorted()
        let target = url
        writeQueue.async {
            guard let data = try? JSONEncoder().encode(snapshot) else { return }
            try? FileManager.default.createDirectory(
                at: target.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try? data.write(to: target, options: .atomic)
        }
    }
}
