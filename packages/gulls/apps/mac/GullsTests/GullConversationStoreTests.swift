import XCTest
@testable import Gulls

@MainActor
final class GullConversationStoreTests: XCTestCase {
    private var tmp: URL!

    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("GullConversationStoreTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tmp)
    }

    private func defaults() -> UserDefaults {
        let suite = "GullConversationStoreTests.\(UUID().uuidString)"
        return UserDefaults(suiteName: suite)!
    }

    private func environment(profileID: String = "profile-1", revision: String = "revision-1") -> GullsCLI.Environment {
        var value = GullsCLI.Environment(
            apiURL: "https://hub.example.test",
            agentHandle: "@sender:gulls.ai",
            contextDir: tmp.appendingPathComponent("context")
        )
        value.profileID = profileID
        value.connectionRevision = revision
        return value
    }

    private func sender(profileID: String = "profile-1", revision: String = "revision-1") -> GullConversationSender {
        GullConversationSender(
            id: profileID,
            displayName: "Sender",
            handle: "@sender:gulls.ai",
            connectionRevision: revision,
            environment: environment(profileID: profileID, revision: revision)
        )
    }

    private func makeCLI(script: String) throws -> GullsCLI {
        let url = tmp.appendingPathComponent("gulls")
        try ("#!/bin/bash\n" + script).write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
        return GullsCLI(executableURL: url)
    }

    private func pagedCLI(total: Int) throws -> GullsCLI {
        let pages = (total + 99) / 100
        for page in 0..<pages {
            let upper = total - page * 100
            let lower = max(1, upper - 99)
            let messages = (lower...upper).map { index in
                ["message_id": "m-\(index)", "thread_id": "thread-1",
                 "content_inline": "message \(index)", "sender_handle": "@atlas:gulls.ai",
                 "created_at": ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: Double(index)))]
            }
            var object: [String: Any] = ["thread_id": "thread-1", "messages": messages]
            if page + 1 < pages { object["next_cursor"] = "page-\(page + 1)" }
            try JSONSerialization.data(withJSONObject: object).write(to: tmp.appendingPathComponent("page-\(page).json"))
        }
        return try makeCLI(script: """
        cursor=page-0
        while [ "$#" -gt 0 ]; do
            if [ "$1" = "--cursor" ]; then shift; cursor="$1"; fi
            shift
        done
        cat "\(tmp.path)/$cursor.json"
        """)
    }

    private func waitForFile(_ url: URL) async throws {
        let deadline = Date().addingTimeInterval(5)
        while !FileManager.default.fileExists(atPath: url.path) {
            guard Date() < deadline else { throw NSError(domain: "Fixture did not reach barrier", code: 1) }
            try await Task.sleep(for: .milliseconds(10))
        }
    }

    func testRapidFirstSendsEstablishOneThreadBeforeSendingSuccessors() async throws {
        let log = tmp.appendingPathComponent("posts.log")
        let release = tmp.appendingPathComponent("release")
        let cli = try makeCLI(script: """
        if [ "$1" = "--json" ]; then shift; fi
        if [ "$1" = "post" ]; then
            printf '%s\\n' "$*" >> "\(log.path)"
            while [ ! -f "\(release.path)" ]; do sleep 0.01; done
            thread="new-thread-$(wc -l < "\(log.path)" | tr -d ' ')"
            while [ "$#" -gt 0 ]; do
                if [ "$1" = "--thread-id" ]; then shift; thread="$1"; fi
                shift
            done
            printf '{"message_id":"message-%s","thread_id":"%s"}' "$(wc -l < "\(log.path)" | tr -d ' ')" "$thread"
            exit 0
        fi
        printf '{"thread_id":"new-thread-1","messages":[]}'
        """)
        let store = GullConversationStore(cli: cli, defaults: defaults(), cacheURL: tmp.appendingPathComponent("cache.json"))
        store.activate(scope: "account")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        let first = Task { try await store.send(conversation.id, content: "first", environment: self.environment()) }
        try await waitForFile(log)
        let enqueued = expectation(description: "second message saved immediately")
        let second = Task {
            try await store.send(conversation.id, content: "second", environment: self.environment()) { enqueued.fulfill() }
        }
        await fulfillment(of: [enqueued], timeout: 5)
        XCTAssertEqual(store.pendingMessages(for: conversation.id).count, 2)
        try Data().write(to: release)
        _ = try await first.value
        _ = try await second.value
        let posts = try String(contentsOf: log, encoding: .utf8).split(separator: "\n")
        XCTAssertEqual(posts.count, 2)
        XCTAssertFalse(posts[0].contains("--thread-id"))
        XCTAssertTrue(posts[1].contains("--thread-id new-thread-1"))
        XCTAssertEqual(store.conversations.first?.threadID, "new-thread-1")
    }

    func testHeadRefreshDoesNotRewindAnAdvancedHistoryCursor() async throws {
        let store = GullConversationStore(cli: try pagedCLI(total: 400), defaults: defaults(), cacheURL: tmp.appendingPathComponent("cache.json"))
        store.activate(scope: "account")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        _ = try await store.load(conversation.id, threadID: "thread-1", environment: environment())
        _ = try await store.loadMore(conversation.id, environment: environment())
        XCTAssertEqual(store.nextCursorByConversationID[conversation.id], "page-2")
        _ = try await store.load(conversation.id, threadID: "thread-1", environment: environment())
        XCTAssertEqual(store.nextCursorByConversationID[conversation.id], "page-2")
    }

    func testExplicitlyLoadedHistoryIsNotCappedAt500Messages() async throws {
        let store = GullConversationStore(cli: try pagedCLI(total: 700), defaults: defaults(), cacheURL: tmp.appendingPathComponent("cache.json"))
        store.activate(scope: "account")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        _ = try await store.load(conversation.id, threadID: "thread-1", environment: environment())
        for _ in 0..<6 { _ = try await store.loadMore(conversation.id, environment: environment()) }
        XCTAssertEqual(store.messages(for: conversation.id).count, 700)
        XCTAssertEqual(store.messages(for: conversation.id).first?.id, "m-1")
        XCTAssertFalse(store.hasMoreMessages(for: conversation.id))
    }

    func testWarmCacheTruncationRebuildsBeforeReportingHistoryEnd() async throws {
        let sharedDefaults = defaults()
        let cache = tmp.appendingPathComponent("cache.json")
        let cli = try pagedCLI(total: 700)
        let store = GullConversationStore(cli: cli, defaults: sharedDefaults, cacheURL: cache)
        store.activate(scope: "account")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        _ = try await store.load(conversation.id, threadID: "thread-1", environment: environment())
        for _ in 0..<6 { _ = try await store.loadMore(conversation.id, environment: environment()) }
        await store.flushCache()
        XCTAssertEqual(store.messages(for: conversation.id).count, 700)

        let restored = GullConversationStore(cli: cli, defaults: sharedDefaults, cacheURL: cache)
        restored.activate(scope: "account")
        await restored.waitForCacheHydration()
        XCTAssertEqual(restored.messages(for: conversation.id).count, 500)
        XCTAssertTrue(restored.hasMoreMessages(for: conversation.id))
        for _ in 0..<10 where restored.hasMoreMessages(for: conversation.id) {
            _ = try await restored.loadMore(conversation.id, environment: environment())
        }
        XCTAssertEqual(restored.messages(for: conversation.id).count, 700)
        XCTAssertEqual(restored.messages(for: conversation.id).first?.id, "m-1")
        XCTAssertFalse(restored.hasMoreMessages(for: conversation.id))
    }

    func testHeadCatchupResumesUntilOfflineGapIsFilled() async throws {
        let store = GullConversationStore(cli: try pagedCLI(total: 100), defaults: defaults(), cacheURL: tmp.appendingPathComponent("cache.json"))
        store.activate(scope: "account")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        _ = try await store.load(conversation.id, threadID: "thread-1", environment: environment())
        XCTAssertFalse(store.hasMoreMessages(for: conversation.id))
        _ = try pagedCLI(total: 350)
        _ = try await store.load(conversation.id, threadID: "thread-1", environment: environment())
        XCTAssertTrue(store.hasMoreMessages(for: conversation.id))
        _ = try await store.load(conversation.id, threadID: "thread-1", environment: environment())
        XCTAssertEqual(Set(store.messages(for: conversation.id).map(\.id)), Set((1...350).map { "m-\($0)" }))
        XCTAssertFalse(store.hasMoreMessages(for: conversation.id))
    }

    func testMissingThreadAcknowledgementBlocksQueuedSuccessors() async throws {
        let log = tmp.appendingPathComponent("posts.log")
        let cli = try makeCLI(script: """
        printf '%s\\n' "$*" >> "\(log.path)"
        printf '{"message_id":"accepted-without-thread"}'
        """)
        let store = GullConversationStore(cli: cli, defaults: defaults(), cacheURL: tmp.appendingPathComponent("cache.json"))
        store.activate(scope: "account")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        do {
            _ = try await store.send(conversation.id, content: "first", environment: environment())
            XCTFail("expected uncertain acknowledgement")
        } catch let error as GullConversationError { XCTAssertEqual(error, .invalidAcknowledgement) }
        _ = try await store.send(conversation.id, content: "second", environment: environment())
        await store.sendQueued(environment: environment())
        let items = store.pendingByConversationID[conversation.id] ?? []
        XCTAssertEqual(items.map(\.state), [.unconfirmed, .queued])
        XCTAssertEqual(try String(contentsOf: log, encoding: .utf8).split(separator: "\n").count, 1)
    }

    func testRetryAfterRestartKeepsOriginalNullThreadEvenAfterReconciliation() async throws {
        let sharedDefaults = defaults()
        let cache = tmp.appendingPathComponent("cache.json")
        let log = tmp.appendingPathComponent("posts.log")
        let cli = try makeCLI(script: """
        if [ "$1" = "--json" ]; then shift; fi
        if [ "$1" = "post" ]; then
            printf '%s\\n' "$*" >> "\(log.path)"
            count=$(wc -l < "\(log.path)" | tr -d ' ')
            if [ "$count" = "1" ]; then printf 'response lost' >&2; exit 1; fi
            printf '{"message_id":"message-%s","thread_id":"thread-1"}' "$count"
            exit 0
        fi
        printf '{"thread_id":"thread-1","messages":[]}'
        """)
        let first = GullConversationStore(cli: cli, defaults: sharedDefaults, cacheURL: cache)
        first.activate(scope: "account")
        let conversation = try first.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        _ = try? await first.send(conversation.id, content: "first", environment: environment())
        let pending = try XCTUnwrap(first.pendingByConversationID[conversation.id]?.first)
        // A separate refresh discovers the accepted thread before the retry.
        _ = try await first.load(conversation.id, threadID: "thread-1", environment: environment())
        _ = try await first.send(conversation.id, content: "second", environment: environment())
        await first.flushCache()

        let restored = GullConversationStore(cli: cli, defaults: sharedDefaults, cacheURL: cache)
        restored.activate(scope: "account")
        await restored.waitForCacheHydration()
        _ = try await restored.retryPending(pending.id, environment: environment())
        let posts = try String(contentsOf: log, encoding: .utf8).split(separator: "\n")
        XCTAssertEqual(posts.count, 3)
        XCTAssertTrue(posts[0].contains(pending.id))
        XCTAssertTrue(posts[1].contains(pending.id))
        XCTAssertFalse(posts[1].contains("--thread-id"))
        XCTAssertTrue(posts[2].contains("--thread-id thread-1"))
        XCTAssertTrue(restored.pendingMessages(for: conversation.id).isEmpty)
    }

    func testStartedConversationsAreIsolatedByAccountScope() throws {
        let sharedDefaults = defaults()
        let first = GullConversationStore(cli: nil, defaults: sharedDefaults)
        first.activate(scope: "user-a|https://sea.gulls.ai")
        _ = try first.start(recipientHandle: "@atlas:gulls.ai", sender: sender())

        let restored = GullConversationStore(cli: nil, defaults: sharedDefaults)
        restored.activate(scope: "user-a|https://sea.gulls.ai")
        XCTAssertEqual(restored.conversations.count, 1)
        restored.activate(scope: "user-b|https://sea.gulls.ai")
        XCTAssertTrue(restored.conversations.isEmpty)
    }

    func testPreviouslyAttemptedQueuedMessageRequiresReviewAfterRestart() async throws {
        let sharedDefaults = defaults()
        let cache = tmp.appendingPathComponent("cache.json")
        let log = tmp.appendingPathComponent("posts.log")
        let cli = try makeCLI(script: """
        printf 'post\\n' >> "\(log.path)"
        printf 'response lost' >&2
        exit 1
        """)
        let store = GullConversationStore(cli: cli, defaults: sharedDefaults, cacheURL: cache)
        store.activate(scope: "account")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        _ = try? await store.send(conversation.id, content: "first", environment: environment())
        await store.flushCache()

        // Crash after Retry persisted its queued state, before its worker ran.
        var snapshot = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: cache)) as? [String: Any])
        var scope = try XCTUnwrap(snapshot["account"] as? [String: Any])
        var queues = try XCTUnwrap(scope["pending"] as? [String: [[String: Any]]])
        queues[conversation.id]?[0]["state"] = "queued"
        scope["pending"] = queues
        snapshot["account"] = scope
        try JSONSerialization.data(withJSONObject: snapshot).write(to: cache)

        let restored = GullConversationStore(cli: cli, defaults: sharedDefaults, cacheURL: cache)
        restored.activate(scope: "account")
        await restored.waitForCacheHydration()
        XCTAssertEqual(restored.pendingByConversationID[conversation.id]?.first?.state, .unconfirmed)
        await restored.sendQueued(environment: environment())
        XCTAssertEqual(try String(contentsOf: log, encoding: .utf8).split(separator: "\n").count, 1)
    }

    func testDefinitiveRejectionRemainsFailedAcrossRestart() async throws {
        let sharedDefaults = defaults()
        let cache = tmp.appendingPathComponent("cache.json")
        let cli = try makeCLI(script: "printf '413: send_too_large' >&2\nexit 3")
        let store = GullConversationStore(cli: cli, defaults: sharedDefaults, cacheURL: cache)
        store.activate(scope: "account")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        _ = try? await store.send(conversation.id, content: "rejected", environment: environment())
        XCTAssertEqual(store.pendingByConversationID[conversation.id]?.first?.state, .failed)
        await store.flushCache()
        let restored = GullConversationStore(cli: cli, defaults: sharedDefaults, cacheURL: cache)
        restored.activate(scope: "account")
        await restored.waitForCacheHydration()
        XCTAssertEqual(restored.pendingByConversationID[conversation.id]?.first?.state, .failed)
    }

    func testCachedConversationMessagesAreAvailableAfterRelaunchWithoutCLI() async throws {
        let sharedDefaults = defaults()
        let cache = tmp.appendingPathComponent("conversation-cache.json")
        let cli = try makeCLI(script: """
        if [ "$1" = "--json" ]; then shift; fi
        if [ "$1" = "thread" ]; then
            printf '{"thread_id":"thread-1","messages":[{"message_id":"m-1","thread_id":"thread-1","sender_handle":"@atlas:gulls.ai","content_inline":"cached reply","created_at":"2026-10-20T00:00:00Z"}]}'
            exit 0
        fi
        exit 2
        """)
        let first = GullConversationStore(cli: cli, defaults: sharedDefaults, cacheURL: cache)
        first.activate(scope: "user-a|https://sea.gulls.ai")
        _ = try first.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        first.activate(scope: "user-a|https://sea.gulls.ai")
        // Persist the thread ID through the normal store path.
        _ = try first.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        guard let current = first.conversations.first else { return XCTFail("conversation missing") }
        _ = try await first.load(current.id, threadID: "thread-1", environment: environment())
        await first.flushCache()

        let restored = GullConversationStore(cli: nil, defaults: sharedDefaults, cacheURL: cache)
        restored.activate(scope: "user-a|https://sea.gulls.ai")
        await restored.waitForCacheHydration()
        XCTAssertEqual(restored.messages(for: current.id).map(\.content), ["cached reply"])
    }

    func testOfflineSendKeepsDurablePendingMessageForRetry() async throws {
        let sharedDefaults = defaults()
        let cache = tmp.appendingPathComponent("conversation-cache.json")
        let first = GullConversationStore(cli: nil, defaults: sharedDefaults, cacheURL: cache)
        first.activate(scope: "user-a|https://sea.gulls.ai")
        let conversation = try first.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        do {
            _ = try await first.send(conversation.id, content: "queued while offline", environment: environment())
            XCTFail("expected unavailable CLI")
        } catch let error as GullConversationError {
            XCTAssertEqual(error, .unavailable)
        }
        await first.flushCache()
        let restored = GullConversationStore(cli: nil, defaults: sharedDefaults, cacheURL: cache)
        restored.activate(scope: "user-a|https://sea.gulls.ai")
        await restored.waitForCacheHydration()
        XCTAssertEqual(restored.messages(for: conversation.id).map(\.content), ["queued while offline"])
        XCTAssertTrue(restored.hasPendingMessages)
    }

    func testImmediateSendAfterActivateDoesNotDropHydratingCache() async throws {
        let sharedDefaults = defaults()
        let cache = tmp.appendingPathComponent("conversation-cache.json")
        let historyCLI = try makeCLI(script: """
        if [ "$1" = "--json" ]; then shift; fi
        if [ "$1" = "thread" ]; then
            printf '{"thread_id":"thread-1","messages":[{"message_id":"cached-1","thread_id":"thread-1","sender_handle":"@atlas:gulls.ai","content_inline":"cached history","created_at":"2026-10-20T00:00:00Z"}]}'
            exit 0
        fi
        exit 2
        """)
        let seed = GullConversationStore(cli: historyCLI, defaults: sharedDefaults, cacheURL: cache)
        seed.activate(scope: "user-a|https://sea.gulls.ai")
        let conversation = try seed.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        _ = try await seed.load(conversation.id, threadID: "thread-1", environment: environment())
        await seed.flushCache()

        let reopened = GullConversationStore(cli: nil, defaults: sharedDefaults, cacheURL: cache)
        reopened.activate(scope: "user-a|https://sea.gulls.ai")
        do {
            _ = try await reopened.send(conversation.id, content: "queued immediately", environment: environment())
            XCTFail("expected unavailable CLI")
        } catch let error as GullConversationError {
            XCTAssertEqual(error, .unavailable)
        }
        await reopened.flushCache()

        let final = GullConversationStore(cli: nil, defaults: sharedDefaults, cacheURL: cache)
        final.activate(scope: "user-a|https://sea.gulls.ai")
        await final.waitForCacheHydration()
        XCTAssertEqual(final.messages(for: conversation.id).map(\.content), ["cached history", "queued immediately"])
        XCTAssertEqual(final.pendingMessages(for: conversation.id).count, 1)
    }

    func testConcurrentRetriesUseOneStableIdempotencyKey() async throws {
        let sharedDefaults = defaults()
        let cache = tmp.appendingPathComponent("conversation-cache.json")
        let seed = GullConversationStore(cli: nil, defaults: sharedDefaults, cacheURL: cache)
        seed.activate(scope: "user-a|https://sea.gulls.ai")
        let conversation = try seed.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        do {
            _ = try await seed.send(conversation.id, content: "retry once", environment: environment())
        } catch let error as GullConversationError {
            XCTAssertEqual(error, .unavailable)
        }
        await seed.flushCache()
        let pendingID = try XCTUnwrap(seed.pendingMessages(for: conversation.id).first)

        let logURL = tmp.appendingPathComponent("post.log")
        let cli = try makeCLI(script: """
        if [ "$1" = "--json" ]; then shift; fi
        if [ "$1" = "post" ]; then
            printf '%s\\n' "$*" >> "\(logURL.path)"
            sleep 0.3
            printf '{"message_id":"server-1","thread_id":"thread-1"}'
            exit 0
        fi
        if [ "$1" = "thread" ]; then
            printf '{"thread_id":"thread-1","messages":[]}'
            exit 0
        fi
        exit 2
        """)
        let restored = GullConversationStore(cli: cli, defaults: sharedDefaults, cacheURL: cache)
        restored.activate(scope: "user-a|https://sea.gulls.ai")
        await restored.waitForCacheHydration()

        let first = Task { @MainActor in
            try? await restored.retryPending(pendingID, environment: self.environment())
        }
        let second = Task { @MainActor in
            try? await restored.retryPending(pendingID, environment: self.environment())
        }
        _ = await first.value
        _ = await second.value

        let log = try String(contentsOf: logURL, encoding: .utf8)
        XCTAssertEqual(log.split(separator: "\n").count, 1)
        XCTAssertTrue(log.contains(pendingID))
    }

    func testIdenticalMessagesCreateIndependentOutboxEntries() async throws {
        let cache = tmp.appendingPathComponent("conversation-cache.json")
        let store = GullConversationStore(cli: nil, defaults: defaults(), cacheURL: cache)
        store.activate(scope: "user-a|https://sea.gulls.ai")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())

        for _ in 0..<2 {
            do {
                _ = try await store.send(conversation.id, content: "same text", environment: environment())
            } catch let error as GullConversationError {
                XCTAssertEqual(error, .unavailable)
            }
        }

        XCTAssertEqual(store.pendingMessages(for: conversation.id).count, 2)
        XCTAssertEqual(store.messages(for: conversation.id).map(\.content), ["same text", "same text"])
    }

    func testSendFailsBeforeNetworkWhenOutboxCannotBePersisted() async throws {
        let cacheDirectory = tmp.appendingPathComponent("cache-directory")
        try FileManager.default.createDirectory(at: cacheDirectory, withIntermediateDirectories: true)
        let store = GullConversationStore(cli: nil, defaults: defaults(), cacheURL: cacheDirectory)
        store.activate(scope: "user-a|https://sea.gulls.ai")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())

        do {
            _ = try await store.send(conversation.id, content: "must persist", environment: environment())
            XCTFail("expected local persistence failure")
        } catch let error as GullConversationError {
            XCTAssertEqual(error, .cacheUnavailable)
        }
        XCTAssertTrue(store.pendingMessages(for: conversation.id).isEmpty)
        XCTAssertTrue(store.messages(for: conversation.id).isEmpty)
    }

    func testRetryUsesPersistedOutboxIDAsIdempotencyKey() async throws {
        let sharedDefaults = defaults()
        let cache = tmp.appendingPathComponent("conversation-cache.json")
        let first = GullConversationStore(cli: nil, defaults: sharedDefaults, cacheURL: cache)
        first.activate(scope: "user-a|https://sea.gulls.ai")
        let conversation = try first.start(recipientHandle: "@atlas:gulls.ai", sender: sender())
        _ = try? await first.send(conversation.id, content: "retry me", environment: environment())
        let pendingID = try XCTUnwrap(first.pendingMessages(for: conversation.id).first)
        let cli = try makeCLI(script: """
        printf '%s\\n' "$@" >&2
        exit 1
        """)
        let restored = GullConversationStore(cli: cli, defaults: sharedDefaults, cacheURL: cache)
        restored.activate(scope: "user-a|https://sea.gulls.ai")
        await restored.waitForCacheHydration()
        XCTAssertTrue(restored.hasPendingMessages)
        do {
            _ = try await restored.retryPending(pendingID, environment: environment())
            XCTFail("expected fixture failure")
        } catch {
            let args = error.localizedDescription
            XCTAssertTrue(args.contains("--idempotency-key"))
            XCTAssertTrue(args.contains(pendingID))
        }
    }

    func testSendRejectsStaleSenderRevisionBeforeRunningCLI() async throws {
        let store = GullConversationStore(cli: nil, defaults: defaults())
        store.activate(scope: "user-a|https://sea.gulls.ai")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender(revision: "old"))

        do {
            _ = try await store.send(conversation.id, content: "hello", environment: environment(revision: "new"))
            XCTFail("expected stale revision failure")
        } catch let error as GullConversationError {
            XCTAssertEqual(error, .staleSelection)
        }
    }

    func testSuccessfulPostRemainsVisibleWhenThreadRefreshFails() async throws {
        let cli = try makeCLI(script: """
        if [ "$1" = "--json" ]; then shift; fi
        if [ "$1" = "post" ]; then
            printf '{"message_id":"message-1","thread_id":"thread-1"}'
            exit 0
        fi
        if [ "$1" = "thread" ]; then
            printf 'thread unavailable' >&2
            exit 1
        fi
        exit 2
        """)
        let store = GullConversationStore(cli: cli, defaults: defaults())
        store.activate(scope: "user-a|https://sea.gulls.ai")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())

        let messages = try await store.send(conversation.id, content: "hello", environment: environment())
        XCTAssertEqual(messages.map(\.content), ["hello"])
        XCTAssertEqual(store.conversations.first?.threadID, "thread-1")
    }

    func testHeadRefreshPreservesOlderPageCursor() async throws {
        let cli = try makeCLI(script: """
        if [ "$1" = "--json" ]; then shift; fi
        if [ "$1" = "thread" ]; then
            case " $* " in
                *" --cursor "*) printf '{"thread_id":"thread-1","messages":[{"message_id":"older","thread_id":"thread-1","sender_handle":"@atlas:gulls.ai","content_inline":"older","created_at":"2026-10-19T00:00:00Z"}]}' ;;
                *) printf '{"thread_id":"thread-1","next_cursor":"older-cursor","messages":[{"message_id":"newer","thread_id":"thread-1","sender_handle":"@atlas:gulls.ai","content_inline":"newer","created_at":"2026-10-20T00:00:00Z"}]}' ;;
            esac
            exit 0
        fi
        exit 2
        """)
        let store = GullConversationStore(cli: cli, defaults: defaults())
        store.activate(scope: "user-a|https://sea.gulls.ai")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())

        _ = try await store.load(conversation.id, threadID: "thread-1", environment: environment())
        XCTAssertTrue(store.hasMoreMessages(for: conversation.id))
        _ = try await store.load(conversation.id, threadID: "thread-1", environment: environment())
        XCTAssertTrue(store.hasMoreMessages(for: conversation.id))
    }

    func testAcknowledgedMessageStaysVisibleWhenThreadOmitsIt() async throws {
        let cli = try makeCLI(script: """
        if [ "$1" = "--json" ]; then shift; fi
        if [ "$1" = "post" ]; then
            printf '{"message_id":"message-1","thread_id":"thread-1"}'
            exit 0
        fi
        if [ "$1" = "thread" ]; then
            printf '{"thread_id":"thread-1","messages":[{"message_id":"reply-1","thread_id":"thread-1","sender_handle":"@atlas:gulls.ai","content_inline":"reply","created_at":"2026-10-20T00:00:00Z"}]}'
            exit 0
        fi
        exit 2
        """)
        let store = GullConversationStore(cli: cli, defaults: defaults())
        store.activate(scope: "user-a|https://sea.gulls.ai")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())

        let messages = try await store.send(conversation.id, content: "hello", environment: environment())
        XCTAssertTrue(messages.contains(where: { $0.id == "message-1" && $0.content == "hello" }))
        XCTAssertTrue(messages.contains(where: { $0.id == "reply-1" && $0.content == "reply" }))
    }

    func testThreadWithoutSenderHandleResolvesKnownAgentIDs() async throws {
        let cli = try makeCLI(script: """
        if [ "$1" = "--json" ]; then shift; fi
        if [ "$1" = "post" ]; then
            printf '{"message_id":"m-own","thread_id":"thread-1"}'
            exit 0
        fi
        if [ "$1" = "thread" ]; then
            printf '{"thread_id":"thread-1","messages":[{"message_id":"m-own","thread_id":"thread-1","sender_agent_id":"agent-sender","recipient_agent_ids":["agent-recipient"],"content_inline":"sent","created_at":"2026-10-19T00:00:00Z"},{"message_id":"m-other","thread_id":"thread-1","sender_agent_id":"agent-recipient","recipient_agent_ids":["agent-sender"],"content_inline":"reply","created_at":"2026-10-19T00:00:01Z"},{"message_id":"m-unknown","thread_id":"thread-1","sender_agent_id":"agent-unknown","recipient_agent_ids":[],"content_inline":"unknown","created_at":"2026-10-19T00:00:02Z"},{"message_id":"m-explicit","thread_id":"thread-1","sender_handle":"@third:gulls.ai","content_inline":"explicit","created_at":"2026-10-19T00:00:03Z"}]}'
            exit 0
        fi
        exit 2
        """)
        let store = GullConversationStore(cli: cli, defaults: defaults())
        store.activate(scope: "user-a|https://sea.gulls.ai")
        let conversation = try store.start(
            recipientHandle: "@atlas:gulls.ai",
            recipientName: "Atlas",
            recipientAgentID: "agent-recipient",
            sender: GullConversationSender(
                id: "profile-1", displayName: "Test Gull", handle: "@sender:gulls.ai",
                agentID: "agent-sender", connectionRevision: "revision-1",
                environment: environment()
            )
        )

        let messages = try await store.send(conversation.id, content: "hello", environment: environment())
        XCTAssertEqual(messages.map(\.senderHandle), ["@sender:gulls.ai", "@atlas:gulls.ai", nil, "@third:gulls.ai"])
        XCTAssertEqual(messages.first(where: { $0.id == "m-unknown" })?.senderAgentID, "agent-unknown")
    }

    func testScopeChangeDuringAwaitRejectsResultEvenWhenReturningToOriginalScope() async throws {
        let cli = try makeCLI(script: """
        if [ "$1" = "--json" ]; then shift; fi
        if [ "$1" = "post" ]; then
            sleep 1
            printf '{"message_id":"message-1","thread_id":"thread-1"}'
            exit 0
        fi
        exit 2
        """)
        let store = GullConversationStore(cli: cli, defaults: defaults())
        store.activate(scope: "user-a|https://sea.gulls.ai")
        let conversation = try store.start(recipientHandle: "@atlas:gulls.ai", sender: sender())

        let pending = Task { @MainActor in
            try await store.send(conversation.id, content: "hello", environment: self.environment())
        }
        try await Task.sleep(for: .milliseconds(100))
        store.activate(scope: "user-b|https://sea.gulls.ai")
        store.activate(scope: "user-a|https://sea.gulls.ai")

        do {
            _ = try await pending.value
            XCTFail("expected scope change failure")
        } catch let error as GullConversationError {
            XCTAssertEqual(error, .staleSelection)
        }
    }

}
