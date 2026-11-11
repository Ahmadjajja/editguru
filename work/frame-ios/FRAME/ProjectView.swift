import SwiftUI
import AVKit

struct ProjectView: View {
    @Environment(ProjectStore.self) private var store
    @State private var instruction = ""
    @State private var selectedCheckpoint: Checkpoint?
    @State private var isRevision = false
    @State private var showExport = false

    var body: some View {
        ScrollView {
            if let project = store.selected {
                VStack(alignment: .leading, spacing: 24) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("YOUR FILM").font(.caption.weight(.bold)).tracking(2).foregroundStyle(accent)
                        Text(project.title).font(.system(size: 36, weight: .semibold, design: .serif))
                        Text(project.brief).foregroundStyle(.secondary)
                    }

                    if let checkpoint = selectedCheckpoint ?? project.checkpoints.last {
                        VideoPlayer(player: AVPlayer(url: checkpoint.videoURL))
                            .frame(height: 235).clipShape(RoundedRectangle(cornerRadius: 16))
                            .overlay(alignment: .topLeading) {
                                Text(checkpoint.label.uppercased())
                                    .font(.caption.weight(.bold)).tracking(1)
                                    .padding(8).background(.black.opacity(0.7), in: RoundedRectangle(cornerRadius: 8))
                                    .padding(12)
                            }
                        if let rationale = checkpoint.rationale, !rationale.isEmpty {
                            Text(rationale).font(.subheadline).foregroundStyle(.secondary)
                        }
                    } else {
                        RoundedRectangle(cornerRadius: 16).fill(surface).frame(height: 220)
                            .overlay { VStack(spacing: 8) { Image(systemName: "film").font(.largeTitle); Text("Your first cut is on its way") }.foregroundStyle(.secondary) }
                    }

                    VStack(alignment: .leading, spacing: 16) {
                        let nextPhase = min(5, max(1, (project.checkpoints.map(\.phase).max() ?? 0) + 1))
                        HStack {
                            Text("The edit").font(.title2.weight(.semibold))
                            Spacer()
                            if project.status == "processing" { ProgressView().tint(accent) }
                        }
                        ForEach(EditPhase.allCases) { phase in
                            HStack(alignment: .top, spacing: 12) {
                                Text(String(format: "%02d", phase.rawValue))
                                    .font(.caption.weight(.bold)).foregroundStyle(accent).frame(width: 28)
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(phase.title).font(.headline)
                                    Text(project.checkpoints.contains(where: { $0.phase == phase.rawValue }) ? "Ready to watch" : phase.rawValue == nextPhase ? project.progressMessage ?? "Ready for your direction" : "Coming next")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                if project.checkpoints.contains(where: { $0.phase == phase.rawValue }) {
                                    Image(systemName: "checkmark.circle.fill").foregroundStyle(accent)
                                }
                            }
                            .padding(15).frame(maxWidth: .infinity, alignment: .leading)
                            .background(surface, in: RoundedRectangle(cornerRadius: 14))
                        }
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        Text(isRevision ? "What should change?" : "Direct the next cut")
                            .font(.title2.weight(.semibold))
                        TextField("Describe the feeling, pacing, or detail…", text: $instruction, axis: .vertical)
                            .lineLimit(3...6).padding(14)
                            .background(surface, in: RoundedRectangle(cornerRadius: 14))
                        Button {
                            let text = instruction.trimmingCharacters(in: .whitespacesAndNewlines)
                            Task {
                                if isRevision, let checkpoint = selectedCheckpoint ?? project.checkpoints.last {
                                    await store.revise(checkpointID: checkpoint.id, instruction: text)
                                } else {
                                    let nextPhase = min(5, max(1, (project.checkpoints.map(\.phase).max() ?? 0) + 1))
                                    await store.direct(phase: nextPhase, instruction: text)
                                }
                                instruction = ""
                            }
                        } label: {
                            Text(store.isWorking ? "Working…" : isRevision ? "Revise this cut" : "Create next cut")
                                .font(.headline).frame(maxWidth: .infinity).padding(16)
                                .foregroundStyle(ink).background(accent, in: RoundedRectangle(cornerRadius: 14))
                        }
                        .disabled(instruction.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.isWorking)
                    }

                    if !project.checkpoints.isEmpty {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Versions").font(.title2.weight(.semibold))
                            ForEach(project.checkpoints.reversed()) { checkpoint in
                                Button { selectedCheckpoint = checkpoint; isRevision = true } label: {
                                    HStack {
                                        Image(systemName: "play.rectangle.fill").foregroundStyle(accent)
                                        Text(checkpoint.label)
                                        Spacer()
                                        if selectedCheckpoint?.id == checkpoint.id { Image(systemName: "checkmark") }
                                    }.padding(15).background(surface, in: RoundedRectangle(cornerRadius: 14))
                                }.buttonStyle(.plain)
                            }
                            if let checkpoint = selectedCheckpoint {
                                Button("Restore selected version") { Task { await store.restore(checkpointID: checkpoint.id) } }
                                    .font(.subheadline).foregroundStyle(accent)
                            }
                        }
                    }

                    Button { Task { await store.export(); showExport = store.exportURL != nil } } label: {
                        Label("Export film", systemImage: "square.and.arrow.up")
                            .font(.headline).frame(maxWidth: .infinity).padding(16)
                            .overlay(RoundedRectangle(cornerRadius: 14).stroke(accent))
                    }
                    .disabled(project.checkpoints.isEmpty || store.isWorking)
                }
                .padding(22)
            }
        }
        .background(ink.ignoresSafeArea())
        .navigationTitle("FRAME")
        .navigationBarTitleDisplayMode(.inline)
        .tint(accent)
        .task {
            while !Task.isCancelled {
                await store.refresh()
                try? await Task.sleep(for: .seconds(5))
            }
        }
        .sheet(isPresented: $showExport) {
            if let url = store.exportURL {
                ShareLink(item: url) { Label("Share exported film", systemImage: "square.and.arrow.up") }
                    .presentationDetents([.medium])
            }
        }
    }
}
