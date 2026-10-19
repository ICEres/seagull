import Foundation
import XCTest
@testable import Gulls

final class CloudAPITests: XCTestCase {
    func testRequiresHTTPSExceptLoopback() throws {
        XCTAssertThrowsError(try CloudAPI(baseURL: "http://api.example.test", accessToken: "")) { XCTAssertEqual($0 as? CloudAPIError, .insecureURL) }
        XCTAssertNoThrow(try CloudAPI(baseURL: "http://localhost:8300", accessToken: ""))
    }

    func testConfigParserOnlyAcceptsAnchoredJSONAssignment() throws {
        let source = #"window.SEAGULL_CONFIG = {"socialApiUrl":"https://api.example.test","auth":{"mode":"cognito","clientId":"abc"}};"#
        let config = try CloudRuntimeConfig.parseConfigJS(source)
        XCTAssertEqual(config.socialAPIURL, "https://api.example.test")
        XCTAssertEqual(config.auth?.clientID, "abc")
        XCTAssertThrowsError(try CloudRuntimeConfig.parseConfigJS("const x = {}; window.SEAGULL_CONFIG = x;"))
        XCTAssertThrowsError(try CloudRuntimeConfig.parseConfigJS("window.SEAGULL_CONFIG = {socialApiUrl: 'http://bad'};"))
    }

    func testPathComponentsAreEscapedAndBearerTokenIsSent() async throws {
        let protocolClass = URLProtocolFixture.self
        URLProtocolFixture.handler = { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer test-token")
            XCTAssertEqual(request.url?.path, "/profiles/@test:example.test/runtime")
            return (200, Data(#"{"mode":"local","connected":true}"#.utf8))
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [protocolClass]
        let api = try CloudAPI(baseURL: "https://api.example.test", accessToken: "test-token", session: URLSession(configuration: configuration))
        let response: CloudGullRuntime = try await api.get("/profiles/@test:example.test/runtime")
        XCTAssertEqual(response.mode, .local)
    }

    func testErrorDoesNotExposeRawBody() async throws {
        URLProtocolFixture.handler = { _ in (401, Data(#"{"message":"api_key=super-secret-value"}"#.utf8)) }
        let configuration = URLSessionConfiguration.ephemeral; configuration.protocolClasses = [URLProtocolFixture.self]
        let api = try CloudAPI(baseURL: "https://api.example.test", session: URLSession(configuration: configuration))
        do { let _: CloudHealth = try await api.get("/health"); XCTFail("expected failure") }
        catch let error as CloudAPIError {
            XCTAssertFalse(error.localizedDescription.contains("super-secret-value"))
            XCTAssertTrue(error.localizedDescription.contains("[redacted]"))
        }
    }
}

private final class URLProtocolFixture: URLProtocol {
    static var handler: ((URLRequest) -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let result = Self.handler?(request) else { fatalError("missing URLProtocol fixture") }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: result.0, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: result.1); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
