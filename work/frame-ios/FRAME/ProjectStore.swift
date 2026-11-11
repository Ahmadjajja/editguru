import Foundation
import Observation

@MainActor @Observable
final class ProjectStore {
    var projects: [Project] = []
    var selected: Project?
    var isWorking = false
    var error: String?
    var exportURL: URL?
    var pendingUploadProjectID: String?
    var uploadProgress: Double?
    var api: FrameAPI

    init() {
        let saved = UserDefaults.standard.string(forKey: "frame.apiURL") ?? "http://localhost:8765/"
        api = FrameAPI(baseURL: URL(string: saved) ?? URL(string: "http://localhost:8765/")!)
        pendingUploadProjectID = UserDefaults.standard.string(forKey: "frame.pendingUploadProjectID")
    }

    var serverURL: String {
        get { api.baseURL.absoluteString }
        set {
            guard let url = URL(string: newValue), let scheme = url.scheme, ["http", "https"].contains(scheme) else { return }
            api.baseURL = url
            UserDefaults.standard.set(newValue, forKey: "frame.apiURL")
        }
    }

    func load() async {
        await perform { projects = try await api.projects() }
    }

    func refresh() async {
        guard let id = selected?.id else { return }
        do {
            let project = try await api.project(id)
            selected = project
            upsert(project)
        } catch { self.error = error.localizedDescription }
    }

    func create(title: String, brief: String, fileURL: URL?) async {
        await perform {
            var project: Project
            if let pendingUploadProjectID {
                project = try await api.project(pendingUploadProjectID)
            } else {
                project = try await api.create(title: title, brief: brief)
                pendingUploadProjectID = project.id
                UserDefaults.standard.set(project.id, forKey: "frame.pendingUploadProjectID")
            }
            selected = project
            upsert(project)
            if let fileURL {
                let access = fileURL.startAccessingSecurityScopedResource()
                defer { if access { fileURL.stopAccessingSecurityScopedResource() } }
                let total = try fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                guard total > 0 else { throw FrameAPIError.server(0, "The chosen video is empty.") }
                let file = try FileHandle(forReadingFrom: fileURL)
                defer { try? file.close() }
                var status = try await api.uploadStatus(projectID: project.id)
                guard status.total == nil || status.total == total else {
                    throw FrameAPIError.server(409, "This upload was started with a different file.")
                }
                var retries = 0
                while !status.complete {
                    try Task.checkCancellation()
                    try file.seek(toOffset: UInt64(status.offset))
                    let bytes = try file.read(upToCount: min(4 * 1024 * 1024, total - status.offset)) ?? Data()
                    guard !bytes.isEmpty else { throw FrameAPIError.server(0, "Could not read the remaining video data.") }
                    do {
                        status = try await api.uploadChunk(projectID: project.id, bytes: bytes, offset: status.offset, total: total)
                        retries = 0
                    } catch {
                        // The server may have accepted a chunk before the connection broke.
                        status = try await api.uploadStatus(projectID: project.id)
                        retries += 1
                        if retries > 3 { throw error }
                    }
                    uploadProgress = min(1, Double(status.offset) / Double(total))
                }
                uploadProgress = nil
                project = try await api.project(project.id)
                pendingUploadProjectID = nil
                UserDefaults.standard.removeObject(forKey: "frame.pendingUploadProjectID")
                selected = project
                upsert(project)
            }
        }
    }

    func direct(phase: Int, instruction: String) async {
        guard let id = selected?.id else { return }
        await perform { let project = try await api.direct(projectID: id, phase: phase, instruction: instruction); selected = project; upsert(project) }
    }

    func revise(checkpointID: String, instruction: String) async {
        guard let id = selected?.id else { return }
        await perform { let project = try await api.revise(projectID: id, checkpointID: checkpointID, instruction: instruction); selected = project; upsert(project) }
    }

    func restore(checkpointID: String) async {
        guard let id = selected?.id else { return }
        await perform { let project = try await api.restore(projectID: id, checkpointID: checkpointID); selected = project; upsert(project) }
    }

    func export() async {
        guard let id = selected?.id else { return }
        await perform { exportURL = try await api.export(projectID: id) }
    }

    private func upsert(_ project: Project) {
        projects.removeAll { $0.id == project.id }
        projects.insert(project, at: 0)
    }

    private func perform(_ work: () async throws -> Void) async {
        isWorking = true
        error = nil
        defer { isWorking = false }
        do { try await work() } catch { self.error = error.localizedDescription }
    }
}
