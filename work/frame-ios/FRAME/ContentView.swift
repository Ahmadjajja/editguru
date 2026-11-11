import SwiftUI
import AVKit
import UniformTypeIdentifiers

let ink = Color(red: 0.055, green: 0.062, blue: 0.078)
let surface = Color(red: 0.11, green: 0.12, blue: 0.145)
let accent = Color(red: 0.95, green: 0.72, blue: 0.42)

struct ContentView: View {
    @Environment(ProjectStore.self) private var store
    @State private var showingNew = false
    @State private var showingSettings = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    header
                    if let project = store.selected {
                        NavigationLink { ProjectView() } label: { featured(project) }
                            .buttonStyle(.plain)
                    } else {
                        emptyState
                    }
                    if !store.projects.isEmpty {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("YOUR FILMS").font(.caption.weight(.bold)).tracking(2).foregroundStyle(accent)
                            ForEach(store.projects) { project in
                                Button {
                                    store.selected = project
                                } label: {
                                    HStack {
                                        VStack(alignment: .leading, spacing: 5) {
                                            Text(project.title).font(.headline)
                                            Text(project.status.capitalized).font(.caption).foregroundStyle(.secondary)
                                        }
                                        Spacer()
                                        Image(systemName: "arrow.up.right")
                                    }
                                    .padding(18).background(surface, in: RoundedRectangle(cornerRadius: 18))
                                }.buttonStyle(.plain)
                            }
                        }
                    }
                }.padding(24)
            }
            .background(ink.ignoresSafeArea())
            .toolbar(.hidden)
            .sheet(isPresented: $showingNew) { NewProjectView() }
            .sheet(isPresented: $showingSettings) { SettingsView() }
            .task { await store.load() }
            .alert("FRAME couldn't complete that", isPresented: Binding(get: { store.error != nil }, set: { if !$0 { store.error = nil } })) {
                Button("OK", role: .cancel) { store.error = nil }
            } message: { Text(store.error ?? "Please try again.") }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 28) {
            HStack {
                Text("FRAME").font(.system(size: 22, weight: .black, design: .rounded)).tracking(4)
                Spacer()
                Button { showingSettings = true } label: { Image(systemName: "gearshape").font(.title3) }
            }
            VStack(alignment: .leading, spacing: 8) {
                Text("Your vision.\nIn motion.")
                    .font(.system(size: 42, weight: .semibold, design: .serif))
                    .tracking(-1.8)
                Text("Direct the story. Your editor handles the craft.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            Button { showingNew = true } label: {
                Label("Start a film", systemImage: "plus")
                    .font(.headline).frame(maxWidth: .infinity).padding(16)
                    .foregroundStyle(ink).background(accent, in: RoundedRectangle(cornerRadius: 15))
            }
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 12) {
            Image(systemName: "sparkles.tv").font(.largeTitle).foregroundStyle(accent)
            Text("A creative partner in your pocket.").font(.title3.weight(.semibold))
            Text("Bring your footage and tell FRAME what you want people to feel.")
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading).padding(22)
        .background(surface, in: RoundedRectangle(cornerRadius: 22))
    }

    private func featured(_ project: Project) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("IN PROGRESS").font(.caption.weight(.bold)).tracking(2).foregroundStyle(accent)
            Text(project.title).font(.system(size: 28, weight: .semibold, design: .serif))
            Text(project.progressMessage ?? "Open your film and keep creating.")
                .font(.subheadline).foregroundStyle(.secondary)
            HStack { Text("Open film"); Spacer(); Image(systemName: "arrow.right") }
                .font(.headline).foregroundStyle(accent)
        }
        .padding(22).frame(maxWidth: .infinity, alignment: .leading)
        .background(LinearGradient(colors: [surface, Color(red: 0.2, green: 0.18, blue: 0.16)], startPoint: .topLeading, endPoint: .bottomTrailing), in: RoundedRectangle(cornerRadius: 22))
    }
}

private struct NewProjectView: View {
    @Environment(ProjectStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var brief = ""
    @State private var fileURL: URL?
    @State private var importing = false

    var body: some View {
        NavigationStack {
            Form {
                Section("The film") {
                    TextField("Working title", text: $title)
                    TextField("What should this make people feel?", text: $brief, axis: .vertical)
                        .lineLimit(3...6)
                }
                Section("Your footage") {
                    if store.pendingUploadProjectID != nil {
                        Text("An earlier upload can resume. Choose the same video file to continue from the last saved chunk.")
                            .font(.caption).foregroundStyle(accent)
                    }
                    Button { importing = true } label: {
                        Label(fileURL?.lastPathComponent ?? "Choose a video", systemImage: "video.badge.plus")
                    }
                    Text("Choose a video from Files. FRAME will create a playable version at each phase.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section {
                    if let progress = store.uploadProgress {
                        ProgressView(value: progress) { Text("Uploading video") } currentValueLabel: { Text("\(Int(progress * 100))%") }
                    }
                    Button {
                        Task { await store.create(title: title, brief: brief, fileURL: fileURL); if store.error == nil { dismiss() } }
                    } label: {
                        HStack { Spacer(); Text(store.isWorking ? "Creating…" : "Create film"); Spacer() }
                    }
                    .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty || brief.trimmingCharacters(in: .whitespaces).isEmpty || fileURL == nil || store.isWorking)
                }
            }
            .navigationTitle("New film")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
            .fileImporter(isPresented: $importing, allowedContentTypes: [.movie, .video, .mpeg4Movie]) { result in
                if case let .success(url) = result { fileURL = url }
            }
            .alert("Upload needs another try", isPresented: Binding(get: { store.error != nil }, set: { if !$0 { store.error = nil } })) {
                Button("OK", role: .cancel) { store.error = nil }
            } message: { Text(store.error ?? "Please try again.") }
        }
        .tint(accent)
    }
}

private struct SettingsView: View {
    @Environment(ProjectStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var url = ""
    var body: some View {
        NavigationStack {
            Form {
                Section("Cloud workspace") {
                    TextField("API URL", text: $url).textInputAutocapitalization(.never).keyboardType(.URL)
                    Text("On a physical iPhone, enter an HTTPS address reachable from the phone. localhost works only with a server on the same device or simulator host. Settings are saved on this phone.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Save") { store.serverURL = url; dismiss() } } }
            .onAppear { url = store.serverURL }
        }.tint(accent)
    }
}
