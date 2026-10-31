import SwiftUI

// MARK: - Plugins
//
// Pick what Genesis can use. Off until chosen; turning one off stops it right away.

struct PluginCard: View {
    @EnvironmentObject var model: AppModel
    var plugin: GenesisPlugin
    @State private var hover = false
    var body: some View {
        let on = model.plugins.contains(plugin.id)
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: plugin.symbol)
                .font(.system(size: 17, weight: .regular))
                .foregroundStyle(on ? Theme.focus : Theme.secondary)
                .frame(width: 38, height: 38)
                .background(on ? Theme.focus.opacity(0.12) : Theme.well, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(plugin.name).font(Typeface.sans(14, .medium))
                    if plugin.suggested && !on { Text("Suggested").font(Typeface.sans(10.5, .medium)).foregroundStyle(Theme.focus).padding(.horizontal, 7).padding(.vertical, 2).background(Theme.focus.opacity(0.1), in: Capsule()) }
                }
                Text(plugin.summary).font(Typeface.sans(12.5)).foregroundStyle(Theme.secondary)
                if hover || on { Text(plugin.detail).font(Typeface.sans(11.5)).foregroundStyle(Theme.tertiary).fixedSize(horizontal: false, vertical: true).transition(.opacity) }
            }
            Spacer(minLength: 8)
            Button { withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { model.setPlugin(plugin.id, !on) } } label: {
                HStack(spacing: 5) {
                    Image(systemName: on ? "checkmark" : "plus").font(.system(size: 10.5, weight: .bold))
                    Text(on ? "Added" : "Add")
                }
                .font(Typeface.sans(12, .medium))
                .foregroundStyle(on ? Theme.secondary : Color.white)
                .padding(.horizontal, 12).padding(.vertical, 6)
                .background(Capsule().fill(on ? Theme.well : Theme.focus))
            }
            .buttonStyle(.plain)
            .help(on ? "Remove \(plugin.name)" : "Add \(plugin.name)")
        }
        .padding(14)
        .background(Theme.raised, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(on ? Theme.focus.opacity(0.35) : Theme.borderStrong, lineWidth: 1))
        .onHover { h in withAnimation(.easeOut(duration: 0.15)) { hover = h } }
    }
}

struct PluginList: View {
    var body: some View {
        VStack(spacing: 10) { ForEach(GenesisPlugin.catalog) { PluginCard(plugin: $0) } }
    }
}

/// First launch: pick what you need. Nothing is on until you add it.
struct PluginPicker: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Make Genesis yours.").font(Typeface.serif(30))
                Text("Pick where Genesis gathers what it needs to build your brief: assignments, documents, dates and announcements. Anything you skip never runs, and you can change this any time in Settings › Plugins.")
                    .font(Typeface.sans(13)).foregroundStyle(Theme.secondary).fixedSize(horizontal: false, vertical: true)
            }
            ScrollView { PluginList().padding(.vertical, 2) }.frame(maxHeight: 430)
            HStack {
                Text(model.plugins.isEmpty ? "Nothing added yet" : "\(model.plugins.count) added").font(Typeface.sans(12)).foregroundStyle(Theme.tertiary)
                Spacer()
                Button(model.plugins.isEmpty ? "Skip for now" : "Done") { model.finishPluginChoice() }.primaryAction()
            }
        }
        .padding(28)
        .frame(width: 560)
    }
}
