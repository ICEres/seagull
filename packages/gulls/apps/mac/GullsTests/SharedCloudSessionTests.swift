import Darwin
import Foundation
import XCTest
@testable import Gulls

final class SharedCloudSessionTests: XCTestCase {
    private var temporaryDirectories: [URL] = []

    override func tearDownWithError() throws {
        for directory in temporaryDirectories {
            try? FileManager.default.removeItem(at: directory)
        }
        temporaryDirectories.removeAll()
        try super.tearDownWithError()
    }

    func testWriteUsesPrivateFileAndReadIsWebsiteIsolated() throws {
        let directory = try makeTemporaryDirectory()
        let file = SharedCloudSessionFile(url: directory.appendingPathComponent("account.json"))
        let session = makeSession(websiteURL: "https://WEB.Example.test:443/")

        try file.write(session)

        let attributes = try FileManager.default.attributesOfItem(atPath: file.url.path)
        XCTAssertEqual((attributes[.posixPermissions] as? NSNumber)?.intValue, 0o600)
        XCTAssertEqual(try file.read(for: " https://web.example.test "), session)
        XCTAssertNil(try file.read(for: "https://other.example.test"))
        XCTAssertNil(SharedCloudSessionFile.normalizedWebsite("https://web.example.test/path/"))
        XCTAssertEqual(
            SharedCloudSessionFile.normalizedWebsite("http://127.0.0.1:80/"),
            "http://127.0.0.1"
        )
        XCTAssertNil(SharedCloudSessionFile.normalizedWebsite("http://example.test"))
    }

    func testReadRejectsPublicReadableFilesAndSymlinks() throws {
        let directory = try makeTemporaryDirectory()
        let fileURL = directory.appendingPathComponent("account.json")
        let file = SharedCloudSessionFile(url: fileURL)
        try file.write(makeSession())
        XCTAssertEqual(chmod(fileURL.path, 0o644), 0)
        XCTAssertThrowsError(try file.read(for: "https://web.example.test"))

        let targetURL = directory.appendingPathComponent("target.json")
        let linkURL = directory.appendingPathComponent("link.json")
        try file.write(makeSession())
        try FileManager.default.copyItem(at: fileURL, to: targetURL)
        try FileManager.default.removeItem(at: fileURL)
        try FileManager.default.createSymbolicLink(at: linkURL, withDestinationURL: targetURL)
        XCTAssertThrowsError(try SharedCloudSessionFile(url: linkURL).read(for: "https://web.example.test"))
    }

    func testRemoveDeletesCorruptPrivateFilePreservesOtherWebsiteAndRejectsSymlink() throws {
        let directory = try makeTemporaryDirectory()
        let fileURL = directory.appendingPathComponent("account.json")
        let file = SharedCloudSessionFile(url: fileURL)

        try file.write(makeSession(websiteURL: "https://other.example.test"))
        try file.remove(for: "https://web.example.test")
        XCTAssertNotNil(try file.read(for: "https://other.example.test"))

        try Data("not-json".utf8).write(to: fileURL)
        try file.remove(for: "https://other.example.test")
        XCTAssertFalse(FileManager.default.fileExists(atPath: fileURL.path))

        let targetURL = directory.appendingPathComponent("target.json")
        let linkURL = directory.appendingPathComponent("link.json")
        try file.write(makeSession())
        try FileManager.default.copyItem(at: fileURL, to: targetURL)
        try FileManager.default.removeItem(at: fileURL)
        try FileManager.default.createSymbolicLink(at: linkURL, withDestinationURL: targetURL)
        XCTAssertThrowsError(try SharedCloudSessionFile(url: linkURL).remove(for: "https://web.example.test"))
        XCTAssertTrue(FileManager.default.fileExists(atPath: linkURL.path))
    }

    func testExpirationDateIsClampedToJwtExpiry() throws {
        let reportedExpiry = Date(timeIntervalSince1970: 2_000)
        let jwtExpiry = Date(timeIntervalSince1970: 1_500)
        let token = try makeJWT(expiry: jwtExpiry.timeIntervalSince1970)
        let session = SharedCloudSession(version: 1, websiteURL: "https://web.example.test", accessToken: token, expiresAt: reportedExpiry.timeIntervalSince1970 * 1000)

        XCTAssertEqual(session.expirationDate.timeIntervalSince1970, jwtExpiry.timeIntervalSince1970, accuracy: 0.001)
    }

    func testSharedSessionRequiresPrivateDirectory() throws {
        let directory = try makeTemporaryDirectory()
        let file = SharedCloudSessionFile(url: directory.appendingPathComponent("account.json"))
        try file.write(makeSession())
        XCTAssertEqual(chmod(directory.path, 0o755), 0)
        XCTAssertThrowsError(try file.read(for: "https://web.example.test"))
        XCTAssertThrowsError(try file.write(makeSession()))
        XCTAssertThrowsError(try file.remove(for: "https://web.example.test"))
    }

    private func makeSession(websiteURL: String = "https://web.example.test") -> SharedCloudSession {
        SharedCloudSession(version: 1, websiteURL: websiteURL, accessToken: "fake-access-token", expiresAt: 4_000_000_000_000)
    }

    private func makeJWT(expiry: TimeInterval) throws -> String {
        let header = try JSONSerialization.data(withJSONObject: ["alg": "none", "typ": "JWT"])
        let payload = try JSONSerialization.data(withJSONObject: ["exp": expiry])
        return "\(base64URL(header)).\(base64URL(payload)).signature"
    }

    private func base64URL(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    private func makeTemporaryDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("gulls-shared-session-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                               attributes: [.posixPermissions: 0o700])
        temporaryDirectories.append(directory)
        return directory
    }
}
