import XCTest
@testable import Gulls

@MainActor
final class LocalConnectionsTests: XCTestCase {
    private final class MemoryTokenStore: GullsTokenStore {
        var values: [String: String] = [:]
        var legacy: String?
        var rejectWrites = false

        func token(for profileID: String) -> String? { values[profileID] }
        func legacyToken() -> String? { legacy }
        @discardableResult
        func setToken(_ token: String, for profileID: String) -> Bool {
            guard !rejectWrites else { return false }
            if token.isEmpty { values.removeValue(forKey: profileID) } else { values[profileID] = token }
            return true
        }
    }

    private final class StubURLProtocol: URLProtocol {
        static var body = Data()
        static var status = 200
        static var delay: TimeInterval = 0
        static var redirect = false

        override class func canInit(with request: URLRequest) -> Bool { true }
        override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
        override func startLoading() {
            let response = HTTPURLResponse(
                url: request.url!, statusCode: Self.status, httpVersion: nil,
                headerFields: Self.redirect
                    ? ["Location": "https://redirected.example/pair"]
                    : ["Content-Type": "application/json"]
            )!
            let send = {
                self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
                self.client?.urlProtocol(self, didLoad: Self.body)
                self.client?.urlProtocolDidFinishLoading(self)
            }
            if Self.delay == 0 { send() } else { DispatchQueue.main.asyncAfter(deadline: .now() + Self.delay, execute: send) }
        }
        override func stopLoading() {}
    }

    private func suite() -> UserDefaults {
        let name = "local-connections-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        addTeardownBlock { defaults.removePersistentDomain(forName: name) }
        return defaults
    }

    func testProfilesNamespaceDefaultsAndCredentials() {
        let defaults = suite()
        let tokens = MemoryTokenStore()
        let first = GullsConfig(profileID: "one", defaults: defaults, tokenStore: tokens)
        let second = GullsConfig(profileID: "two", defaults: defaults, tokenStore: tokens)

        first.agentHandle = "@one:gulls.ai"
        second.agentHandle = "@two:gulls.ai"
        first.token = "sga_one"
        second.token = "sga_two"

        let reloadedFirst = GullsConfig(profileID: "one", defaults: defaults, tokenStore: tokens)
        let reloadedSecond = GullsConfig(profileID: "two", defaults: defaults, tokenStore: tokens)
        XCTAssertEqual(reloadedFirst.agentHandle, "@one:gulls.ai")
        XCTAssertEqual(reloadedSecond.agentHandle, "@two:gulls.ai")
        XCTAssertEqual(reloadedFirst.token, "sga_one")
        XCTAssertEqual(reloadedSecond.token, "sga_two")
        XCTAssertNotEqual(reloadedFirst.contextDir, reloadedSecond.contextDir)
    }

    func testLegacyDefaultTokenIsReadUntilExplicitlyMigrated() {
        let defaults = suite()
        let tokens = MemoryTokenStore()
        tokens.legacy = "legacy-token"

        let imported = GullsConfig(defaults: defaults, tokenStore: tokens)
        XCTAssertEqual(imported.token, "legacy-token")
        imported.token = ""

        let reloaded = GullsConfig(defaults: defaults, tokenStore: tokens)
        XCTAssertEqual(reloaded.token, "", "clearing a migrated token must not resurrect the legacy item")
    }

    func testStoreAddsSelectsAndRemovesWithoutCrossProfileState() {
        let defaults = suite()
        let tokens = MemoryTokenStore()
        let store = LocalConnectionsStore(defaults: defaults, tokenStore: tokens)
        let added = store.add(displayName: "Second Gull")
        XCTAssertEqual(store.selectedProfileID, added.profileID)
        XCTAssertEqual(store.selectedConfig?.displayName, "Second Gull")
        added.agentHandle = "@second:gulls.ai"
        XCTAssertTrue(store.select(profileID: GullsConfig.defaultProfileID) != nil)
        XCTAssertEqual(store.selectedConfig?.agentHandle, "")
        XCTAssertTrue(store.remove(profileID: added.profileID))
        XCTAssertNil(store.profiles.first(where: { $0.profileID == added.profileID }))
    }

    func testInboxPrefersPairedGullOverLegacyProfileEvenWhileOffline() {
        let defaults = suite()
        let tokens = MemoryTokenStore()
        let connections = LocalConnectionsStore(defaults: defaults, tokenStore: tokens)
        let legacy = connections.selectedConfig!
        legacy.apiURL = "http://localhost:8200"
        legacy.agentHandle = "@worker:gulls.ai"
        let paired = connections.add(displayName: "Test")
        paired.apiURL = "https://message.example"
        paired.agentHandle = "@test:gulls.ai"
        paired.socialAPIURL = "https://social.example"
        paired.nodeID = "node_test"
        paired.token = "sga_test"
        paired.monitoringEnabled = false
        connections.select(profileID: legacy.profileID)

        XCTAssertEqual(connections.preferredInboxProfileID, paired.profileID)
        let restored = LocalConnectionsStore(defaults: defaults, tokenStore: tokens)
        XCTAssertEqual(restored.preferredInboxProfileID, paired.profileID)
        XCTAssertEqual(restored.selectedProfileID, legacy.profileID, "choosing a default scope must not mutate the connection selection")
    }

    func testDelegatedReplyDeliveryPreferenceIsPerProfileAndDefaultsToAutomatic() {
        let defaults = suite()
        let tokens = MemoryTokenStore()
        let first = GullsConfig(profileID: "first", defaults: defaults, tokenStore: tokens)
        let second = GullsConfig(profileID: "second", defaults: defaults, tokenStore: tokens)

        XCTAssertTrue(first.sendRepliesAutomatically)
        XCTAssertTrue(second.sendRepliesAutomatically)
        first.sendRepliesAutomatically = false

        XCTAssertFalse(first.sendRepliesAutomatically)
        XCTAssertTrue(second.sendRepliesAutomatically)
        XCTAssertFalse(GullsConfig(profileID: "first", defaults: defaults, tokenStore: tokens).sendRepliesAutomatically)
    }

    func testInboxPreservesSelectedPairedGullAcrossReload() {
        let defaults = suite()
        let tokens = MemoryTokenStore()
        let connections = LocalConnectionsStore(defaults: defaults, tokenStore: tokens)
        let first = connections.add(displayName: "First")
        let second = connections.add(displayName: "Second")
        for config in [first, second] {
            config.apiURL = "https://message.example"
            config.agentHandle = "@\(config.displayName.lowercased()):gulls.ai"
            config.socialAPIURL = "https://social.example"
            config.nodeID = "node_\(config.profileID)"
            config.token = "sga_test"
        }
        connections.select(profileID: first.profileID)

        let restored = LocalConnectionsStore(defaults: defaults, tokenStore: tokens)
        XCTAssertEqual(restored.preferredInboxProfileID, first.profileID)
    }

    func testInboxFallsBackToConfiguredProfilesWithoutPairing() {
        let connections = LocalConnectionsStore(defaults: suite(), tokenStore: MemoryTokenStore())
        XCTAssertNil(connections.preferredInboxProfileID)
        let first = connections.selectedConfig!
        first.apiURL = "http://localhost:8200"
        first.agentHandle = "@first:gulls.ai"
        let second = connections.add()
        XCTAssertEqual(connections.preferredInboxProfileID, first.profileID)
        second.apiURL = "http://localhost:8300"
        second.agentHandle = "@second:gulls.ai"
        XCTAssertEqual(connections.preferredInboxProfileID, second.profileID)
    }

    func testMonitoringPauseAndSuspendHaveDifferentPersistenceSemantics() {
        let defaults = suite()
        let config = GullsConfig(defaults: defaults, tokenStore: MemoryTokenStore())
        let store = InboxStore(cli: nil, config: config, notifier: Notifier())

        XCTAssertTrue(config.monitoringEnabled)
        store.stopMonitoring()
        XCTAssertFalse(config.monitoringEnabled)
        store.monitoringEnabled = true
        store.suspendMonitoring()
        XCTAssertTrue(config.monitoringEnabled)
    }

    func testPairValidatesAndStoresOnlyAValidRuntimeCredential() async throws {
        let defaults = suite()
        let tokens = MemoryTokenStore()
        let store = LocalConnectionsStore(defaults: defaults, tokenStore: tokens)
        let config = store.selectedConfig!
        let sessionConfig = URLSessionConfiguration.ephemeral
        sessionConfig.protocolClasses = [StubURLProtocol.self]
        let session = URLSession(configuration: sessionConfig)
        addTeardownBlock { session.invalidateAndCancel() }
        StubURLProtocol.status = 200
        StubURLProtocol.delay = 0
        StubURLProtocol.redirect = false
        StubURLProtocol.body = Data(#"{"api_url":"https://message.example","social_api_url":"https://social.example","agent_handle":"@paired:gulls.ai","node_id":"node_1","token":"sga_runtime"}"#.utf8)

        let result = try await store.pair(
            profileID: config.profileID,
            socialAPIURL: "https://social.example",
            pairingToken: "one-time",
            expectedHandle: "@paired:gulls.ai",
            session: session
        )
        XCTAssertEqual(result.agentHandle, "@paired:gulls.ai")
        XCTAssertEqual(config.token, "sga_runtime")
        XCTAssertEqual(tokens.values[config.profileID], "sga_runtime")
    }

    func testPairRejectsInsecureEndpointMismatchedHandleAndCredentialFailure() async throws {
        let defaults = suite()
        let tokens = MemoryTokenStore()
        let store = LocalConnectionsStore(defaults: defaults, tokenStore: tokens)
        let config = store.selectedConfig!
        let sessionConfig = URLSessionConfiguration.ephemeral
        sessionConfig.protocolClasses = [StubURLProtocol.self]
        let session = URLSession(configuration: sessionConfig)
        addTeardownBlock { session.invalidateAndCancel() }
        StubURLProtocol.status = 200
        StubURLProtocol.redirect = false
        StubURLProtocol.body = Data(#"{"api_url":"https://message.example","social_api_url":"https://social.example","agent_handle":"@other:gulls.ai","node_id":"node_1","token":"sga_runtime"}"#.utf8)

        do {
            _ = try await store.pair(profileID: config.profileID, socialAPIURL: "http://public.example", pairingToken: "x", session: session)
            XCTFail("expected insecure endpoint rejection")
        } catch let error as LocalConnectionsStore.PairError {
            XCTAssertEqual(error.localizedDescription, "Pairing server must use HTTPS; HTTP is allowed only for loopback development.")
        }
        do {
            _ = try await store.pair(profileID: config.profileID, socialAPIURL: "https://social.example", pairingToken: "x", expectedHandle: "@expected:gulls.ai", session: session)
            XCTFail("expected target mismatch")
        } catch let error as LocalConnectionsStore.PairError {
            guard case .invalidResponse = error else { return XCTFail("unexpected error: \(error)") }
        }
        tokens.rejectWrites = true
        StubURLProtocol.body = Data(#"{"api_url":"https://message.example","social_api_url":"https://social.example","agent_handle":"@other:gulls.ai","node_id":"node_1","token":"sga_runtime"}"#.utf8)
        do {
            _ = try await store.pair(profileID: config.profileID, socialAPIURL: "https://social.example", pairingToken: "x", session: session)
            XCTFail("expected credential failure")
        } catch let error as LocalConnectionsStore.PairError {
            guard case .credentialStoreUnavailable = error else { return XCTFail("unexpected error: \(error)") }
        }
    }

    func testPairDoesNotApplyResultAfterProfileRemoval() async throws {
        let defaults = suite()
        let tokens = MemoryTokenStore()
        let store = LocalConnectionsStore(defaults: defaults, tokenStore: tokens)
        let config = store.selectedConfig!
        let sessionConfig = URLSessionConfiguration.ephemeral
        sessionConfig.protocolClasses = [StubURLProtocol.self]
        let session = URLSession(configuration: sessionConfig)
        addTeardownBlock { session.invalidateAndCancel() }
        StubURLProtocol.status = 200
        StubURLProtocol.redirect = false
        StubURLProtocol.delay = 0.05
        StubURLProtocol.body = Data(#"{"api_url":"https://message.example","social_api_url":"https://social.example","agent_handle":"@paired:gulls.ai","node_id":"node_1","token":"sga_runtime"}"#.utf8)

        XCTAssertTrue(store.remove(profileID: config.profileID) == false, "the default profile remains a safe registry anchor")
        // Remove a non-default profile, which is the real in-flight removal case.
        let added = store.add(displayName: "Pending")
        let pendingAdded = Task {
            try await store.pair(profileID: added.profileID, socialAPIURL: "https://social.example", pairingToken: "x", session: session)
        }
        XCTAssertTrue(store.remove(profileID: added.profileID))
        do {
            _ = try await pendingAdded.value
            XCTFail("expected removed-profile failure")
        } catch let error as LocalConnectionsStore.PairError {
            guard case .profileRemoved = error else { return XCTFail("unexpected error: \(error)") }
        }
        StubURLProtocol.delay = 0
    }

    func testPairDoesNotForwardTokenAcrossRedirect() async throws {
        let defaults = suite()
        let tokens = MemoryTokenStore()
        let store = LocalConnectionsStore(defaults: defaults, tokenStore: tokens)
        let profileID = store.selectedConfig!.profileID
        let sessionConfig = URLSessionConfiguration.ephemeral
        sessionConfig.protocolClasses = [StubURLProtocol.self]
        let session = URLSession(configuration: sessionConfig)
        addTeardownBlock { session.invalidateAndCancel() }
        StubURLProtocol.redirect = true
        StubURLProtocol.status = 302
        StubURLProtocol.delay = 0

        do {
            _ = try await store.pair(
                profileID: profileID,
                socialAPIURL: "https://social.example",
                pairingToken: "one-time",
                session: session
            )
            XCTFail("expected the redirect to be rejected")
        } catch let error as LocalConnectionsStore.PairError {
            guard case .rejected(302) = error else { return XCTFail("unexpected error: \(error)") }
        }
        XCTAssertNil(tokens.values[profileID])
        StubURLProtocol.redirect = false
    }
}
