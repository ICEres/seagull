import XCTest
@testable import Gulls

final class GullIdentityTests: XCTestCase {
    func testMatchesJavaScriptHashFixtures() {
        XCTAssertEqual(GullIdentity.javascriptHash(""), 0)
        XCTAssertEqual(GullIdentity.javascriptHash("test2"), 110_251_488)
        XCTAssertEqual(GullIdentity.javascriptHash("studio"), 3_403_065_814)
        XCTAssertEqual(GullIdentity.javascriptHash("agent_alice"), 1_978_541_254)
        XCTAssertEqual(GullIdentity.javascriptHash("@test2:example.test"), 2_057_889_328)
        XCTAssertEqual(GullIdentity.javascriptHash("@studio:example.test"), 613_241_210)
    }

    func testUsesUTF16CodeUnitsForUnicodeHandles() {
        XCTAssertEqual(GullIdentity.javascriptHash("测试"), 903_146)
        XCTAssertEqual(GullIdentity.javascriptHash("😀"), 1_772_899)
    }

    func testIdentityIsStableForTheSameHandle() {
        let first = GullIdentity(handle: "test2")
        let second = GullIdentity(handle: "test2")

        XCTAssertEqual(first, second)
        XCTAssertEqual(first.wingName, .classic)
        XCTAssertEqual(first.tintHue, 245)
    }

    func testWingAndTintRemainHandleDerived() {
        let test2 = GullIdentity(handle: "test2")
        let studio = GullIdentity(handle: "studio")

        XCTAssertNotEqual(test2.wingName, studio.wingName)
        XCTAssertNotEqual(test2.tintHue, studio.tintHue)
    }

    func testLoopWingPreservesTheSVGNegativeLargeArc() {
        let path = GullWing(name: .loop).path(in: CGRect(x: 0, y: 0, width: 32, height: 14))

        // The SVG arc travels below its endpoints. A short normalized arc
        // incorrectly travels above them and has a much smaller height.
        XCTAssertGreaterThan(path.boundingRect.height, 6.5)
        XCTAssertGreaterThan(path.boundingRect.maxY, 13.2)
    }
}
