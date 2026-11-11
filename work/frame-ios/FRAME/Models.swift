import Foundation

enum EditPhase: Int, CaseIterable, Identifiable, Codable {
    case story = 1, studio, broll, captions, sound
    var id: Int { rawValue }
    var title: String {
        switch self {
        case .story: "Story & Rhythm"
        case .studio: "Studio & Visuals"
        case .broll: "B-roll & Storytelling"
        case .captions: "Captions & Graphics"
        case .sound: "Sound & Final Polish"
        }
    }
    var shortTitle: String {
        switch self {
        case .story: "Story"
        case .studio: "Visuals"
        case .broll: "B-roll"
        case .captions: "Captions"
        case .sound: "Sound"
        }
    }
}

struct Checkpoint: Codable, Identifiable, Hashable {
    let id: String
    let phase: Int
    let version: Int
    let videoURL: URL
    let createdAt: Date
    let rationale: String?
    var label: String { "V\(version) · \(EditPhase(rawValue: phase)?.shortTitle ?? "Edit")" }

    enum CodingKeys: String, CodingKey {
        case id, phase, version, rationale
        case videoURL = "video_url"
        case createdAt = "created_at"
    }
}

struct Project: Codable, Identifiable {
    let id: String
    var title: String
    var brief: String
    var status: String
    var currentPhase: Int
    var checkpoints: [Checkpoint]
    var progressMessage: String?

    enum CodingKeys: String, CodingKey {
        case id, title, brief, status, checkpoints
        case currentPhase = "current_phase"
        case progressMessage = "progress_message"
    }
}

struct ProjectList: Codable { let projects: [Project] }
struct ExportResponse: Codable { let url: URL }
