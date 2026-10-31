import SwiftUI
import AppKit

struct ProgressPage: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("PROGRESS").font(Typeface.label(10.5)).tracking(1.4).foregroundStyle(Theme.tertiary)
                    Text("Where you stand").font(Typeface.largeTitle()).lineLimit(1).minimumScaleFactor(0.8)
                    Text("Skills count as shown only after unaided correct answers on different problems, then again days later.")
                        .font(Typeface.sans(14)).foregroundStyle(Theme.secondary)
                }
                if let courses = model.overview?.courses {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 320), spacing: 18, alignment: .top)], alignment: .leading, spacing: 18) {
                        ForEach(courses) { CourseCard(course: $0) }
                    }
                } else {
                    Text("Sync once to see your progress.").font(Typeface.sans(14)).foregroundStyle(Theme.secondary)
                }
            }
            .padding(.horizontal, 44).padding(.vertical, 40)
            .frame(maxWidth: 1100, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }
}

struct CourseCard: View {
    var course: CourseOverview
    var segments: [(String, Int, Color)] {
        [("Shown again later", course.skills["transfer-checked"] ?? 0, Theme.success),
         ("Shown once", course.skills["demonstrated"] ?? 0, Theme.success.opacity(0.55)),
         ("Learning", course.skills["learning"] ?? 0, Theme.ink.opacity(0.45)),
         ("Not started", course.skills["untested"] ?? 0, Theme.sand)]
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                Text(course.label).font(Typeface.headline(15)).lineLimit(1)
                Text(course.id).font(Typeface.sans(11)).foregroundStyle(Theme.tertiary)
                Spacer()
                if let g = course.grade { Text(g).font(Typeface.mono(15, .medium)) }
            }
            GeometryReader { geo in
                HStack(spacing: 2) {
                    ForEach(Array(segments.enumerated()), id: \.offset) { _, s in
                        if s.1 > 0 {
                            RoundedRectangle(cornerRadius: 3).fill(s.2)
                                .frame(width: max(4, geo.size.width * CGFloat(s.1) / CGFloat(max(1, course.skill_total)) - 2))
                        }
                    }
                }
            }
            .frame(height: 8)
            HStack(spacing: 12) {
                ForEach(Array(segments.enumerated()), id: \.offset) { _, s in
                    if s.1 > 0 {
                        HStack(spacing: 5) {
                            Circle().fill(s.2).frame(width: 7, height: 7)
                            Text("\(s.1) \(s.0.lowercased())").font(Typeface.sans(11)).foregroundStyle(Theme.secondary)
                        }
                    }
                }
            }
            if !course.low_exams.isEmpty {
                Text("Low scores: " + course.low_exams.joined(separator: ", ")).font(Typeface.sans(12)).foregroundStyle(Theme.secondary)
            }
            if course.due_reviews > 0 {
                Text("\(course.due_reviews) spaced review\(course.due_reviews == 1 ? "" : "s") due").font(Typeface.sans(12, .medium))
            }
            if !course.weak.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    SectionTitle(text: "Working on")
                    ForEach(course.weak, id: \.self) { w in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(w.name.capitalized).font(Typeface.sans(13, .medium))
                            if let e = w.error { Text(e).font(Typeface.sans(12)).foregroundStyle(Theme.tertiary).lineLimit(2) }
                        }
                    }
                }
            }
            if let next = course.events.first(where: { $0.days >= 0 }) {
                HStack(spacing: 6) {
                    GlyphView(glyph: next.exam ? .page : .calendar, size: 11)
                    Text(next.name + Theme.sep + dayLabel(next.date, days: next.days)).font(Typeface.sans(12)).lineLimit(1)
                }
                .foregroundStyle(Theme.secondary)
            }
        }
        .card(padding: 20, radius: 16)
    }
}

struct LibraryView: View {
    @EnvironmentObject var model: AppModel
    @State private var query = ""
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("LIBRARY").font(Typeface.label(10.5)).tracking(1.4).foregroundStyle(Theme.tertiary)
                    Text("Search your courses").font(Typeface.largeTitle()).lineLimit(1).minimumScaleFactor(0.8)
                    Text("Canvas pages, announcements, professor notes and Canvas emails, searched by content.")
                        .font(Typeface.sans(14)).foregroundStyle(Theme.secondary)
                }
                HStack(spacing: 10) {
                    GlyphView(glyph: .search, size: 13).foregroundStyle(Theme.tertiary)
                    TextField("Try “linked list delete” or “exam 2”", text: $query)
                        .textFieldStyle(.plain).font(Typeface.sans(15))
                        .onSubmit { model.search(query) }
                }
                .padding(.horizontal, 16).padding(.vertical, 12)
                .background(Theme.raised, in: RoundedRectangle(cornerRadius: 22))
                .overlay(RoundedRectangle(cornerRadius: 22).strokeBorder(Theme.ring, lineWidth: 1))
                .onChange(of: query) { _, new in if new.count >= 3 { model.search(new) } }
                VStack(spacing: 0) {
                    ForEach(model.searchHits) { hit in
                        Button { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: hit.path)]) } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    Text(URL(fileURLWithPath: hit.path).deletingPathExtension().lastPathComponent).font(Typeface.sans(13, .medium)).lineLimit(1)
                                    Spacer()
                                    Text(Theme.courseLabel(hit.course)).font(Typeface.sans(11)).foregroundStyle(Theme.tertiary)
                                }
                                InlineText(text: hit.snippet.replacingOccurrences(of: "[", with: "**").replacingOccurrences(of: "]", with: "**"), size: 12.5, color: Theme.secondary)
                                    .lineLimit(3)
                            }
                            .padding(14).contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        Rectangle().fill(Theme.border).frame(height: 1)
                    }
                }
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 14))
                .opacity(model.searchHits.isEmpty ? 0 : 1)
            }
            .padding(.horizontal, 44).padding(.vertical, 40)
            .frame(maxWidth: 900, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }
}
