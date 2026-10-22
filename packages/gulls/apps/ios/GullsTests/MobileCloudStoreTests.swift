import Foundation
import XCTest
@testable import GullsIOS

@MainActor
final class MobileCloudStoreTests: XCTestCase {
    func testExpiredKeychainSessionRefreshesAndRestoresAccount() async throws {
        let credentials = TestCredentials(session: MobileStoredSession(accessToken: "old", refreshToken: "refresh", idToken: nil, expiresAt: Date(timeIntervalSinceNow: -60)))
        let recorder = RequestRecorder()
        let session = makeSession { request in
            recorder.append(request)
            switch (request.url?.host, request.url?.path) {
            case ("sea.test", "/config.js"):
                return .json(#"window.SEAGULL_CONFIG = {"socialApiUrl":"https://social.test","auth":{"mode":"cognito","issuer":"https://cognito.test","clientId":"client"}}"#, contentType: "text/javascript")
            case ("cognito.test", "/"):
                return .json(#"{"AuthenticationResult":{"AccessToken":"new","IdToken":"id","ExpiresIn":3600}}"#)
            case ("social.test", "/me"):
                return .json(#"{"identity":{"user_id":"user-1","provider":"cognito","subject":"sub-1","email":"owner@example.com"}}"#)
            case ("social.test", "/profiles"):
                return .json(#"{"items":[]}"#)
            case ("social.test", "/agent-chats"):
                return .json(#"{"items":[]}"#)
            case ("social.test", "/me/ai-usage"):
                return .json(#"{"owner_user_id":"user-1","balance":{"available_credits":10},"usage":[],"entries":[]}"#)
            case ("social.test", "/health"):
                return .json(#"{"ok":true,"app":"social"}"#)
            default:
                return .json(#"{}"#)
            }
        }
        let store = MobileAppStore(websiteURL: "https://sea.test", session: session, credentials: credentials)
        await store.prepare()
        XCTAssertTrue(store.isSignedIn)
        XCTAssertEqual(store.accessToken, "new")
        XCTAssertEqual(store.userID, "user-1")
        XCTAssertEqual(store.account?.email, "owner@example.com")
        XCTAssertTrue(recorder.requests.contains { $0.value(forHTTPHeaderField: "X-Amz-Target") == "AWSCognitoIdentityProviderService.InitiateAuth" })
    }

    func testInboxDTODecodesSnakeCaseIDsThroughCloudAPI() async throws {
        let session = makeSession { _ in .json(#"{"delivery":{"delivery_id":"delivery-1","message_id":"message-1","thread_id":"thread-1","sender_agent_id":"agent-1","status":"delivered"},"message":{"message_id":"message-1","thread_id":"thread-1","sender_agent_id":"agent-1","sender_handle":"@other:gulls.ai","recipient_agent_ids":["owned-1"],"content_inline":"hello"},"current_message":{"content_inline":"hello"}}"#) }
        let api = try CloudAPI(baseURL: "https://social.test", session: session)
        let item: MobileInboxItem = try await api.get("/inbox")
        XCTAssertEqual(item.id, "delivery-1")
        XCTAssertEqual(item.delivery.messageID, "message-1")
        XCTAssertEqual(item.message?.senderHandle, "@other:gulls.ai")
        XCTAssertEqual(item.message?.recipientAgentIDs, ["owned-1"])
    }

    func testSignedRequestIncludesOwnerQueryAndBearerToken() async throws {
        let credentials = TestCredentials(session: MobileStoredSession(accessToken: "token", refreshToken: nil, idToken: nil, expiresAt: Date(timeIntervalSinceNow: 3600)))
        let recorder = RequestRecorder()
        let session = makeSession { request in
            recorder.append(request)
            switch request.url?.path {
            case "/config.js": return .json(#"window.SEAGULL_CONFIG = {"socialApiUrl":"https://social.test","auth":{"mode":"cognito","issuer":"https://cognito.test","clientId":"client"}}"#, contentType: "text/javascript")
            case "/me": return .json(#"{"identity":{"user_id":"user-1","provider":"cognito","subject":"sub","email":"owner@example.com"}}"#)
            case "/profiles": return .json(#"{"items":[]}"#)
            case "/agent-chats": return .json(#"{"items":[]}"#)
            case "/me/ai-usage": return .json(#"{"owner_user_id":"user-1","balance":{"available_credits":0},"usage":[],"entries":[]}"#)
            case "/health": return .json(#"{"ok":true}"#)
            default: return .json(#"{}"#)
            }
        }
        let store = MobileAppStore(websiteURL: "https://sea.test", session: session, credentials: credentials)
        await store.prepare()
        let profile = try XCTUnwrap(recorder.requests.first { $0.url?.path == "/profiles" })
        XCTAssertEqual(profile.value(forHTTPHeaderField: "Authorization"), "Bearer token")
        XCTAssertEqual(URLComponents(url: try XCTUnwrap(profile.url), resolvingAgainstBaseURL: false)?.queryItems?.first?.name, "owner_user_id")
    }

    func testInboxUsesOwnerScopedNetworkFacade() async throws {
        let credentials = TestCredentials(session: MobileStoredSession(accessToken: "token", refreshToken: nil, idToken: nil, expiresAt: Date(timeIntervalSinceNow: 3600)))
        let recorder = RequestRecorder()
        let session = makeSession { request in
            recorder.append(request)
            switch request.url?.path {
            case "/config.js": return .json(#"window.SEAGULL_CONFIG = {"socialApiUrl":"https://social.test","auth":{"mode":"cognito","issuer":"https://cognito.test","clientId":"client"}}"#, contentType: "text/javascript")
            case "/me": return .json(#"{"identity":{"user_id":"user-1","provider":"cognito","subject":"sub","email":"owner@example.com"}}"#)
            case "/profiles": return .json(#"{"items":[]}"#)
            case "/agent-chats": return .json(#"{"items":[]}"#)
            case "/me/ai-usage": return .json(#"{"owner_user_id":"user-1","balance":{"available_credits":0},"usage":[],"entries":[]}"#)
            case "/health": return .json(#"{"ok":true}"#)
            case "/agent-network/inbox": return .json(#"{"items":[],"next_cursor":"next"}"#)
            default: return .json(#"{}"#)
            }
        }
        let store = MobileAppStore(websiteURL: "https://sea.test", session: session, credentials: credentials)
        await store.prepare()
        let gull = CloudGull(agentID: "gull-1", ownerUserID: "user-1", handle: "@mine:gulls.ai", displayName: nil, bio: nil, capabilities: [], relationshipPosture: "open", approvalRequiredFor: [], allowedUseTerms: [], contactExplanation: nil, protocols: [], status: "active", nodeID: nil, deliveryMode: "cloud", lastSeenAt: nil, createdAt: nil, updatedAt: nil)
        let loaded = await store.refreshInbox(for: gull)
        XCTAssertTrue(loaded)
        let request = try XCTUnwrap(recorder.requests.first { $0.url?.path == "/agent-network/inbox" })
        let query = URLComponents(url: try XCTUnwrap(request.url), resolvingAgainstBaseURL: false)?.queryItems ?? []
        XCTAssertEqual(query.first(where: { $0.name == "owner_user_id" })?.value, "user-1")
        XCTAssertEqual(query.first(where: { $0.name == "agent_handle" })?.value, "@mine:gulls.ai")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer token")
    }
    func testFreshEmailCodeSignInCompletesThroughMe() async throws {
        let recorder = RequestRecorder()
        let session = makeSession { request in
            recorder.append(request)
            switch (request.url?.host, request.url?.path) {
            case ("sea.test", "/config.js"):
                return .json(#"window.SEAGULL_CONFIG = {"socialApiUrl":"https://social.test","auth":{"mode":"cognito","issuer":"https://cognito.test","clientId":"client"}}"#, contentType: "text/javascript")
            case ("cognito.test", "/") where request.value(forHTTPHeaderField: "X-Amz-Target")?.hasSuffix("InitiateAuth") == true:
                return .json(#"{"ChallengeName":"EMAIL_OTP","Session":"challenge"} "#.trimmingCharacters(in: .whitespacesAndNewlines))
            case ("cognito.test", "/"):
                return .json(#"{"AuthenticationResult":{"AccessToken":"fresh","IdToken":"id","RefreshToken":"rotating","ExpiresIn":3600}}"#)
            case ("social.test", "/me"):
                return .json(#"{"identity":{"user_id":"user-fresh","provider":"cognito","subject":"sub","email":"fresh@example.com"}}"#)
            default:
                return .json(#"{"items":[],"usage":[],"entries":[],"balance":{"available_credits":0},"ok":true}"#)
            }
        }
        let store = MobileAppStore(websiteURL: "https://sea.test", session: session, credentials: TestCredentials(session: nil))
        store.email = "Fresh@example.com"
        await store.beginSignIn()
        XCTAssertTrue(store.challengePending)
        store.code = "123456"
        await store.completeSignIn()
        XCTAssertTrue(store.isSignedIn)
        XCTAssertEqual(store.userID, "user-fresh")
        XCTAssertTrue(recorder.requests.contains { $0.value(forHTTPHeaderField: "X-Amz-Target")?.hasSuffix("RespondToAuthChallenge") == true })
    }

    func testValidUnexpiredRestoreBootstrapsAccountWithoutRefresh() async {
        let recorder = RequestRecorder()
        let credentials = TestCredentials(session: MobileStoredSession(accessToken: "valid", refreshToken: "refresh", idToken: nil, expiresAt: Date(timeIntervalSinceNow: 3600)))
        let session = makeSession { request in
            recorder.append(request)
            if request.url?.path == "/config.js" { return .json(#"window.SEAGULL_CONFIG = {"socialApiUrl":"https://social.test","auth":{"mode":"cognito","issuer":"https://cognito.test","clientId":"client"}}"#, contentType: "text/javascript") }
            if request.url?.path == "/me" { return .json(#"{"identity":{"user_id":"restored","provider":"cognito","subject":"sub","email":"restored@example.com"}}"#) }
            return .json(#"{"items":[],"usage":[],"entries":[],"balance":{"available_credits":0},"ok":true}"#)
        }
        let store = MobileAppStore(websiteURL: "https://sea.test", session: session, credentials: credentials)
        await store.prepare()
        XCTAssertTrue(store.isSignedIn)
        XCTAssertEqual(store.userID, "restored")
        XCTAssertFalse(recorder.requests.contains { $0.value(forHTTPHeaderField: "X-Amz-Target") != nil })
    }

    func testSignOutClearsSentAndAdminState() {
        let store = MobileAppStore.preview()
        XCTAssertFalse(store.sentByHandle.isEmpty)
        store.signOut()
        XCTAssertTrue(store.sentByHandle.isEmpty)
        XCTAssertTrue(store.sentTruncatedHandles.isEmpty)
        XCTAssertFalse(store.isAdmin)
        XCTAssertFalse(store.isSignedIn)
    }

    func testPreviewSendPromptAndRuntimeStayInMemory() async throws {
        let recorder = RequestRecorder()
        let store = MobileAppStore.preview(session: makeSession { request in recorder.append(request); return .json("{}") })
        let gull = try XCTUnwrap(store.ownedGulls.first)
        let counterpart = try XCTUnwrap(store.savedGulls.first)
        await store.prepare()
        await store.refresh()
        _ = await store.refreshGulls()
        _ = await store.refreshInbox(for: gull)
        _ = await store.refreshSent(for: gull)
        _ = try await store.loadThread("preview-thread-0", for: gull)
        _ = try await store.lookupPublicGull(handle: counterpart.handle)
        let before = store.sentByHandle[gull.handle]?.count ?? 0
        let response = try await store.send(sender: gull, recipientHandle: counterpart.handle, content: "preview send", threadID: "preview-thread-0", idempotencyKey: "preview-id")
        XCTAssertEqual(response.message?.senderHandle, gull.handle)
        XCTAssertEqual(store.sentByHandle[gull.handle]?.count, before + 1)
        XCTAssertTrue(store.messagesByThreadID["preview-thread-0"]?.contains(where: { $0.messageID == "preview-send-preview-id" }) == true)
        try await store.savePrompt(for: gull, instructions: "local preview")
        _ = try await store.setRuntime(for: gull, mode: .manual)
        let prompt = try await store.loadPrompt(for: gull)
        let runtime = try await store.loadRuntime(for: gull)
        XCTAssertEqual(prompt, "local preview")
        XCTAssertEqual(runtime.mode, .manual)
        XCTAssertTrue(recorder.requests.isEmpty)
    }

    func testSendUsesExactBodyAndUpdatesSentState() async throws {
        let credentials = TestCredentials(session: MobileStoredSession(accessToken: "token", refreshToken: nil, idToken: nil, expiresAt: Date(timeIntervalSinceNow: 3600)))
        let recorder = RequestRecorder()
        let session = makeSession { request in
            recorder.append(request)
            switch request.url?.path {
            case "/config.js": return .json(#"window.SEAGULL_CONFIG = {"socialApiUrl":"https://social.test","auth":{"mode":"cognito","issuer":"https://cognito.test","clientId":"client"}}"#, contentType: "text/javascript")
            case "/me": return .json(#"{"identity":{"user_id":"owner","provider":"cognito","subject":"sub","email":"owner@example.com"}}"#)
            case "/agent-network/messages": return .json(#"{"message":{"message_id":"m1","thread_id":"t1","content_inline":"hello"},"message_id":"m1","thread_id":"t1"}"#)
            default: return .json(#"{"items":[],"usage":[],"entries":[],"balance":{"available_credits":0},"ok":true}"#)
            }
        }
        let store = MobileAppStore(websiteURL: "https://sea.test", session: session, credentials: credentials)
        await store.prepare()
        let gull = CloudGull(agentID: "g1", ownerUserID: "owner", handle: "@mine:gulls.ai", displayName: "Mine", bio: nil, capabilities: [], relationshipPosture: "open", approvalRequiredFor: [], allowedUseTerms: [], contactExplanation: nil, protocols: [], status: "active", nodeID: nil, deliveryMode: "cloud", lastSeenAt: nil, createdAt: nil, updatedAt: nil)
        let response = try await store.send(sender: gull, recipientHandle: "@other:gulls.ai", content: "hello", idempotencyKey: "idem-1")
        XCTAssertEqual(response.message?.senderHandle, gull.handle)
        let request = try XCTUnwrap(recorder.requests.first { $0.url?.path == "/agent-network/messages" })
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: try XCTUnwrap(request.httpBody)) as? [String: Any])
        XCTAssertEqual(json["owner_user_id"] as? String, "owner")
        XCTAssertEqual(json["sender_handle"] as? String, "@mine:gulls.ai")
        XCTAssertEqual((json["recipient_handles"] as? [String])?.first, "@other:gulls.ai")
        XCTAssertEqual(json["idempotency_key"] as? String, "idem-1")
        XCTAssertEqual(store.sentByHandle[gull.handle]?.last?.threadID, "t1")
        XCTAssertEqual(store.messagesByThreadID["t1"]?.last?.senderHandle, gull.handle)
    }

    func testTemporaryRestoreFailurePreservesCredentialsAndCanRetry() async {
        let credentials = TestCredentials(session: MobileStoredSession(accessToken: "valid", refreshToken: "refresh", idToken: nil, expiresAt: Date(timeIntervalSinceNow: 3600)))
        let session = makeSession { request in
            if request.url?.path == "/config.js" { return .json(Self.configuration, contentType: "text/javascript") }
            return .json(#"{"message":"Temporarily unavailable"}"#, status: 503)
        }
        let store = MobileAppStore(websiteURL: "https://sea.test", session: session, credentials: credentials)
        await store.prepare()
        XCTAssertNotNil(credentials.session)
        XCTAssertTrue(store.canRetryRestore)
        XCTAssertFalse(store.isSignedIn)
    }

    func testRejectedRefreshRemovesExpiredCredentials() async {
        let credentials = TestCredentials(session: MobileStoredSession(accessToken: "old", refreshToken: "invalid", idToken: nil, expiresAt: .distantPast))
        let session = makeSession { request in
            if request.url?.path == "/config.js" { return .json(Self.configuration, contentType: "text/javascript") }
            return .json(#"{"message":"Not authorized"}"#, status: 400)
        }
        let store = MobileAppStore(websiteURL: "https://sea.test", session: session, credentials: credentials)
        await store.prepare()
        XCTAssertNil(credentials.session)
        XCTAssertFalse(store.isSignedIn)
        XCTAssertFalse(store.canRetryRestore)
    }

    func testThreadRefreshRetainsOlderPagesAndDoesNotResetCursor() async throws {
        let credentials = TestCredentials(session: MobileStoredSession(accessToken: "valid", refreshToken: nil, idToken: nil, expiresAt: Date(timeIntervalSinceNow: 3600)))
        let session = makeSession { request in
            switch request.url?.path {
            case "/config.js": return .json(Self.configuration, contentType: "text/javascript")
            case "/me": return .json(#"{"identity":{"user_id":"owner","provider":"cognito","subject":"sub"}}"#)
            case "/agent-network/threads/thread-1":
                if request.url?.query?.contains("cursor=older") == true {
                    return .json(#"{"thread_id":"thread-1","messages":[{"message_id":"old","thread_id":"thread-1","created_at":"2026-10-01T10:00:00Z"}]}"#)
                }
                return .json(#"{"thread_id":"thread-1","messages":[{"message_id":"new","thread_id":"thread-1","created_at":"2026-10-02T10:00:00.123Z"}],"next_cursor":"older"}"#)
            default: return .json(#"{"items":[],"ok":true}"#)
            }
        }
        let store = MobileAppStore(websiteURL: "https://sea.test", session: session, credentials: credentials)
        await store.prepare()
        let gull = try XCTUnwrap(MobileAppStore.preview().ownedGulls.first)
        _ = try await store.loadThread("thread-1", for: gull)
        XCTAssertEqual(store.threadCursors["thread-1"], "older")
        _ = try await store.loadMoreThread("thread-1", for: gull)
        XCTAssertNil(store.threadCursors["thread-1"])
        _ = try await store.loadThread("thread-1", for: gull)
        XCTAssertEqual(store.messagesByThreadID["thread-1"]?.compactMap(\.messageID), ["old", "new"])
        XCTAssertNil(store.threadCursors["thread-1"])
    }

    private static let configuration = #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://social.test","auth":{"mode":"cognito","issuer":"https://cognito.test","clientId":"client"}}"#
}

private final class TestCredentials: MobileCredentialStore {
    var session: MobileStoredSession?
    init(session: MobileStoredSession?) { self.session = session }
    func read() throws -> MobileStoredSession? { session }
    func write(_ session: MobileStoredSession) throws { self.session = session }
    func delete() throws { session = nil }
}

private final class RequestRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [URLRequest] = []
    var requests: [URLRequest] { lock.lock(); defer { lock.unlock() }; return values }
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
        lock.lock(); values.append(recorded); lock.unlock()
    }
}

private func makeSession(handler: @escaping (URLRequest) -> StubResponse) -> URLSession {
    StubURLProtocol.handler = handler
    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [StubURLProtocol.self]
    return URLSession(configuration: configuration)
}

private struct StubResponse {
    let body: Data
    let contentType: String
    let status: Int
    static func json(_ value: String, contentType: String = "application/json", status: Int = 200) -> StubResponse { StubResponse(body: Data(value.utf8), contentType: contentType, status: status) }
}

private final class StubURLProtocol: URLProtocol {
    static var handler: ((URLRequest) -> StubResponse)?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let handler = Self.handler else { return }
        let value = handler(request)
        let response = HTTPURLResponse(url: request.url!, statusCode: value.status, httpVersion: nil, headerFields: ["Content-Type": value.contentType])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: value.body)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
