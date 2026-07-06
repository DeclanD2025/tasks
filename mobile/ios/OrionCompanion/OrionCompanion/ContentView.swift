import SwiftData
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @Environment(CompanionStore.self) private var store
    @Environment(AppLockStore.self) private var appLock
    @State private var isImporting = false

    var body: some View {
        Group {
            if appLock.isLocked {
                LockScreen()
            } else {
                AppShell(isImporting: $isImporting)
            }
        }
        .fileImporter(isPresented: $isImporting, allowedContentTypes: [.json]) { result in
            if case let .success(url) = result {
                store.importSnapshot(from: url)
            }
        }
        .task {
            await store.refreshCloudKitStatus()
        }
    }
}

@MainActor
private struct AppShell: View {
    @Binding var isImporting: Bool
    @State private var selectedTab: AppTab = .today
    @State private var tabRouter = TabRouter()

    var body: some View {
        TabView(selection: $selectedTab) {
            ForEach(AppTab.allCases) { tab in
                NavigationStack(path: tabRouter.binding(for: tab)) {
                    tab.content(isImporting: $isImporting)
                        .withAppRouter()
                }
                .environment(tabRouter.router(for: tab))
                .tabItem { tab.label }
                .tag(tab)
            }
        }
    }
}

private enum AppTab: String, CaseIterable, Identifiable {
    case today
    case tasks
    case capture
    case insights
    case settings

    var id: String { rawValue }

    @ViewBuilder
    func content(isImporting: Binding<Bool>) -> some View {
        switch self {
        case .today:
            TodayScreen()
        case .tasks:
            TasksScreen()
        case .capture:
            CaptureScreen()
        case .insights:
            InsightsScreen()
        case .settings:
            SettingsScreen(isImporting: isImporting)
        }
    }

    @ViewBuilder
    var label: some View {
        switch self {
        case .today:
            Label("Today", systemImage: "circle.grid.2x2")
        case .tasks:
            Label("Tasks", systemImage: "checklist")
        case .capture:
            Label("Capture", systemImage: "plus.circle")
        case .insights:
            Label("Insights", systemImage: "sparkles")
        case .settings:
            Label("Settings", systemImage: "gearshape")
        }
    }
}

@MainActor
@Observable
private final class RouterPath {
    var path: [Route] = []

    func navigate(to route: Route) {
        path.append(route)
    }
}

@MainActor
@Observable
private final class TabRouter {
    private var routers: [AppTab: RouterPath] = [:]

    func router(for tab: AppTab) -> RouterPath {
        if let router = routers[tab] {
            return router
        }
        let router = RouterPath()
        routers[tab] = router
        return router
    }

    func binding(for tab: AppTab) -> Binding<[Route]> {
        let router = router(for: tab)
        return Binding(get: { router.path }, set: { router.path = $0 })
    }
}

private enum Route: Hashable {
    case task(Int)
    case syncSettings
}

private extension View {
    func withAppRouter() -> some View {
        navigationDestination(for: Route.self) { route in
            switch route {
            case .task(let id):
                TaskDetailScreen(taskID: id)
            case .syncSettings:
                SyncSettingsScreen()
            }
        }
    }
}

private struct LockScreen: View {
    @Environment(AppLockStore.self) private var appLock

    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: "lock.shield")
                .font(.system(size: 44, weight: .semibold))
                .foregroundStyle(.blue)
            Text("ORION")
                .font(.largeTitle.weight(.semibold))
            Button {
                Task { await appLock.unlock() }
            } label: {
                Label("Unlock", systemImage: "faceid")
            }
            .buttonStyle(.borderedProminent)
            if let error = appLock.lastError {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            }
        }
        .padding(28)
    }
}

private struct TodayScreen: View {
    @Environment(CompanionStore.self) private var store

    var body: some View {
        List {
            Section {
                ForEach(store.snapshot.overview.metrics.prefix(8)) { metric in
                    MetricRow(metric: metric)
                }
            }
            if let insight = store.snapshot.overview.primaryInsight {
                Section("Signal") {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(insight.title).font(.headline)
                        Text(insight.body).foregroundStyle(.secondary)
                    }
                }
            }
            Section("Calendar") {
                ForEach(store.snapshot.calendar.upcoming.prefix(4)) { event in
                    CalendarEventRow(event: event)
                }
                if store.snapshot.calendar.upcoming.isEmpty {
                    ContentUnavailableView("No upcoming events", systemImage: "calendar")
                }
            }
            Section("Health") {
                SignalGrid(signal: store.snapshot.health)
            }
        }
        .navigationTitle("Today")
        .toolbar {
            Text(store.snapshot.user.displayName)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}

private struct TasksScreen: View {
    @Environment(CompanionStore.self) private var store
    @Environment(RouterPath.self) private var router

    var body: some View {
        List {
            Section {
                LabeledContent("Open", value: "\(store.snapshot.tasks.counts.open)")
                LabeledContent("Done", value: "\(store.snapshot.tasks.counts.done)")
                LabeledContent("Total", value: "\(store.snapshot.tasks.counts.total)")
            }
            Section("Open") {
                ForEach(store.snapshot.tasks.open) { task in
                    Button {
                        router.navigate(to: .task(task.id))
                    } label: {
                        TaskRow(task: task)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .navigationTitle("Tasks")
    }
}

private struct CaptureScreen: View {
    @Environment(CompanionStore.self) private var store
    @Environment(\.modelContext) private var modelContext
    @Query(sort: \CaptureDraft.createdAt, order: .reverse) private var drafts: [CaptureDraft]
    @State private var text = ""

    var body: some View {
        List {
            Section {
                TextEditor(text: $text)
                    .frame(minHeight: 120)
                Button {
                    let submitted = text
                    text = ""
                    Task {
                        await store.capture(submitted, modelContext: modelContext)
                    }
                } label: {
                    Label("Capture", systemImage: "paperplane")
                }
                .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            Section("Queue") {
                ForEach(drafts.prefix(12)) { draft in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(draft.text)
                            .font(.headline)
                        HStack {
                            Text(draft.status.uppercased())
                            Text(draft.createdAt, style: .relative)
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        if let error = draft.lastError {
                            Text(error)
                                .font(.caption)
                                .foregroundStyle(.red)
                        }
                    }
                }
                if drafts.isEmpty {
                    ContentUnavailableView("Nothing queued", systemImage: "tray")
                }
            }
        }
        .navigationTitle("Capture")
    }
}

private struct InsightsScreen: View {
    @Environment(CompanionStore.self) private var store

    var body: some View {
        List(store.snapshot.insights) { insight in
            VStack(alignment: .leading, spacing: 6) {
                Text(insight.title).font(.headline)
                Text(insight.body).foregroundStyle(.secondary)
                Text(insight.domain.uppercased())
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .navigationTitle("Insights")
    }
}

private struct SettingsScreen: View {
    @Environment(CompanionStore.self) private var store
    @Environment(AppLockStore.self) private var appLock
    @Binding var isImporting: Bool

    var body: some View {
        List {
            Section("Sync") {
                NavigationLink(value: Route.syncSettings) {
                    LabeledContent("iCloud", value: store.syncStatus.accountState.label)
                }
                if let lastSyncedAt = store.syncStatus.lastSyncedAt {
                    LabeledContent("Last Sync", value: lastSyncedAt.formatted(date: .abbreviated, time: .shortened))
                }
                LabeledContent("Pending", value: "\(store.syncStatus.pendingCount)")
            }
            Section("Snapshot Fallback") {
                Button {
                    isImporting = true
                } label: {
                    Label("Import Snapshot", systemImage: "doc.badge.plus")
                }
                LabeledContent("Schema", value: "\(store.snapshot.schemaVersion)")
                LabeledContent("Generated", value: store.snapshot.generatedAt)
            }
            if let error = store.lastImportError ?? store.syncStatus.lastError {
                Section("Attention") {
                    Text(error).foregroundStyle(.red)
                }
            }
            Section("Sources") {
                ForEach(store.snapshot.sources) { source in
                    LabeledContent(source.name, value: source.status.uppercased())
                }
            }
            Section {
                Button(role: .none) {
                    appLock.lock()
                } label: {
                    Label("Lock ORION", systemImage: "lock")
                }
            }
        }
        .navigationTitle("Settings")
    }
}

private struct SyncSettingsScreen: View {
    @Environment(CompanionStore.self) private var store
    @Environment(\.modelContext) private var modelContext

    var body: some View {
        List {
            Section {
                LabeledContent("Account", value: store.syncStatus.accountState.label)
                if let checked = store.syncStatus.lastCheckedAt {
                    LabeledContent("Checked", value: checked.formatted(date: .abbreviated, time: .shortened))
                }
                if let synced = store.syncStatus.lastSyncedAt {
                    LabeledContent("Synced", value: synced.formatted(date: .abbreviated, time: .shortened))
                }
                LabeledContent("Pending Captures", value: "\(store.syncStatus.pendingCount)")
            }
            Section {
                Button {
                    Task { await store.refreshCloudKitStatus() }
                } label: {
                    Label("Check iCloud", systemImage: "icloud")
                }
                Button {
                    Task { await store.syncNow(modelContext: modelContext) }
                } label: {
                    Label("Sync Now", systemImage: "arrow.triangle.2.circlepath")
                }
            }
            if let error = store.syncStatus.lastError {
                Section("Last Error") {
                    Text(error).foregroundStyle(.red)
                }
            }
        }
        .navigationTitle("Sync")
    }
}

private struct TaskDetailScreen: View {
    @Environment(CompanionStore.self) private var store
    let taskID: Int

    private var task: TaskPayload? {
        store.snapshot.tasks.open.first { $0.id == taskID }
    }

    var body: some View {
        List {
            if let task {
                Section {
                    Text(task.title).font(.headline)
                    LabeledContent("Status", value: task.status.capitalized)
                    LabeledContent("Priority", value: task.priority.capitalized)
                    if let dueDate = task.dueDate {
                        LabeledContent("Due", value: dueDate)
                    }
                }
                if let notes = task.notes, !notes.isEmpty {
                    Section("Notes") {
                        Text(notes)
                    }
                }
            } else {
                ContentUnavailableView("Task unavailable", systemImage: "checklist")
            }
        }
        .navigationTitle("Task")
    }
}

private struct MetricRow: View {
    let metric: MetricPayload

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                Text(metric.label).font(.caption).foregroundStyle(.secondary)
                Text(metric.value).font(.title3.weight(.semibold))
            }
            Spacer()
            if !metric.delta.isEmpty {
                Text(metric.delta)
                    .font(.callout.monospacedDigit())
                    .foregroundStyle(metric.trend == "down" ? .red : .green)
            }
        }
    }
}

private struct TaskRow: View {
    let task: TaskPayload

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(task.title).font(.headline)
            HStack {
                Text(task.area)
                Text(task.priority.uppercased())
                if let dueDate = task.dueDate {
                    Text(dueDate)
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }
}

private struct CalendarEventRow: View {
    let event: CalendarEventPayload

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(event.title).font(.headline)
            HStack {
                Text(event.allDay ? "All day" : event.startsAt)
                if let calendarName = event.calendarName {
                    Text(calendarName)
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }
}

private struct SignalGrid: View {
    let signal: SignalPayload?

    var body: some View {
        if let latest = signal?.latest, !latest.isEmpty {
            ForEach(latest.keys.sorted().prefix(4), id: \.self) { key in
                LabeledContent(key.replacingOccurrences(of: "_", with: " ").capitalized) {
                    Text(latest[key]?.displayValue ?? "—")
                }
            }
        } else {
            ContentUnavailableView("No health signal", systemImage: "heart.text.square")
        }
    }
}

#Preview {
    ContentView()
        .environment(CompanionStore())
        .environment(AppLockStore())
}
