import Foundation

enum CloudAPIError: Error, LocalizedError, Equatable {
    case invalidBaseURL
    case insecureURL
    case invalidPath
    case invalidResponse
    case http(status: Int, message: String)
    case encoding
    case decoding

    var errorDescription: String? {
        switch self {
        case .invalidBaseURL: return "The cloud service URL is invalid."
        case .insecureURL: return "Cloud services require HTTPS, except for loopback development URLs."
        case .invalidPath: return "The cloud request path is invalid."
        case .invalidResponse: return "The cloud service returned an invalid response."
        case .http(let status, let message): return "Cloud request failed (\(status)): \(message)"
        case .encoding: return "The cloud request could not be encoded."
        case .decoding: return "The cloud service returned an unexpected response."
        }
    }
}

/// Stateless JSON client for the Social API, Message Hub, and AI Provider.
/// It never persists credentials and only sends a Bearer token to its base URL.
final class CloudAPI {
    let baseURL: URL
    let accessToken: String
    private let session: URLSession
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(baseURL: String, accessToken: String = "", session: URLSession? = nil) throws {
        guard let url = URL(string: baseURL.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = url.scheme?.lowercased(),
              let host = url.host,
              !host.isEmpty,
              url.user == nil,
              url.password == nil else {
            throw CloudAPIError.invalidBaseURL
        }
        let loopback = host == "localhost" || host == "127.0.0.1" || host == "::1"
        guard scheme == "https" || (scheme == "http" && loopback) else {
            throw CloudAPIError.insecureURL
        }
        self.baseURL = url
        self.accessToken = accessToken.trimmingCharacters(in: .whitespacesAndNewlines)
        self.session = session ?? URLSession(
            configuration: .ephemeral,
            delegate: CloudRedirectDelegate(origin: url.originKey),
            delegateQueue: nil
        )
        encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .custom { path in
            let raw = path.last?.stringValue ?? ""
            return AnyCodingKey(stringValue: CloudAPI.normalizedKey(raw))
        }
    }

    func get<Response: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> Response {
        try await request(method: "GET", path: path, query: query, body: nil)
    }

    func post<Body: Encodable, Response: Decodable>(_ path: String, body: Body, query: [URLQueryItem] = []) async throws -> Response {
        try await request(method: "POST", path: path, query: query, body: try encode(body))
    }

    func post<Response: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> Response {
        try await request(method: "POST", path: path, query: query, body: nil)
    }

    func put<Body: Encodable, Response: Decodable>(_ path: String, body: Body, query: [URLQueryItem] = []) async throws -> Response {
        try await request(method: "PUT", path: path, query: query, body: try encode(body))
    }

    func patch<Body: Encodable, Response: Decodable>(_ path: String, body: Body, query: [URLQueryItem] = []) async throws -> Response {
        try await request(method: "PATCH", path: path, query: query, body: try encode(body))
    }

    func delete<Response: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> Response {
        try await request(method: "DELETE", path: path, query: query, body: nil)
    }

    private func encode<Body: Encodable>(_ body: Body) throws -> Data {
        do { return try encoder.encode(body) } catch { throw CloudAPIError.encoding }
    }

    private func request<Response: Decodable>(method: String, path: String, query: [URLQueryItem], body: Data?) async throws -> Response {
        guard let url = makeURL(path: path, query: query) else { throw CloudAPIError.invalidPath }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if !accessToken.isEmpty { request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization") }
        let data: Data
        let response: URLResponse
        do {
            let delegate = CloudRedirectDelegate(origin: baseURL.originKey)
            (data, response) = try await session.data(for: request, delegate: delegate)
        }
        catch { throw CloudAPIError.http(status: -1, message: "The network request could not be completed.") }
        guard let http = response as? HTTPURLResponse else { throw CloudAPIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else { throw httpError(status: http.statusCode, data: data) }
        guard !data.isEmpty else { throw CloudAPIError.decoding }
        do { return try decoder.decode(Response.self, from: data) } catch { throw CloudAPIError.decoding }
    }

    private func makeURL(path: String, query: [URLQueryItem]) -> URL? {
        guard !path.contains("://"), !path.contains(".."), !path.contains("\\") else { return nil }
        var url = baseURL
        for component in path.split(separator: "/", omittingEmptySubsequences: true) {
            guard !component.isEmpty else { continue }
            url.appendPathComponent(String(component), isDirectory: false)
        }
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        components.queryItems = query.isEmpty ? nil : query
        return components.url
    }

    private func httpError(status: Int, data: Data) -> CloudAPIError {
        struct ErrorPayload: Decodable { var error: String?; var message: String? }
        let payload = try? decoder.decode(ErrorPayload.self, from: data)
        let raw = payload?.message ?? payload?.error ?? "Request rejected"
        let sanitized = redact(raw.trimmingCharacters(in: .whitespacesAndNewlines)).prefix(240)
        return .http(status: status, message: sanitized.isEmpty ? "Request rejected" : String(sanitized))
    }

    private func redact(_ value: String) -> String {
        var result = value
        let patterns = [
            #"(?i)(bearer\s+)[^\s,;]+"#,
            #"(?i)((?:api[_-]?key|secret|token|pair[_-]?token)["'\s:=]+)[^\s,;"']+"#,
        ]
        for pattern in patterns {
            guard let expression = try? NSRegularExpression(pattern: pattern) else { continue }
            let range = NSRange(result.startIndex..<result.endIndex, in: result)
            result = expression.stringByReplacingMatches(in: result, range: range, withTemplate: "$1[redacted]")
        }
        return result
    }

    private static func normalizedKey(_ raw: String) -> String {
        guard raw.contains("_") else { return raw }
        let pieces = raw.split(separator: "_")
        guard let first = pieces.first else { return raw }
        var value = String(first)
        for piece in pieces.dropFirst() { value += piece.prefix(1).uppercased() + piece.dropFirst() }
        for suffix in ["Id", "Url", "Uri", "Api"] {
            if value.hasSuffix(suffix) { value = String(value.dropLast(suffix.count)) + suffix.uppercased() }
        }
        return value
    }
}

final class CloudRedirectDelegate: NSObject, URLSessionTaskDelegate {
    private let origin: String

    init(origin: String) { self.origin = origin }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        guard let url = request.url,
              (url.scheme?.lowercased() == "https" || (url.scheme?.lowercased() == "http" && url.isLoopback)),
              url.originKey == origin else {
            completionHandler(nil)
            return
        }
        completionHandler(request)
    }
}

extension URL {
    var isLoopback: Bool {
        host == "localhost" || host == "127.0.0.1" || host == "::1"
    }

    var originKey: String {
        let scheme = scheme?.lowercased() ?? ""
        let host = host?.lowercased() ?? ""
        let portValue = port.map(String.init) ?? ((scheme == "https") ? "443" : "80")
        return "\(scheme)://\(host):\(portValue)"
    }
}

private struct AnyCodingKey: CodingKey {
    var stringValue: String
    init(stringValue: String) { self.stringValue = stringValue }
    var intValue: Int? { nil }
    init?(intValue: Int) { nil }
}
