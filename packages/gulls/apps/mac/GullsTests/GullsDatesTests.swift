import XCTest
@testable import Gulls

// Hub timestamps arrive in several ISO 8601 flavors: the Go hubstub emits
// second-precision RFC 3339, the real hub emits Python isoformat() with
// microseconds. Display code must parse all of them.
final class GullsDatesTests: XCTestCase {

    func testParsesRFC3339SecondPrecision() {
        XCTAssertNotNil(GullsDates.parse("2026-07-17T09:15:23Z"))
    }

    func testParsesPythonIsoformatWithMicroseconds() {
        // datetime_to_string in the hub: isoformat() → microseconds + offset.
        XCTAssertNotNil(GullsDates.parse("2026-07-17T09:15:23.123456+00:00"))
    }

    func testParsesMillisecondPrecisionZulu() {
        XCTAssertNotNil(GullsDates.parse("2026-07-17T09:15:23.123Z"))
    }

    func testFractionalVariantsAgreeOnTheSecond() throws {
        let plain = try XCTUnwrap(GullsDates.parse("2026-07-17T09:15:23Z"))
        let micro = try XCTUnwrap(GullsDates.parse("2026-07-17T09:15:23.123456+00:00"))
        XCTAssertEqual(plain.timeIntervalSince1970, micro.timeIntervalSince1970, accuracy: 1)
    }

    func testRejectsGarbage() {
        XCTAssertNil(GullsDates.parse("yesterday-ish"))
        XCTAssertNil(GullsDates.parse(""))
    }
}
