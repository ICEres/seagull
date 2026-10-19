import Foundation
import XCTest
@testable import Gulls

@MainActor
final class CloudAccountStoreTests: XCTestCase {
    func testEmailOTPFlowUsesCognitoPayloadCasingAndServerIdentity() async throws {
        let defaults = try temporaryDefaults()
        let token = jwt(sub: "jwt-sub", groups: ["admin"])
        let session = makeSession { request in
            switch request.url?.path {
            case "/config.js":
                return CloudAccountURLProtocol.json(200, #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test","messageApiUrl":"https://hub.example.test","aiProviderApiUrl":"https://ai.example.test","auth":{"mode":"cognito","issuer":"https://cognito.example.test/pool","clientId":"client-1"}};"#)
            case "/":
                let body = try! JSONSerialization.jsonObject(with: request.httpBody ?? Data()) as! [String: Any]
                XCTAssertEqual(request.value(forHTTPHeaderField: "X-Amz-Target"), "AWSCognitoIdentityProviderService.\(body["AuthFlow"] == nil ? "RespondToAuthChallenge" : "InitiateAuth")")
                if body["AuthFlow"] != nil {
                    XCTAssertEqual(body["ClientId"] as? String, "client-1")
                    XCTAssertEqual((body["AuthParameters"] as? [String: String])?["PREFERRED_CHALLENGE"], "EMAIL_OTP")
                    return CloudAccountURLProtocol.json(200, #"{"ChallengeName":"EMAIL_OTP","Session":"challenge-1"}"#)
                }
                XCTAssertEqual(body["ChallengeName"] as? String, "EMAIL_OTP")
                XCTAssertEqual((body["ChallengeResponses"] as? [String: String])?["EMAIL_OTP_CODE"], "123456")
                return CloudAccountURLProtocol.json(200, #"{"AuthenticationResult":{"AccessToken":"\#(token)","IdToken":"\#(token)","ExpiresIn":3600,"TokenType":"Bearer"}}"#)
            case "/me":
                XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer \(token)")
                return CloudAccountURLProtocol.json(200, #"{"identity":{"user_id":"actual-owner","provider":"cognito","subject":"cognito-sub","email":"owner@example.test","display_name":"Owner"}}"#)
            default:
                return CloudAccountURLProtocol.json(404, #"{"message":"unexpected route"}"#)
            }
        }
        let store = CloudAccountStore(defaults: defaults, session: session)
        store.websiteURL = "https://web.example.test"
        await store.loadConfiguration()
        store.email = "Owner@Example.Test"
        await store.beginSignIn()
        XCTAssertTrue(store.challengePending)
        store.code = "123456"
        await store.completeSignIn()

        XCTAssertTrue(store.isSignedIn)
        XCTAssertEqual(store.account?.userID, "actual-owner")
        XCTAssertEqual(store.userID, "actual-owner")
        XCTAssertTrue(store.isAdmin)
        XCTAssertFalse(defaults.dictionaryRepresentation().values.contains { ($0 as? String)?.contains(token) == true })
    }

    func testProviderRequestUsesSnakeCaseAndNeverStoresAPIKey() async throws {
        let defaults = try temporaryDefaults()
        let token = jwt(sub: "owner")
        let session = makeSession { request in
            switch request.url?.path {
            case "/config.js":
                return CloudAccountURLProtocol.json(200, #"window.SEAGULL_CONFIG = {"aiProviderApiUrl":"https://ai.example.test","auth":{"mode":"cognito","issuer":"https://cognito.example.test/pool","clientId":"client-1"}};"#)
            case "/admin/ai-providers/openai":
                let body = try! JSONSerialization.jsonObject(with: request.httpBody ?? Data()) as! [String: Any]
                XCTAssertEqual(body["admin_actor_id"] as? String, "owner")
                XCTAssertEqual(body["api_key"] as? String, "sk-test-secret")
                XCTAssertNil(body["apiKey"])
                return CloudAccountURLProtocol.json(200, #"{"provider_config":{"provider_config_id":"pc-1","provider":"openai","enabled":true,"allowed_models":["gpt-5.5"],"secret_ref":"secret/ref","region":"global"}}"#)
            default:
                return CloudAccountURLProtocol.json(404, #"{"message":"unexpected route"}"#)
            }
        }
        let store = CloudAccountStore(defaults: defaults, session: session)
        store.websiteURL = "https://web.example.test"
        await store.loadConfiguration()
        store.setTestSession(accessToken: token, userID: "owner", admin: true)
        try await store.saveProvider(CloudProviderDraft(provider: "openai", enabled: true, allowedModels: ["gpt-5.5"], apiKey: "sk-test-secret", secretRef: nil, region: "global", reason: "test"))
        XCTAssertFalse(defaults.dictionaryRepresentation().values.contains { String(describing: $0).contains("sk-test-secret") })
    }

    func testLogoutWinsAgainstAnInFlightGullRefresh() async throws {
        let defaults = try temporaryDefaults()
        let started = expectation(description: "profiles request started")
        let release = DispatchSemaphore(value: 0)
        let session = makeSession { request in
            if request.url?.path == "/config.js" {
                return CloudAccountURLProtocol.json(200, #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test"};"#)
            }
            if request.url?.path == "/profiles" {
                started.fulfill()
                release.wait()
                return CloudAccountURLProtocol.json(200, #"{"items":[{"agent_id":"g-1","owner_user_id":"owner","handle":"@test:gulls.ai","capabilities":[],"relationship_posture":"needs_approval","approval_required_for":[],"allowed_use_terms":[],"protocols":[],"status":"active"}]}"#)
            }
            return CloudAccountURLProtocol.json(404, #"{"message":"unexpected route"}"#)
        }
        let store = CloudAccountStore(defaults: defaults, session: session)
        store.websiteURL = "https://web.example.test"
        await store.loadConfiguration()
        store.setTestSession(accessToken: jwt(sub: "owner"), userID: "owner", admin: false)
        let refresh = Task { await store.refreshGulls() }
        await fulfillment(of: [started], timeout: 2)
        store.signOut()
        release.signal()
        await refresh.value
        XCTAssertTrue(store.ownedGulls.isEmpty)
    }

    func testLogoutAndNewSessionWinsAgainstAnInFlightGullUpdate() async throws {
        let defaults = try temporaryDefaults()
        let started = expectation(description: "profile update started")
        let release = DispatchSemaphore(value: 0)
        let session = makeSession { request in
            if request.url?.path == "/config.js" {
                return CloudAccountURLProtocol.json(200, #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test"};"#)
            }
            if request.url?.path == "/profiles/@test:gulls.ai" {
                started.fulfill()
                release.wait()
                return CloudAccountURLProtocol.json(200, #"{"profile":{"agent_id":"g-1","owner_user_id":"old-owner","handle":"@test:gulls.ai","display_name":"Old session","capabilities":[],"relationship_posture":"needs_approval","approval_required_for":[],"allowed_use_terms":[],"protocols":[],"status":"active"}}"#)
            }
            return CloudAccountURLProtocol.json(404, #"{"message":"unexpected route"}"#)
        }
        let store = CloudAccountStore(defaults: defaults, session: session)
        store.websiteURL = "https://web.example.test"
        await store.loadConfiguration()
        store.setTestSession(accessToken: jwt(sub: "old-owner"), userID: "old-owner", admin: false)
        let gull = CloudGull(agentID: "g-1", ownerUserID: "old-owner", handle: "@test:gulls.ai",
                             displayName: "Original", bio: nil, capabilities: [], relationshipPosture: "needs_approval",
                             approvalRequiredFor: [], allowedUseTerms: [], contactExplanation: nil, protocols: [],
                             status: "active", nodeID: nil, deliveryMode: nil, lastSeenAt: nil, createdAt: nil, updatedAt: nil)

        let update = Task { () -> Error? in
            do {
                try await store.updateGull(gull, displayName: "Old session", bio: nil)
                return nil
            } catch {
                return error
            }
        }
        await fulfillment(of: [started], timeout: 2)
        store.signOut()
        store.setTestSession(accessToken: jwt(sub: "new-owner"), userID: "new-owner", admin: false)
        release.signal()

        let error = await update.value
        XCTAssertTrue(error is CancellationError)
        XCTAssertTrue(store.ownedGulls.isEmpty)
        XCTAssertEqual(store.userID, "new-owner")
    }

    func testChangingWebsiteInvalidatesRuntimeAndSession() async throws {
        let defaults = try temporaryDefaults()
        let store = CloudAccountStore(defaults: defaults)
        store.setTestSession(accessToken: jwt(sub: "owner"), userID: "owner", admin: false)
        XCTAssertTrue(store.isSignedIn)
        store.websiteURL = "https://another.example.test"
        XCTAssertFalse(store.isSignedIn)
        XCTAssertNil(store.runtime)
        XCTAssertNil(store.userID)
    }

    func testUsageRefreshReportsRepeatedFailuresAndKeepsLastBalance() async throws {
        let defaults = try temporaryDefaults()
        var usageRequests = 0
        let session = makeSession { request in
            if request.url?.path == "/config.js" {
                return CloudAccountURLProtocol.json(200, #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test"};"#)
            }
            if request.url?.path == "/me/ai-usage" {
                usageRequests += 1
                if usageRequests == 1 {
                    return CloudAccountURLProtocol.json(200, #"{"owner_user_id":"owner","balance":{"owner_user_id":"owner","available_credits":973},"usage":[],"entries":[]}"#)
                }
                return CloudAccountURLProtocol.json(503, #"{"message":"Usage is temporarily unavailable"}"#)
            }
            return CloudAccountURLProtocol.json(404, #"{"message":"unexpected route"}"#)
        }
        let store = CloudAccountStore(defaults: defaults, session: session)
        store.websiteURL = "https://web.example.test"
        await store.loadConfiguration()
        store.setTestSession(accessToken: jwt(sub: "owner"), userID: "owner", admin: false)

        let loaded = await store.refreshAIUsage()
        XCTAssertTrue(loaded)
        for _ in 0..<2 {
            let refreshed = await store.refreshAIUsage()
            XCTAssertFalse(refreshed)
            XCTAssertEqual(store.aiUsage?.balance.availableCredits, 973)
            XCTAssertNotNil(store.error)
        }
        store.signOut()
        XCTAssertNil(store.error)
    }

    func testLogoutDuringIdentityLookupDoesNotPublishAccount() async throws {
        let defaults = try temporaryDefaults()
        let started = expectation(description: "identity lookup started")
        let release = DispatchSemaphore(value: 0)
        let token = jwt(sub: "jwt-sub")
        let session = makeSession { request in
            switch request.url?.path {
            case "/config.js":
                return CloudAccountURLProtocol.json(200, #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test","auth":{"mode":"cognito","issuer":"https://cognito.example.test/pool","clientId":"client-1"}};"#)
            case "/":
                let body = (try? JSONSerialization.jsonObject(with: request.httpBody ?? Data())) as? [String: Any]
                if body?["AuthFlow"] != nil { return CloudAccountURLProtocol.json(200, #"{"ChallengeName":"EMAIL_OTP","Session":"challenge-1"}"#) }
                return CloudAccountURLProtocol.json(200, "{\"AuthenticationResult\":{\"AccessToken\":\"\(token)\",\"IdToken\":\"\(token)\",\"ExpiresIn\":3600}}")
            case "/me":
                started.fulfill()
                release.wait()
                return CloudAccountURLProtocol.json(200, #"{"identity":{"user_id":"actual-owner","provider":"cognito","subject":"subject"}}"#)
            default:
                return CloudAccountURLProtocol.json(404, #"{"message":"unexpected route"}"#)
            }
        }
        let store = CloudAccountStore(defaults: defaults, session: session)
        store.websiteURL = "https://web.example.test"
        await store.loadConfiguration()
        store.email = "owner@example.test"
        await store.beginSignIn()
        store.code = "123456"
        let completion = Task { await store.completeSignIn() }
        await fulfillment(of: [started], timeout: 2)
        store.signOut()
        release.signal()
        await completion.value
        XCTAssertFalse(store.isSignedIn)
        XCTAssertNil(store.account)
        XCTAssertNil(store.userID)
    }

    func testIdentityFailureDoesNotClaimSignedIn() async throws {
        let defaults = try temporaryDefaults()
        let token = jwt(sub: "jwt-sub")
        let session = makeSession { request in
            switch request.url?.path {
            case "/config.js":
                return CloudAccountURLProtocol.json(200, #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test","auth":{"mode":"cognito","issuer":"https://cognito.example.test/pool","clientId":"client-1"}};"#)
            case "/":
                let body = (try? JSONSerialization.jsonObject(with: request.httpBody ?? Data())) as? [String: Any]
                if body?["AuthFlow"] != nil { return CloudAccountURLProtocol.json(200, #"{"ChallengeName":"EMAIL_OTP","Session":"challenge-1"}"#) }
                return CloudAccountURLProtocol.json(200, "{\"AuthenticationResult\":{\"AccessToken\":\"\(token)\",\"IdToken\":\"\(token)\",\"ExpiresIn\":3600}}")
            case "/me":
                return CloudAccountURLProtocol.json(401, #"{"message":"identity unavailable"}"#)
            default:
                return CloudAccountURLProtocol.json(404, #"{"message":"unexpected route"}"#)
            }
        }
        let store = CloudAccountStore(defaults: defaults, session: session)
        store.websiteURL = "https://web.example.test"
        await store.loadConfiguration()
        store.email = "owner@example.test"
        await store.beginSignIn()
        store.code = "123456"
        await store.completeSignIn()
        XCTAssertFalse(store.isSignedIn)
        XCTAssertNil(store.account)
        XCTAssertNotNil(store.error)
    }

    func testRepresentativeSnakeCaseModelsDecodeThroughCloudAPI() async throws {
        let defaults = try temporaryDefaults()
        let session = makeSession { request in
            switch request.url?.path {
            case "/config.js":
                return CloudAccountURLProtocol.json(200, #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test"};"#)
            case "/profiles":
                return CloudAccountURLProtocol.json(200, #"{"items":[{"agent_id":"g-1","owner_user_id":"owner","handle":"@test:gulls.ai","display_name":"Test Gull","capabilities":["research"],"relationship_posture":"needs_approval","approval_required_for":[],"allowed_use_terms":[],"protocols":["seagull"],"status":"active","node_id":"node-1","last_seen_at":"2026-10-18T00:00:00Z"}]}"#)
            case "/profiles/@test:gulls.ai/runtime":
                return CloudAccountURLProtocol.json(200, #"{"runtime":{"mode":"local","node_id":"node-1","connected":true,"last_seen_at":"2026-10-18T00:00:00Z"}}"#)
            case "/profiles/@test:gulls.ai/local-pair-tokens":
                return CloudAccountURLProtocol.json(200, #"{"pair_token":{"pair_token":"pair-short","node_id":"node-1","owner_user_id":"owner","expires_at":"2026-10-18T00:10:00Z"},"social_api_url":"https://api.example.test"}"#)
            default:
                return CloudAccountURLProtocol.json(404, #"{"message":"unexpected route"}"#)
            }
        }
        let store = CloudAccountStore(defaults: defaults, session: session)
        store.websiteURL = "https://web.example.test"
        await store.loadConfiguration()
        store.setTestSession(accessToken: jwt(sub: "owner"), userID: "owner", admin: false)
        await store.refreshGulls()
        let gull = try XCTUnwrap(store.ownedGulls.first)
        let runtime = try await store.loadRuntime(for: gull)
        let pair = try await store.createLocalPairToken(for: gull)
        XCTAssertEqual(gull.agentID, "g-1")
        XCTAssertEqual(runtime.nodeID, "node-1")
        XCTAssertEqual(pair.pairToken, "pair-short")
    }

    func testSharedCLISessionIsVerifiedBeforeImportAndFollowsLogout() async throws {
        let defaults = try temporaryDefaults()
        let file = try temporarySharedFile()
        let token = jwt(sub: "cli-owner", groups: ["admin"])
        var identityRequests = 0
        let session = makeSession { request in
            if request.url?.path == "/config.js" {
                return CloudAccountURLProtocol.json(200, #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test"};"#)
            }
            XCTAssertEqual(request.url?.path, "/me")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer \(token)")
            identityRequests += 1
            return CloudAccountURLProtocol.json(200, #"{"identity":{"user_id":"verified-owner","provider":"cognito","subject":"subject","email":"owner@example.test","display_name":"Owner"}}"#)
        }
        let store = CloudAccountStore(defaults: defaults, session: session, sharedSessionURL: file.url)
        try file.write(sharedSession(token: token))
        XCTAssertFalse(store.isSignedIn)

        await store.synchronizeSharedSession()
        XCTAssertTrue(store.isSignedIn)
        XCTAssertEqual(store.userID, "verified-owner")
        XCTAssertTrue(store.isAdmin)
        await store.synchronizeSharedSession()
        XCTAssertEqual(identityRequests, 1)

        try file.remove(for: store.websiteURL)
        await store.synchronizeSharedSession()
        XCTAssertFalse(store.isSignedIn)
        XCTAssertNil(store.account)
    }

    func testRejectedSharedIdentityDoesNotSignIn() async throws {
        let file = try temporarySharedFile()
        let session = makeSession { request in
            if request.url?.path == "/config.js" {
                return CloudAccountURLProtocol.json(200, #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test"};"#)
            }
            return CloudAccountURLProtocol.json(401, #"{"message":"Unauthorized"}"#)
        }
        let store = CloudAccountStore(defaults: try temporaryDefaults(), session: session, sharedSessionURL: file.url)
        try file.write(sharedSession(token: jwt(sub: "rejected")))
        await store.synchronizeSharedSession()
        XCTAssertFalse(store.isSignedIn)
        XCTAssertNil(store.account)
        XCTAssertNotNil(store.error)
    }

    func testLogoutDuringSharedIdentityLookupCannotRestoreSession() async throws {
        let file = try temporarySharedFile()
        let started = expectation(description: "shared identity lookup started")
        let release = DispatchSemaphore(value: 0)
        let session = makeSession { request in
            if request.url?.path == "/config.js" {
                return CloudAccountURLProtocol.json(200, #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test"};"#)
            }
            started.fulfill()
            release.wait()
            return CloudAccountURLProtocol.json(200, #"{"identity":{"user_id":"owner","provider":"cognito","subject":"subject"}}"#)
        }
        let store = CloudAccountStore(defaults: try temporaryDefaults(), session: session, sharedSessionURL: file.url)
        try file.write(sharedSession(token: jwt(sub: "owner")))
        let restore = Task { await store.synchronizeSharedSession() }
        await fulfillment(of: [started], timeout: 2)
        store.signOut()
        release.signal()
        await restore.value
        XCTAssertFalse(store.isSignedIn)
        XCTAssertNil(store.account)
        XCTAssertNil(try file.read(for: store.websiteURL))
    }

    func testExistingNativeAccountIsNotReplacedByOldCLISession() async throws {
        let file = try temporarySharedFile()
        let session = makeSession { _ in
            XCTFail("A valid native account must not import a stale CLI session")
            return CloudAccountURLProtocol.json(500, "{}")
        }
        let store = CloudAccountStore(defaults: try temporaryDefaults(), session: session, sharedSessionURL: file.url)
        store.setTestSession(accessToken: jwt(sub: "native"), userID: "native", admin: false)
        try file.write(sharedSession(token: jwt(sub: "old-cli")))
        await store.synchronizeSharedSession()
        store.cancelBrowserSignIn()
        XCTAssertTrue(store.isSignedIn)
        XCTAssertEqual(store.userID, "native")
    }

    func testExpiredSharedSessionDoesNotCallCloudAPI() async throws {
        let file = try temporarySharedFile()
        let session = makeSession { _ in
            XCTFail("Expired account sessions must not be transmitted")
            return CloudAccountURLProtocol.json(500, "{}")
        }
        let store = CloudAccountStore(defaults: try temporaryDefaults(), session: session, sharedSessionURL: file.url)
        try file.write(SharedCloudSession(version: 1, websiteURL: store.websiteURL,
                                         accessToken: jwt(sub: "expired"), expiresAt: 1))
        await store.synchronizeSharedSession()
        XCTAssertFalse(store.isSignedIn)
    }

    func testCancellingBrowserSignInDuringVerificationDoesNotPublishSharedSession() async throws {
        let file = try temporarySharedFile()
        let source = file.url.deletingLastPathComponent().appendingPathComponent("browser-session.json")
        try JSONEncoder().encode(sharedSession(token: jwt(sub: "browser"))).write(to: source)
        let executable = source.deletingLastPathComponent().appendingPathComponent("fake-gulls")
        try "#!/bin/bash\ncp \"\(source.path)\" \"$6\"\nchmod 600 \"$6\"\nprintf '{}\\n'\n".write(to: executable, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
        let started = expectation(description: "browser identity lookup started")
        let release = DispatchSemaphore(value: 0)
        let session = makeSession { request in
            if request.url?.path == "/config.js" {
                return CloudAccountURLProtocol.json(200, #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test"};"#)
            }
            started.fulfill()
            release.wait()
            return CloudAccountURLProtocol.json(200, #"{"identity":{"user_id":"browser","provider":"cognito","subject":"subject"}}"#)
        }
        let store = CloudAccountStore(defaults: try temporaryDefaults(), session: session,
                                      cli: GullsCLI(executableURL: executable), sharedSessionURL: file.url)
        store.startBrowserSignIn()
        await fulfillment(of: [started], timeout: 3)
        store.cancelBrowserSignIn()
        release.signal()
        for _ in 0..<100 where store.isRestoringSharedSession { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertFalse(store.isBrowserSignInPending)
        XCTAssertFalse(store.isRestoringSharedSession)
        XCTAssertFalse(store.isSignedIn)
        XCTAssertNil(try file.read(for: store.websiteURL))
    }

    private func temporarySharedFile() throws -> SharedCloudSessionFile {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("CloudSessionTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                               attributes: [.posixPermissions: 0o700])
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        return SharedCloudSessionFile(url: directory.appendingPathComponent("account.json"))
    }

    private func sharedSession(token: String) -> SharedCloudSession {
        SharedCloudSession(version: 1, websiteURL: "https://sea.gulls.ai", accessToken: token,
                           expiresAt: Date().addingTimeInterval(3600).timeIntervalSince1970 * 1000)
    }

    private func makeSession(handler: @escaping (URLRequest) -> CloudAccountURLProtocol.Result) -> URLSession {
        CloudAccountURLProtocol.handler = handler
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [CloudAccountURLProtocol.self]
        return URLSession(configuration: configuration)
    }

    private func temporaryDefaults() throws -> UserDefaults {
        let suite = "CloudAccountStoreTests.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suite) else { throw XCTSkip("Could not create isolated defaults") }
        addTeardownBlock { defaults.removePersistentDomain(forName: suite) }
        return defaults
    }

    private func jwt(sub: String, groups: [String] = []) -> String {
        func part(_ object: [String: Any]) -> String {
            let data = try! JSONSerialization.data(withJSONObject: object)
            return data.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        }
        return "\(part(["alg": "none"])).\(part(["sub": sub, "cognito:groups": groups])).signature"
    }
}

private final class CloudAccountURLProtocol: URLProtocol {
    struct Result { var status: Int; var body: Data }
    static var handler: ((URLRequest) -> Result)?

    static func json(_ status: Int, _ body: String) -> Result { Result(status: status, body: Data(body.utf8)) }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var capturedRequest = request
        if capturedRequest.httpBody == nil, let stream = capturedRequest.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var body = Data()
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let count = stream.read(&buffer, maxLength: buffer.count)
                guard count > 0 else { break }
                body.append(contentsOf: buffer.prefix(count))
            }
            capturedRequest.httpBody = body
        }
        guard let result = Self.handler?(capturedRequest), let url = request.url,
              let response = HTTPURLResponse(url: url, statusCode: result.status, httpVersion: nil, headerFields: ["Content-Type": "application/json"]) else { return }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: result.body)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
