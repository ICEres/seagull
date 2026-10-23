import Foundation
import XCTest
@testable import GullsIOS

@MainActor
final class MobileLocalFirstTests: XCTestCase {
    func testColdOnlinePrepareCachesWorkspaceAndThread() async throws {
        let databaseURL = try temporaryURL()
        let store = makeStore(databaseURL: databaseURL, response: .online)
        await store.prepare()

        XCTAssertEqual(store.userID, "owner-1")
        XCTAssertEqual(store.ownedGulls.count, 1)
        XCTAssertEqual(store.inboxByHandle[fixtureGull.handle]?.count, 1)
        XCTAssertEqual(store.sentByHandle[fixtureGull.handle]?.count, 1)
        XCTAssertEqual(store.aiUsage?.balance.availableCredits, 42)

        let messages = try await store.loadThread("thread-1", for: fixtureGull)
        XCTAssertEqual(Set(messages.compactMap(\.messageID)), Set(["message-1", "sent-1"]))

        let restored = makeStore(databaseURL: databaseURL, response: .offline)
        await restored.prepare()
        XCTAssertEqual(restored.userID, "owner-1")
        XCTAssertEqual(restored.ownedGulls.count, 1)
        XCTAssertEqual(restored.inboxByHandle[fixtureGull.handle]?.count, 1)
        XCTAssertEqual(restored.sentByHandle[fixtureGull.handle]?.count, 1)
        XCTAssertEqual(Set(restored.messagesByThreadID["thread-1"]?.compactMap(\.messageID) ?? []), Set(["message-1", "sent-1"]))
    }

    func testCachedWorkspaceAppearsBeforeStalledConfigurationFinishes() async throws {
        let databaseURL = try temporaryURL()
        let online = makeStore(databaseURL: databaseURL, response: .online)
        await online.prepare()

        let stalled = makeStore(databaseURL: databaseURL, response: .stalledOffline)
        let task = Task { await stalled.prepare() }
        var restored = false
        for _ in 0..<20 {
            if stalled.hasPrepared && stalled.account != nil && !stalled.ownedGulls.isEmpty {
                restored = true
                break
            }
            try await Task.sleep(for: .milliseconds(25))
        }
        task.cancel()
        XCTAssertTrue(restored)
        XCTAssertEqual(stalled.ownedGulls.count, 1)
    }

    func testExpiredTokenTransientFailurePreservesCachedWorkspaceAndCredentials() async throws {
        let databaseURL = try temporaryURL()
        let online = makeStore(databaseURL: databaseURL, response: .online)
        await online.prepare()

        let credentials = TestMobileCredentials(session: MobileStoredSession(accessToken: "expired", refreshToken: "refresh", idToken: nil, expiresAt: .distantPast, userID: "owner-1", websiteURL: "https://sea.test"))
        let retry = makeStore(databaseURL: databaseURL, response: .transientAuthFailure, credentials: credentials)
        await retry.prepare()

        XCTAssertEqual(retry.userID, "owner-1")
        XCTAssertEqual(retry.ownedGulls.count, 1)
        XCTAssertNotNil(credentials.session)
        XCTAssertNotNil(retry.syncIssue)
    }

    func testDifferentAccountAndServerCannotRestoreAnotherCache() async throws {
        let databaseURL = try temporaryURL()
        let online = makeStore(databaseURL: databaseURL, response: .online)
        await online.prepare()

        let otherAccountCredentials = TestMobileCredentials(session: MobileStoredSession(accessToken: "token", refreshToken: nil, idToken: nil, expiresAt: .distantFuture, userID: "owner-2", websiteURL: "https://sea.test"))
        let otherAccount = makeStore(databaseURL: databaseURL, response: .offline, credentials: otherAccountCredentials)
        await otherAccount.prepare()
        XCTAssertNil(otherAccount.account)
        XCTAssertTrue(otherAccount.ownedGulls.isEmpty)

        let otherServerCredentials = TestMobileCredentials(session: MobileStoredSession(accessToken: "token", refreshToken: nil, idToken: nil, expiresAt: .distantFuture, userID: "owner-1", websiteURL: "https://other.test"))
        let otherServer = makeStore(databaseURL: databaseURL, websiteURL: "https://other.test", response: .offline, credentials: otherServerCredentials)
        await otherServer.prepare()
        XCTAssertNil(otherServer.account)
        XCTAssertTrue(otherServer.ownedGulls.isEmpty)
    }

    func testSignOutHidesCachedDataAndStaleRefreshCannotRepopulateIt() async throws {
        let databaseURL = try temporaryURL()
        let online = makeStore(databaseURL: databaseURL, response: .online)
        await online.prepare()

        let delayed = makeStore(databaseURL: databaseURL, response: .delayedRefresh)
        await delayed.prepare()
        let refreshTask = Task { await delayed.refresh() }
        try await Task.sleep(for: .milliseconds(40))
        delayed.signOut()
        refreshTask.cancel()
        try await Task.sleep(for: .milliseconds(160))

        XCTAssertNil(delayed.account)
        XCTAssertTrue(delayed.ownedGulls.isEmpty)
        let cache = MobileLocalDatabase(url: databaseURL)
        let cachedGulls = try await cache.read(scope: "\("https://sea.test".utf8.count):https://sea.test:owner-1", bucket: "gulls")
        XCTAssertTrue(cachedGulls.isEmpty)
    }

    func testOutboxSurvivesUnknownOutcomeAndExplicitRetryReusesIdempotencyKey() async throws {
        let databaseURL = try temporaryURL()
        let credentials = TestMobileCredentials(session: MobileStoredSession(accessToken: "token", refreshToken: nil, idToken: nil, expiresAt: .distantFuture, userID: "owner-1", websiteURL: "https://sea.test"))
        let recorder = RequestRecorder()
        let store = makeStore(databaseURL: databaseURL, response: .sendUnknown, credentials: credentials, recorder: recorder)
        await store.prepare()
        let pending = try await store.enqueueMessage(sender: fixtureGull, recipientHandle: "@other:gulls.ai", content: "hello", threadID: "thread-1")
        try await waitUntil { store.pendingMessages.first?.state == .unconfirmed }
        let firstBody = try XCTUnwrap(recorder.messageBodies.first)
        XCTAssertEqual(store.pendingMessages.first?.id, pending.id)

        let reopened = makeStore(databaseURL: databaseURL, response: .sendSuccess, credentials: credentials, recorder: recorder)
        await reopened.prepare()
        XCTAssertEqual(reopened.pendingMessages.first?.id, pending.id)
        let requestCountBeforeExplicitRetry = recorder.messageBodies.count
        XCTAssertEqual(requestCountBeforeExplicitRetry, 1)
        try await reopened.retryPendingMessage(pending.id)
        try await waitUntil { reopened.pendingMessages.isEmpty }
        XCTAssertEqual(recorder.messageBodies.last?["idempotency_key"] as? String, firstBody["idempotency_key"] as? String)
        XCTAssertEqual(Set(reopened.sentByHandle[fixtureGull.handle]?.compactMap(\.messageID) ?? []), Set(["sent-1", "sent-2"]))
    }

    func testOfflineThreadHydratesFirstHundredAndLoadsRemainingLocally() async throws {
        let databaseURL = try temporaryURL()
        let online = makeStore(databaseURL: databaseURL, response: .online)
        await online.prepare()
        let database = MobileLocalDatabase(url: databaseURL)
        let messages = (0..<120).map { index in
            MobileMessage(messageID: "cached-\(index)", threadID: "cached-thread", senderAgentID: "other-1", senderHandle: "@other:gulls.ai", contentInline: "message-\(index)", createdAt: "2026-10-23T00:\(String(format: "%02d", index / 60)):\(String(format: "%02d", index % 60))Z")
        }
        let entries = try messages.map { message in
            MobileLocalDatabase.Entry(id: message.messageID!, data: try JSONEncoder().encode(message), sortKey: MobileDates.parse(message.createdAt)!.timeIntervalSince1970)
        }
        try await database.write(scope: cacheScope, bucket: "thread:cached-thread", entries: entries, replacing: true)
        try await database.write(scope: cacheScope, bucket: "thread-pages", entries: [MobileLocalDatabase.Entry(id: "cached-thread", data: Data(#"{"cursor":"server-cursor"}"#.utf8), sortKey: 1)], replacing: true)

        let offline = makeStore(databaseURL: databaseURL, response: .offline)
        await offline.prepare()
        XCTAssertEqual(offline.messagesByThreadID["cached-thread"]?.count, 100)
        let loaded = try await offline.loadMoreThread("cached-thread", for: fixtureGull)
        XCTAssertEqual(loaded.count, 120)
        XCTAssertEqual(offline.threadCursors["cached-thread"], "server-cursor")
    }

    func testInboxCatchupResumesAcrossPollsAndRestartWithoutRewindingHistory() async throws {
        let databaseURL = try temporaryURL()
        let online = makeStore(databaseURL: databaseURL, response: .online)
        await online.prepare()

        let database = MobileLocalDatabase(url: databaseURL)
        let cachedItems = (0..<100).map { index in inboxFixture(index: index) }
        try await database.write(scope: cacheScope, bucket: "inbox:\(fixtureGull.handle)", entries: cachedItems.map {
            MobileLocalDatabase.Entry(id: $0.id, data: try JSONEncoder().encode($0), sortKey: Double(Int($0.id.split(separator: "-").last ?? "0") ?? 0))
        }, replacing: true)
        let page = Data(#"{"version":3,"initialized":true,"historyCursor":"history-old","headID":"delivery-99","historyCursorVerified":true}"#.utf8)
        try await database.write(scope: cacheScope, bucket: "inbox-pages", entries: [MobileLocalDatabase.Entry(id: fixtureGull.handle, data: page, sortKey: 1)], replacing: true)

        let first = makeStore(databaseURL: databaseURL, response: .inboxGap)
        await first.prepare()
        XCTAssertEqual(first.inboxByHandle[fixtureGull.handle]?.count, 250)
        XCTAssertEqual(first.inboxCursors[fixtureGull.handle], "history-old")

        let resumedRecorder = RequestRecorder()
        let resumed = makeStore(databaseURL: databaseURL, response: .inboxGap, recorder: resumedRecorder)
        await resumed.prepare()
        XCTAssertEqual(resumed.inboxByHandle[fixtureGull.handle]?.count, 250)
        XCTAssertEqual(resumed.inboxCursors[fixtureGull.handle], "history-old")
        XCTAssertTrue(resumedRecorder.requests.contains { $0.url?.query?.contains("cursor=c-100") == true })
        XCTAssertEqual(Set(resumed.inboxByHandle[fixtureGull.handle, default: []].compactMap { $0.message?.messageID }), Set((0..<250).map { "message-\($0)" }))

        let restarted = makeStore(databaseURL: databaseURL, response: .inboxGap)
        await restarted.prepare()
        XCTAssertEqual(restarted.inboxByHandle[fixtureGull.handle]?.count, 250)
        XCTAssertEqual(restarted.inboxCursors[fixtureGull.handle], "history-old")
        XCTAssertEqual(Set(restarted.inboxByHandle[fixtureGull.handle, default: []].compactMap { $0.message?.messageID }), Set((0..<250).map { "message-\($0)" }))
    }

    func testThreadCatchupCrossesBudgetAndKeepsOlderHistoryCursor() async throws {
        let databaseURL = try temporaryURL()
        let online = makeStore(databaseURL: databaseURL, response: .online)
        await online.prepare()
        let database = MobileLocalDatabase(url: databaseURL)
        let cached = (0..<100).map { index in
            MobileMessage(messageID: "old-\(index)", threadID: "gap-thread", senderAgentID: "other-1", senderHandle: "@other:gulls.ai", contentInline: "old", createdAt: "2026-10-01T00:\(String(format: "%02d", index / 60)):\(String(format: "%02d", index % 60))Z")
        }
        try await database.write(scope: cacheScope, bucket: "thread:gap-thread", entries: cached.map {
            MobileLocalDatabase.Entry(id: $0.messageID!, data: try JSONEncoder().encode($0), sortKey: Double(Int($0.messageID!.split(separator: "-").last ?? "0") ?? 0))
        }, replacing: true)
        let page = Data(#"{"version":3,"initialized":true,"historyCursor":"history-old","headID":"old-99","historyCursorVerified":true}"#.utf8)
        try await database.write(scope: cacheScope, bucket: "thread-pages", entries: [MobileLocalDatabase.Entry(id: "gap-thread", data: page, sortKey: 1)], replacing: false)

        let store = makeStore(databaseURL: databaseURL, response: .threadGap)
        await store.prepare()
        let first = try await store.loadThread("gap-thread", for: fixtureGull)
        XCTAssertEqual(first.count, 400)
        XCTAssertEqual(store.threadCursors["gap-thread"], "history-old")
        let second = try await store.loadThread("gap-thread", for: fixtureGull)
        XCTAssertEqual(second.count, 500)
        XCTAssertEqual(store.threadCursors["gap-thread"], "history-old")
        XCTAssertEqual(Set(second.compactMap(\.messageID)), Set((0..<500).map { "old-\($0)" }))
    }

    func testRepeatedInboxCursorPreservesIncompleteCatchupAcrossRestart() async throws {
        let databaseURL = try temporaryURL()
        let online = makeStore(databaseURL: databaseURL, response: .online)
        await online.prepare()
        let database = MobileLocalDatabase(url: databaseURL)
        let cached = (0..<100).map { inboxFixture(index: $0) }
        try await database.write(scope: cacheScope, bucket: "inbox:\(fixtureGull.handle)", entries: cached.map {
            MobileLocalDatabase.Entry(id: $0.id, data: try JSONEncoder().encode($0), sortKey: Double(Int($0.id.split(separator: "-").last ?? "0") ?? 0))
        }, replacing: true)
        let page = Data(#"{"version":3,"initialized":true,"historyCursor":"history-old","headID":"delivery-99","historyCursorVerified":true}"#.utf8)
        try await database.write(scope: cacheScope, bucket: "inbox-pages", entries: [MobileLocalDatabase.Entry(id: fixtureGull.handle, data: page, sortKey: 1)], replacing: true)

        let store = makeStore(databaseURL: databaseURL, response: .inboxLoop)
        await store.prepare()
        XCTAssertNotNil(store.syncIssue)
        XCTAssertEqual(store.inboxCursors[fixtureGull.handle], "history-old")

        let restarted = makeStore(databaseURL: databaseURL, response: .inboxLoop)
        await restarted.prepare()
        XCTAssertNotNil(restarted.syncIssue)
        XCTAssertEqual(restarted.inboxCursors[fixtureGull.handle], "history-old")
        XCTAssertEqual(Set(restarted.inboxByHandle[fixtureGull.handle, default: []].compactMap { $0.message?.messageID }), Set((0..<150).map { "message-\($0)" }))
    }

    func testContentlessRawInboxAnchorCompletesCatchupWithoutDuplicateVisibleMessages() async throws {
        let databaseURL = try temporaryURL()
        let online = makeStore(databaseURL: databaseURL, response: .online)
        await online.prepare()
        let database = MobileLocalDatabase(url: databaseURL)
        let cached = (0..<100).map { inboxFixture(index: $0) }
        try await database.write(scope: cacheScope, bucket: "inbox:\(fixtureGull.handle)", entries: cached.map {
            MobileLocalDatabase.Entry(id: $0.id, data: try JSONEncoder().encode($0), sortKey: Double(Int($0.id.split(separator: "-").last ?? "0") ?? 0))
        }, replacing: true)
        let page = Data(#"{"version":3,"initialized":true,"historyCursor":"history-old","headID":"delivery-99","historyCursorVerified":true}"#.utf8)
        try await database.write(scope: cacheScope, bucket: "inbox-pages", entries: [MobileLocalDatabase.Entry(id: fixtureGull.handle, data: page, sortKey: 1)], replacing: true)

        let store = makeStore(databaseURL: databaseURL, response: .inboxContentlessAnchor)
        await store.prepare()
        _ = await store.refreshInbox(for: fixtureGull)
        let items = store.inboxByHandle[fixtureGull.handle, default: []]
        let visibleIDs = items.compactMap { $0.message?.messageID }
        XCTAssertEqual(Set(visibleIDs), Set((0..<99).map { "message-\($0)" } + (100..<250).map { "message-\($0)" }))
        XCTAssertEqual(visibleIDs.count, Set(visibleIDs).count)
        XCTAssertTrue(items.contains { $0.id == "delivery-99" && $0.message == nil })
        XCTAssertEqual(store.inboxCursors[fixtureGull.handle], "history-old")
    }

    func testEnqueueStorageFailureDoesNotPostOrExposePendingMessage() async throws {
        let databaseDirectory = FileManager.default.temporaryDirectory.appendingPathComponent("gulls-cache-file-\(UUID().uuidString)")
        try Data("regular file".utf8).write(to: databaseDirectory)
        let recorder = RequestRecorder()
        let store = makeStore(databaseURL: databaseDirectory.appendingPathComponent("mobile.sqlite"), response: .online, recorder: recorder)
        await store.prepare()
        do {
            _ = try await store.enqueueMessage(sender: fixtureGull, recipientHandle: "@other:gulls.ai", content: "should not post")
            XCTFail("Expected enqueue to fail when the database parent is a regular file")
        } catch {
            XCTAssertTrue(store.pendingMessages.isEmpty)
            XCTAssertTrue(recorder.messageBodies.isEmpty)
        }
    }

    func testOldQueuedMessageCannotBeRetriedAutomaticallyOrExplicitly() async throws {
        let databaseURL = try temporaryURL()
        let database = MobileLocalDatabase(url: databaseURL)
        let old = MobilePendingMessage(id: "old-pending", sender: fixtureGull, recipientHandle: "@other:gulls.ai", content: "old", threadID: "thread-1", createdAt: Date(timeIntervalSinceNow: -7 * 86_400), state: .queued)
        let encoded = try JSONEncoder().encode(old)
        let accountData = try JSONEncoder().encode(CachedAccountFixture(identity: fixtureIdentity, runtime: fixtureRuntime, lastSyncedAt: nil))
        try await database.write(scope: cacheScope, bucket: "account", entries: [MobileLocalDatabase.Entry(id: "snapshot", data: accountData, sortKey: 1)], replacing: true)
        try await database.write(scope: cacheScope, bucket: "gulls", entries: [MobileLocalDatabase.Entry(id: fixtureGull.agentID, data: try JSONEncoder().encode(fixtureGull), sortKey: 1)], replacing: true)
        try await database.write(scope: cacheScope, bucket: "outbox", entries: [MobileLocalDatabase.Entry(id: old.id, data: encoded, sortKey: old.createdAt.timeIntervalSince1970)], replacing: true)
        let recorder = RequestRecorder()
        let credentials = TestMobileCredentials(session: MobileStoredSession(accessToken: "token", refreshToken: nil, idToken: nil, expiresAt: .distantFuture, userID: "owner-1", websiteURL: "https://sea.test"))
        let store = makeStore(databaseURL: databaseURL, response: .offline, credentials: credentials, recorder: recorder)
        await store.prepare()
        XCTAssertEqual(store.pendingMessages.first?.id, old.id)
        do {
            try await store.retryPendingMessage(old.id)
            XCTFail("Expected old pending message retry to be rejected")
        } catch {
            XCTAssertTrue(recorder.messageBodies.isEmpty)
        }
    }

    func testExpiredSessionWithoutRefreshTokenKeepsCachedWorkspaceReadOnly() async throws {
        let databaseURL = try temporaryURL()
        let online = makeStore(databaseURL: databaseURL, response: .online)
        await online.prepare()

        let credentials = TestMobileCredentials(session: MobileStoredSession(accessToken: "expired", refreshToken: nil, idToken: nil, expiresAt: .distantPast, userID: "owner-1", websiteURL: "https://sea.test"))
        let recorder = RequestRecorder()
        let restored = makeStore(databaseURL: databaseURL, response: .online, credentials: credentials, recorder: recorder)
        await restored.prepare()

        XCTAssertTrue(restored.isSignedIn)
        XCTAssertEqual(restored.ownedGulls.count, 1)
        XCTAssertEqual(restored.inboxByHandle[fixtureGull.handle]?.count, 1)
        XCTAssertEqual(restored.sentByHandle[fixtureGull.handle]?.count, 1)
        XCTAssertNotNil(credentials.session)
        XCTAssertTrue(recorder.requests.filter { $0.url?.path != "/config.js" }.isEmpty)
        XCTAssertTrue(recorder.messageBodies.isEmpty)
    }

    func testOfflineThreadRestoreBuildsBodiesFromCachedInboxAndSentWithoutThreadRequest() async throws {
        let databaseURL = try temporaryURL()
        let online = makeStore(databaseURL: databaseURL, response: .online)
        await online.prepare()

        let recorder = RequestRecorder()
        let restored = makeStore(databaseURL: databaseURL, response: .offline, recorder: recorder)
        await restored.prepare()
        await restored.restoreCachedThread("thread-1")

        let messages = restored.messagesByThreadID["thread-1"] ?? []
        XCTAssertEqual(Set(messages.compactMap(\.messageID)), Set(["message-1", "sent-1"]))
        XCTAssertTrue(recorder.requests.filter { $0.url?.path == "/agent-network/threads/thread-1" }.isEmpty)
    }

    private enum ResponseMode: Equatable { case online, offline, inboxGap, inboxLoop, inboxContentlessAnchor, threadGap, stalledOffline, transientAuthFailure, delayedRefresh, sendUnknown, sendSuccess }

    private let fixtureGull = CloudGull(agentID: "gull-1", ownerUserID: "owner-1", handle: "@mine:gulls.ai", displayName: "Mine", bio: nil, capabilities: ["chat"], relationshipPosture: "open", approvalRequiredFor: [], allowedUseTerms: [], contactExplanation: nil, protocols: ["gulls"], status: "active", nodeID: nil, deliveryMode: "cloud", lastSeenAt: nil, createdAt: nil, updatedAt: nil)
    private let fixtureIdentity = CloudHumanIdentity(userID: "owner-1", provider: "cognito", subject: "subject-1", email: "owner@example.com", displayName: "Owner", createdAt: nil, updatedAt: nil)
    private let fixtureRuntime = CloudRuntimeConfig(socialAPIURL: "https://social.test", messageAPIURL: nil, aiProviderAPIURL: nil, adminDomainName: nil, auth: nil)
    private let cacheScope = "16:https://sea.test:owner-1"

    private func makeStore(databaseURL: URL, websiteURL: String = "https://sea.test", response mode: ResponseMode, credentials: TestMobileCredentials? = nil, recorder: RequestRecorder? = nil) -> MobileAppStore {
        let credentials = credentials ?? TestMobileCredentials(session: MobileStoredSession(accessToken: "token", refreshToken: nil, idToken: nil, expiresAt: .distantFuture, userID: "owner-1", websiteURL: websiteURL))
        let session = makeSession(mode: mode, recorder: recorder)
        let defaults = UserDefaults(suiteName: "gulls-local-first-\(UUID().uuidString)")!
        return MobileAppStore(websiteURL: websiteURL, session: session, credentials: credentials, defaults: defaults, database: MobileLocalDatabase(url: databaseURL), monitorNetwork: false)
    }

    private func makeSession(mode: ResponseMode, recorder: RequestRecorder?) -> URLSession {
        let token = LocalFirstURLProtocol.install { request in
            recorder?.append(request)
            return self.response(for: request, mode: mode)
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpAdditionalHeaders = ["X-Local-First-Session": token]
        configuration.protocolClasses = [LocalFirstURLProtocol.self]
        return URLSession(configuration: configuration)
    }

    private func response(for request: URLRequest, mode: ResponseMode) -> StubResponse {
        let path = request.url?.path ?? ""
        if path == "/config.js" {
            if mode == .stalledOffline { return StubResponse(body: Data(), status: 503, delay: 0.4) }
            if mode == .offline { return StubResponse(body: Data(), status: 503) }
            return StubResponse(body: Data(#"window.SEAGULL_CONFIG = {"socialApiUrl":"https://social.test","auth":{"mode":"cognito","issuer":"https://cognito.test","clientId":"client"}}"#.utf8), contentType: "text/javascript")
        }
        if mode == .transientAuthFailure && request.url?.host == "cognito.test" { return StubResponse(body: Data(), status: 503) }
        if mode == .offline || mode == .stalledOffline { return StubResponse(body: Data(), status: 503) }
        if mode == .inboxGap && path == "/agent-network/inbox" {
            let cursor = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "cursor" }?.value
            switch cursor {
            case nil: return json(inboxJSON(range: 200..<250, next: "c-200"))
            case "c-200": return json(inboxJSON(range: 150..<200, next: "c-150"))
            case "c-150": return json(inboxJSON(range: 100..<150, next: "c-100"))
            case "c-100": return json(inboxJSON(range: 50..<100, next: "c-50"))
            default: return json(inboxJSON(range: 0..<0, next: nil))
            }
        }
        if (mode == .inboxLoop || mode == .inboxContentlessAnchor) && path == "/agent-network/inbox" {
            let cursor = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "cursor" }?.value
            if mode == .inboxLoop {
                if cursor == nil { return json(inboxJSON(range: 100..<150, next: "c-loop")) }
                return json(inboxJSON(range: 50..<100, next: "c-loop"))
            }
            switch cursor {
            case nil: return json(inboxJSON(range: 200..<250, next: "c-200"))
            case "c-200": return json(inboxJSON(range: 150..<200, next: "c-150"))
            case "c-150": return json(contentlessAnchorJSON())
            default: return json(inboxJSON(range: 0..<0, next: nil))
            }
        }
        if mode == .threadGap && path == "/agent-network/threads/gap-thread" {
            let cursor = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "cursor" }?.value
            switch cursor {
            case nil: return json(threadJSON(range: 400..<500, next: "c-400"))
            case "c-400": return json(threadJSON(range: 300..<400, next: "c-300"))
            case "c-300": return json(threadJSON(range: 200..<300, next: "c-200"))
            case "c-200": return json(threadJSON(range: 100..<200, next: "c-100"))
            case "c-100": return json(threadJSON(range: 0..<100, next: nil))
            default: return json(threadJSON(range: 0..<0, next: nil))
            }
        }
        if path == "/me" {
            if mode == .transientAuthFailure { return StubResponse(body: Data(), status: 503) }
            return json(#"{"identity":{"user_id":"owner-1","provider":"cognito","subject":"subject-1","email":"owner@example.com","display_name":"Owner"}}"#)
        }
        if path == "/profiles" {
            let body = Data(#"{"items":[{"agent_id":"gull-1","owner_user_id":"owner-1","handle":"@mine:gulls.ai","display_name":"Mine","capabilities":["chat"],"relationship_posture":"open","approval_required_for":[],"allowed_use_terms":[],"protocols":["gulls"],"status":"active","delivery_mode":"cloud"}]}"#.utf8)
            return StubResponse(body: body, delay: mode == .delayedRefresh ? 0.12 : 0)
        }
        if path == "/agent-network/inbox" { return json(#"{"items":[{"delivery":{"delivery_id":"delivery-1","message_id":"message-1","thread_id":"thread-1","sender_agent_id":"other-1","recipient_agent_id":"gull-1","status":"delivered","created_at":"2026-10-23T00:00:00Z"},"message":{"message_id":"message-1","thread_id":"thread-1","sender_agent_id":"other-1","sender_handle":"@other:gulls.ai","content_inline":"hello","created_at":"2026-10-23T00:00:00Z"},"current_message":{"content_inline":"hello"}}],"next_cursor":null}"#) }
        if path == "/agent-network/sent" { return json(#"{"messages":[{"message_id":"sent-1","thread_id":"thread-1","sender_agent_id":"gull-1","sender_handle":"@mine:gulls.ai","content_inline":"sent","created_at":"2026-10-22T00:00:00Z"}],"truncated":false}"#) }
        if path == "/agent-network/threads/thread-1" { return json(#"{"thread_id":"thread-1","messages":[{"message_id":"message-1","thread_id":"thread-1","sender_agent_id":"other-1","sender_handle":"@other:gulls.ai","content_inline":"hello","created_at":"2026-10-23T00:00:00Z"}],"next_cursor":null}"#) }
        if path == "/me/ai-usage" { return json(#"{"owner_user_id":"owner-1","balance":{"available_credits":42},"usage":[],"entries":[]}"#) }
        if path == "/health" { return json(#"{"ok":true,"app":"social"}"#) }
        if path == "/agent-network/messages" {
            if mode == .sendUnknown { return StubResponse(body: Data(), status: 503) }
            return json(#"{"message":{"message_id":"sent-2","thread_id":"thread-1","sender_agent_id":"gull-1","sender_handle":"@mine:gulls.ai","content_inline":"hello","created_at":"2026-10-23T00:00:00Z"},"message_id":"sent-2","thread_id":"thread-1"}"#)
        }
        return json(#"{"items":[],"messages":[],"usage":[],"entries":[],"balance":{"available_credits":42},"ok":true}"#)
    }

    private func json(_ string: String) -> StubResponse { StubResponse(body: Data(string.utf8)) }

    private func inboxFixture(index: Int) -> MobileInboxItem {
        let timestamp = "2026-10-01T00:\(String(format: "%02d", index / 60)):\(String(format: "%02d", index % 60))Z"
        let message = MobileMessage(messageID: "message-\(index)", threadID: "gap-thread", senderAgentID: "other-1", senderHandle: "@other:gulls.ai", contentInline: "message", createdAt: timestamp)
        let delivery = MobileDelivery(deliveryID: "delivery-\(index)", messageID: message.messageID, threadID: message.threadID, senderAgentID: "other-1", recipientAgentID: "gull-1", status: "delivered", currentStage: nil, createdAt: timestamp, updatedAt: timestamp)
        return MobileInboxItem(delivery: delivery, message: message, currentMessage: MobileCurrentMessage(contentInline: "message"))
    }

    private func inboxJSON(range: Range<Int>, next: String?) -> String {
        let items = range.map { index -> [String: Any] in
            let fixture = inboxFixture(index: index)
            return ["delivery": ["delivery_id": fixture.delivery.deliveryID, "message_id": fixture.delivery.messageID as Any, "thread_id": fixture.delivery.threadID as Any, "sender_agent_id": "other-1", "recipient_agent_id": "gull-1", "status": "delivered", "created_at": fixture.delivery.createdAt as Any], "message": ["message_id": fixture.message?.messageID as Any, "thread_id": "gap-thread", "sender_agent_id": "other-1", "sender_handle": "@other:gulls.ai", "content_inline": "message", "created_at": fixture.message?.createdAt as Any], "current_message": ["content_inline": "message"]]
        }
        var value: [String: Any] = ["items": items]
        if let next { value["next_cursor"] = next }
        return String(data: try! JSONSerialization.data(withJSONObject: value), encoding: .utf8)!
    }

    private func contentlessAnchorJSON() -> String {
        let anchor: [String: Any] = ["delivery": ["delivery_id": "delivery-99", "message_id": "message-99", "thread_id": "gap-thread", "sender_agent_id": "other-1", "recipient_agent_id": "gull-1", "status": "delivered", "created_at": "2026-10-01T00:01:39Z"]]
        let visible = (100..<150).map { index -> [String: Any] in
            let timestamp = "2026-10-01T00:\(String(format: "%02d", index / 60)):\(String(format: "%02d", index % 60))Z"
            return [
                "delivery": ["delivery_id": "delivery-\(index)", "message_id": "message-\(index)", "thread_id": "gap-thread", "sender_agent_id": "other-1", "recipient_agent_id": "gull-1", "status": "delivered", "created_at": timestamp],
                "message": ["message_id": "message-\(index)", "thread_id": "gap-thread", "sender_agent_id": "other-1", "sender_handle": "@other:gulls.ai", "content_inline": "message", "created_at": timestamp],
                "current_message": ["content_inline": "message"]
            ]
        }
        return String(data: try! JSONSerialization.data(withJSONObject: ["items": [anchor] + visible, "next_cursor": "c-100"]), encoding: .utf8)!
    }

    private func threadJSON(range: Range<Int>, next: String?) -> String {
        let messages = range.map { index -> [String: Any] in
            ["message_id": "old-\(index)", "thread_id": "gap-thread", "sender_agent_id": "other-1", "sender_handle": "@other:gulls.ai", "content_inline": "message", "created_at": "2026-10-01T00:\(String(format: "%02d", index / 60)):\(String(format: "%02d", index % 60))Z"]
        }
        var value: [String: Any] = ["thread_id": "gap-thread", "messages": messages]
        if let next { value["next_cursor"] = next }
        return String(data: try! JSONSerialization.data(withJSONObject: value), encoding: .utf8)!
    }

    private func waitUntil(_ predicate: @escaping () -> Bool) async throws {
        for _ in 0..<80 {
            if predicate() { return }
            try await Task.sleep(for: .milliseconds(25))
        }
        XCTFail("Timed out waiting for local-first state")
    }

    private func temporaryURL() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("gulls-local-first-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent("mobile.sqlite")
    }
}

private final class TestMobileCredentials: MobileCredentialStore {
    var session: MobileStoredSession?
    init(session: MobileStoredSession?) { self.session = session }
    func read() throws -> MobileStoredSession? { session }
    func write(_ session: MobileStoredSession) throws { self.session = session }
    func delete() throws { session = nil }
}

private struct CachedAccountFixture: Codable {
    let identity: CloudHumanIdentity
    let runtime: CloudRuntimeConfig
    let lastSyncedAt: Date?
}

private final class RequestRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var storedRequests: [URLRequest] = []
    private var storedMessageBodies: [[String: Any]] = []
    var requests: [URLRequest] { lock.lock(); defer { lock.unlock() }; return storedRequests }
    var messageBodies: [[String: Any]] { lock.lock(); defer { lock.unlock() }; return storedMessageBodies }
    func append(_ request: URLRequest) {
        var recorded = request
        if recorded.httpBody == nil, let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var body = Data()
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let count = stream.read(&buffer, maxLength: buffer.count)
                guard count > 0 else { break }
                body.append(buffer, count: count)
            }
            recorded.httpBody = body
        }
        lock.lock()
        storedRequests.append(recorded)
        lock.unlock()
        guard recorded.url?.path == "/agent-network/messages", let body = recorded.httpBody,
              let json = try? JSONSerialization.jsonObject(with: body) as? [String: Any] else { return }
        lock.lock()
        storedMessageBodies.append(json)
        lock.unlock()
    }
}

private struct StubResponse {
    let body: Data
    let contentType: String
    let status: Int
    let delay: TimeInterval
    init(body: Data, contentType: String = "application/json", status: Int = 200, delay: TimeInterval = 0) {
        self.body = body; self.contentType = contentType; self.status = status; self.delay = delay
    }
}

private final class LocalFirstURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var handlers: [String: (URLRequest) -> StubResponse] = [:]
    private var workItem: DispatchWorkItem?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let token = request.value(forHTTPHeaderField: "X-Local-First-Session"), let url = request.url else { return }
        Self.lock.lock(); let handler = Self.handlers[token]; Self.lock.unlock()
        guard let response = handler?(request) else { return }
        let deliver = DispatchWorkItem { [weak self] in
            guard let self, !self.workItem!.isCancelled else { return }
            let http = HTTPURLResponse(url: url, statusCode: response.status, httpVersion: nil, headerFields: ["Content-Type": response.contentType])!
            self.client?.urlProtocol(self, didReceive: http, cacheStoragePolicy: .notAllowed)
            if !response.body.isEmpty { self.client?.urlProtocol(self, didLoad: response.body) }
            self.client?.urlProtocolDidFinishLoading(self)
        }
        workItem = deliver
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + response.delay, execute: deliver)
    }
    override func stopLoading() { workItem?.cancel() }

    static func install(_ handler: @escaping (URLRequest) -> StubResponse) -> String {
        let token = UUID().uuidString
        lock.lock(); handlers[token] = handler; lock.unlock()
        return token
    }
}
