import XCTest
@testable import Gulls

// The import parser must match loadEnvFile in the CLI (config.go).
final class EnvFileParserTests: XCTestCase {
    func testParsesExportsCommentsAndQuotes() {
        let text = """
        # Seagull connector config
        export SEAGULL_API_URL="https://fishing.gulls.ai"
        SEAGULL_AGENT_HANDLE='@worker:gulls.ai'
        SEAGULL_CONNECTOR_TOKEN = secret-token

        not a key value line
        =missing-name
        SEAGULL_AGENT_POLL_INTERVAL=30
        """

        let values = GullsConfig.parseEnvFile(text)

        XCTAssertEqual(values["SEAGULL_API_URL"], "https://fishing.gulls.ai")
        XCTAssertEqual(values["SEAGULL_AGENT_HANDLE"], "@worker:gulls.ai")
        XCTAssertEqual(values["SEAGULL_CONNECTOR_TOKEN"], "secret-token")
        XCTAssertEqual(values["SEAGULL_AGENT_POLL_INTERVAL"], "30")
        XCTAssertNil(values["not a key value line"])
        XCTAssertEqual(values.count, 4)
    }

    func testMismatchedQuotesAreKept() {
        let values = GullsConfig.parseEnvFile(#"SEAGULL_API_URL="https://example.test'"#)
        XCTAssertEqual(values["SEAGULL_API_URL"], #""https://example.test'"#)
    }
}
