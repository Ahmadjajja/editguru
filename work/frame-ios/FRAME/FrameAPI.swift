import Foundation

enum FrameAPIError: LocalizedError {
    case invalidResponse
    case server(Int, String)
    var errorDescription: String? {
        switch self {
        case .invalidResponse: "The server sent an unreadable response."
        case let .server(code, message): "Server error \(code): \(message)"
        }
    }
}

struct FrameAPI {
    var baseURL: URL
    private let session: URLSession

    init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    private func request<T: Decodable>(_ path: String, method: String = "GET", body: Encodable? = nil) async throws -> T {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = method
        request.timeoutInterval = 60
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(AnyEncodable(body))
        }
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw FrameAPIError.invalidResponse }
        guard (200..<300).contains(response.statusCode) else {
            throw FrameAPIError.server(response.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try decoder.decode(T.self, from: data)
    }

    func projects() async throws -> [Project] {
        let response: ProjectList = try await request("api/projects")
        return response.projects
    }

    func create(title: String, brief: String) async throws -> Project {
        try await request("api/projects", method: "POST", body: ["title": title, "brief": brief])
    }

    func project(_ id: String) async throws -> Project {
        try await request("api/projects/\(id)")
    }

    func upload(projectID: String, fileURL: URL) async throws -> Project {
        var request = URLRequest(url: baseURL.appending(path: "api/projects/\(projectID)/media"))
        request.httpMethod = "POST"
        request.setValue("video/mp4", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 600
        // URLSession's file upload can continue without loading the whole clip into memory.
        let (data, response) = try await session.upload(for: request, fromFile: fileURL)
        guard let response = response as? HTTPURLResponse else { throw FrameAPIError.invalidResponse }
        guard (200..<300).contains(response.statusCode) else {
            throw FrameAPIError.server(response.statusCode, String(data: data, encoding: .utf8) ?? "Upload failed")
        }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try decoder.decode(Project.self, from: data)
    }

    func uploadStatus(projectID: String) async throws -> UploadStatus {
        try await request("api/projects/\(projectID)/media/upload")
    }

    func uploadChunk(projectID: String, bytes: Data, offset: Int, total: Int) async throws -> UploadStatus {
        var request = URLRequest(url: baseURL.appending(path: "api/projects/\(projectID)/media/upload"))
        request.httpMethod = "PUT"
        request.setValue("video/mp4", forHTTPHeaderField: "Content-Type")
        request.setValue(String(offset), forHTTPHeaderField: "X-Upload-Offset")
        request.setValue(String(total), forHTTPHeaderField: "X-Upload-Total")
        request.timeoutInterval = 120
        let (data, response) = try await session.upload(for: request, from: bytes)
        guard let response = response as? HTTPURLResponse else { throw FrameAPIError.invalidResponse }
        guard (200..<300).contains(response.statusCode) else {
            throw FrameAPIError.server(response.statusCode, String(data: data, encoding: .utf8) ?? "Upload failed")
        }
        return try JSONDecoder().decode(UploadStatus.self, from: data)
    }

    func direct(projectID: String, phase: Int, instruction: String) async throws -> Project {
        try await request("api/projects/\(projectID)/directives", method: "POST", body: Directive(phase: phase, instruction: instruction))
    }

    func revise(projectID: String, checkpointID: String, instruction: String) async throws -> Project {
        try await request("api/projects/\(projectID)/revisions", method: "POST", body: Revision(checkpointID: checkpointID, instruction: instruction))
    }

    func restore(projectID: String, checkpointID: String) async throws -> Project {
        try await request("api/projects/\(projectID)/restore", method: "POST", body: ["checkpoint_id": checkpointID])
    }

    func export(projectID: String) async throws -> URL {
        let response: ExportResponse = try await request("api/projects/\(projectID)/export")
        return response.url
    }
}

struct UploadStatus: Decodable {
    let offset: Int
    let total: Int?
    let complete: Bool
}

private struct Directive: Encodable { let phase: Int; let instruction: String }
private struct Revision: Encodable {
    let checkpointID: String
    let instruction: String
    enum CodingKeys: String, CodingKey { case checkpointID = "checkpoint_id", instruction }
}
private struct AnyEncodable: Encodable {
    private let encodeValue: (Encoder) throws -> Void
    init(_ value: Encodable) { encodeValue = value.encode }
    func encode(to encoder: Encoder) throws { try encodeValue(encoder) }
}
