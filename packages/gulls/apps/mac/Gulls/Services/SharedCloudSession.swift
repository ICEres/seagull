import Darwin
import Foundation

struct SharedCloudSession: Codable, Equatable {
    let version: Int
    let websiteURL: String
    let accessToken: String
    let expiresAt: Double

    var expirationDate: Date {
        let reported = Date(timeIntervalSince1970: expiresAt / 1000)
        let parts = accessToken.split(separator: ".")
        guard parts.count == 3 else { return reported }
        var claims = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        claims += String(repeating: "=", count: (4 - claims.count % 4) % 4)
        guard let data = Data(base64Encoded: claims),
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let expiry = payload["exp"] as? Double, expiry.isFinite else { return reported }
        return min(reported, Date(timeIntervalSince1970: expiry))
    }

    enum CodingKeys: String, CodingKey {
        case version
        case websiteURL = "website_url"
        case accessToken = "access_token"
        case expiresAt = "expires_at"
    }
}

struct SharedCloudSessionFile {
    let url: URL

    static var defaultURL: URL {
        if let path = ProcessInfo.processInfo.environment["SEAGULL_ACCOUNT_SESSION_FILE"], !path.isEmpty {
            return URL(fileURLWithPath: (path as NSString).expandingTildeInPath)
        }
        return URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent(".config/seagull/account.json")
    }

    func read(for websiteURL: String) throws -> SharedCloudSession? {
        let descriptor = open(url.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
        if descriptor < 0 {
            if errno == ENOENT { return nil }
            throw SharedCloudSessionError.unreadable
        }
        defer { close(descriptor) }
        try validateDirectory()
        var attributes = stat()
        guard fstat(descriptor, &attributes) == 0,
              attributes.st_mode & S_IFMT == S_IFREG,
              attributes.st_uid == getuid(),
              attributes.st_mode & 0o077 == 0,
              attributes.st_size > 0, attributes.st_size <= 32_768 else {
            throw SharedCloudSessionError.unreadable
        }
        let file = FileHandle(fileDescriptor: descriptor, closeOnDealloc: false)
        guard let data = try? file.read(upToCount: 32_769), data.count <= 32_768,
              let value = try? JSONDecoder().decode(SharedCloudSession.self, from: data),
              value.version == 1, !value.accessToken.isEmpty, value.expiresAt.isFinite,
              let savedWebsite = Self.normalizedWebsite(value.websiteURL),
              let requestedWebsite = Self.normalizedWebsite(websiteURL) else {
            throw SharedCloudSessionError.unreadable
        }
        return savedWebsite == requestedWebsite ? value : nil
    }

    func remove(for websiteURL: String) throws {
        guard let requestedWebsite = Self.normalizedWebsite(websiteURL) else { throw SharedCloudSessionError.unreadable }
        let descriptor = open(url.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
        if descriptor < 0 {
            if errno == ENOENT { return }
            throw SharedCloudSessionError.unreadable
        }
        defer { close(descriptor) }
        try validateDirectory()
        var attributes = stat()
        guard fstat(descriptor, &attributes) == 0,
              attributes.st_mode & S_IFMT == S_IFREG,
              attributes.st_uid == getuid(), attributes.st_mode & 0o077 == 0 else {
            throw SharedCloudSessionError.unreadable
        }
        let file = FileHandle(fileDescriptor: descriptor, closeOnDealloc: false)
        if let data = try? file.read(upToCount: 32_769), data.count <= 32_768,
           let value = try? JSONDecoder().decode(SharedCloudSession.self, from: data),
           let savedWebsite = Self.normalizedWebsite(value.websiteURL), savedWebsite != requestedWebsite {
            return
        }
        var current = stat()
        guard lstat(url.path, &current) == 0,
              current.st_dev == attributes.st_dev, current.st_ino == attributes.st_ino,
              unlink(url.path) == 0 else { throw SharedCloudSessionError.unreadable }
    }

    func write(_ value: SharedCloudSession) throws {
        let directory = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                               attributes: [.posixPermissions: 0o700])
        try validateDirectory()
        let temporary = directory.appendingPathComponent(".account-\(UUID().uuidString).json")
        let descriptor = open(temporary.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { throw SharedCloudSessionError.unreadable }
        defer {
            close(descriptor)
            try? FileManager.default.removeItem(at: temporary)
        }
        let file = FileHandle(fileDescriptor: descriptor, closeOnDealloc: false)
        try file.write(contentsOf: JSONEncoder().encode(value))
        try file.synchronize()
        guard rename(temporary.path, url.path) == 0 else { throw SharedCloudSessionError.unreadable }
    }

    private func validateDirectory() throws {
        var attributes = stat()
        guard lstat(url.deletingLastPathComponent().path, &attributes) == 0,
              attributes.st_mode & S_IFMT == S_IFDIR,
              attributes.st_uid == getuid(), attributes.st_mode & 0o077 == 0 else {
            throw SharedCloudSessionError.unreadable
        }
    }

    static func normalizedWebsite(_ raw: String) -> String? {
        guard var components = URLComponents(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)),
              let host = components.host, !host.isEmpty,
              components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil,
              components.path.isEmpty || components.path == "/" else { return nil }
        let scheme = components.scheme?.lowercased()
        guard scheme == "https" || (scheme == "http" && ["localhost", "127.0.0.1", "::1"].contains(host.lowercased())) else { return nil }
        components.scheme = scheme
        components.host = host.lowercased()
        components.path = ""
        if components.port == (scheme == "https" ? 443 : 80) { components.port = nil }
        return components.url?.absoluteString
    }
}

enum SharedCloudSessionError: Error, LocalizedError {
    case unreadable

    var errorDescription: String? {
        "The saved CLI sign-in could not be read securely. Sign in again from your browser."
    }
}
