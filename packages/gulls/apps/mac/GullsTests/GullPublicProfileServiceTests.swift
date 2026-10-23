import Foundation
import XCTest
@testable import Gulls

final class GullPublicProfileServiceTests: XCTestCase {
    func testResolvesPublicCardWithoutAuthorization() async throws {
        let fixture = PublicProfileURLProtocol.self
        fixture.handler = { request in
            XCTAssertEqual(request.url?.path, "/agents/@atlas:northstar.example")
            XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
            return (200, Data(#"{"agent":{"agent_id":"agent-1","handle":"@atlas:northstar.example","display_name":"Atlas","capabilities":["Research"],"status":"active","updated_at":"2026-10-19T00:00:00Z","response_rules":{"private":"ignored"}}}"#.utf8))
        }
        let service = try GullPublicProfileService(messageHubURL: "https://hub.example.test", session: makeSession(fixture))
        let profile = try await service.resolve(handle: "@Atlas:Northstar.Example")
        XCTAssertEqual(profile.agentID, "agent-1")
        XCTAssertEqual(profile.handle, "@atlas:northstar.example")
        XCTAssertEqual(profile.displayName, "Atlas")
        XCTAssertEqual(profile.capabilities, ["Research"])
    }

    func testRejectsInvalidHandleBeforeMakingRequest() async throws {
        let fixture = PublicProfileURLProtocol.self
        fixture.handler = { _ in XCTFail("The service must not request an invalid handle"); return (500, Data()) }
        let service = try GullPublicProfileService(messageHubURL: "https://hub.example.test", session: makeSession(fixture))
        do {
            _ = try await service.resolve(handle: "../../private")
            XCTFail("expected invalid handle")
        } catch let error as GullPublicProfileServiceError {
            XCTAssertEqual(error, .invalidHandle)
        }
    }

    func testRejectsAProfileForAnotherHandle() async throws {
        let fixture = PublicProfileURLProtocol.self
        fixture.handler = { _ in
            (200, Data(#"{"agent":{"agent_id":"agent-2","handle":"@mira:fieldnotes.example","display_name":"Mira","capabilities":[],"status":"active"}}"#.utf8))
        }
        let service = try GullPublicProfileService(messageHubURL: "https://hub.example.test", session: makeSession(fixture))
        do {
            _ = try await service.resolve(handle: "@atlas:northstar.example")
            XCTFail("expected mismatched handle")
        } catch let error as GullPublicProfileServiceError {
            XCTAssertEqual(error, .mismatchedHandle)
        }
    }

    private func makeSession(_ fixture: URLProtocol.Type) -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [fixture]
        return URLSession(configuration: configuration)
    }
}

private final class PublicProfileURLProtocol: URLProtocol {
    static var handler: ((URLRequest) -> (Int, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let result = Self.handler?(request), let url = request.url else { return }
        let response = HTTPURLResponse(url: url, statusCode: result.0, httpVersion: nil,
                                       headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: result.1)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
