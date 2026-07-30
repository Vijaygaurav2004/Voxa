import SwiftUI
import AppKit

/// Home: now playing, weather, and today's calendar — three glanceable cards.
struct PerchHomeTab: View {
    @ObservedObject private var player = PerchNowPlaying.shared
    @ObservedObject private var weather = PerchWeather.shared
    @ObservedObject private var calendar = PerchCalendar.shared
    @ObservedObject private var settings = PerchSettings.shared

    var body: some View {
        HStack(spacing: 10) {
            nowPlayingCard.frame(maxWidth: .infinity)
            weatherCard.frame(maxWidth: .infinity)
            calendarCard.frame(maxWidth: .infinity)
        }
        .padding(12)
        .onAppear {
            player.refresh()
            weather.refreshIfStale()
            calendar.refresh()
        }
    }

    // MARK: Now playing

    private var nowPlayingCard: some View {
        VStack(spacing: 9) {
            // A bright card floating inside the dark one — the strongest bit of
            // contrast in the whole perch, and what makes the track read first.
            HStack(spacing: 10) {
                artwork
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 4) {
                        Text(player.hasTrack ? (player.artist.isEmpty ? player.app : player.artist)
                                             : "Nothing playing")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(.black.opacity(0.5))
                            .lineLimit(1)
                        if player.hasTrack {
                            Image(systemName: "heart.fill")
                                .font(.system(size: 7)).foregroundStyle(.black.opacity(0.35))
                        }
                    }
                    Text(player.hasTrack ? player.title : "Spotify or Music")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(.black)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .padding(8)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(Color.white)
                    .shadow(color: .black.opacity(0.28), radius: 8, y: 3)
            )

            // Transport: prev/next grouped in one well, play separated.
            HStack(spacing: 8) {
                HStack(spacing: 0) {
                    transport("backward.fill") { player.previous() }
                    transport("forward.fill") { player.next() }
                }
                .perchWell(radius: 13)

                transport(player.isPlaying ? "pause.fill" : "play.fill") { player.playPause() }
                    .frame(maxWidth: .infinity)
                    .perchWell(radius: 13)
            }
            .frame(height: 34)
        }
        .padding(10)
        .perchSurface()
    }

    @ViewBuilder private var artwork: some View {
        if let image = player.artwork {
            Image(nsImage: image).resizable().aspectRatio(contentMode: .fill)
                .frame(width: 40, height: 40)
                .clipShape(RoundedRectangle(cornerRadius: 11, style: .continuous))
        } else {
            RoundedRectangle(cornerRadius: 11, style: .continuous)
                .fill(LinearGradient(colors: [settings.accent.color.opacity(0.9),
                                              settings.accent.color.opacity(0.5)],
                                     startPoint: .topLeading, endPoint: .bottomTrailing))
                .frame(width: 40, height: 40)
                .overlay(Image(systemName: "music.note")
                    .font(.system(size: 15, weight: .semibold)).foregroundStyle(.white))
        }
    }

    private func transport(_ symbol: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Perch.text)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .frame(minWidth: 40)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    // MARK: Weather

    private var weatherCard: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 6) {
                VStack(alignment: .leading, spacing: 1) {
                    HStack(alignment: .top, spacing: 1) {
                        Text(weather.temperature.map(String.init) ?? (weather.failed ? "—" : "··"))
                            .font(.system(size: 38, weight: .bold))
                            .foregroundStyle(Perch.text)
                        Text("°C")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(Perch.text)
                            .padding(.top, 5)
                    }
                    if let low = weather.low, let high = weather.high {
                        Text("+\(low)°C   +\(high)°C")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(Perch.subtle)
                    }
                }
                Spacer(minLength: 0)
                Image(systemName: weather.symbol)
                    .font(.system(size: 38))
                    .symbolRenderingMode(.multicolor)
                    .shadow(color: .black.opacity(0.4), radius: 6, y: 2)
            }

            Spacer(minLength: 8)

            HStack(spacing: 6) {
                pill(weather.city.isEmpty ? (weather.failed ? "Offline" : "Locating…") : weather.city,
                     symbol: "location.fill")
                if !weather.summary.isEmpty { pill(weather.summary, symbol: weather.symbol) }
                Spacer(minLength: 0)
            }
        }
        .padding(13)
        .frame(maxHeight: .infinity)
        .perchSurface()
        .contentShape(Rectangle())
        .onTapGesture { Task { await weather.refresh() } }
        .help("Click to refresh")
    }

    private func pill(_ text: String, symbol: String) -> some View {
        HStack(spacing: 4) {
            Image(systemName: symbol).font(.system(size: 9))
            Text(text).font(.system(size: 10, weight: .semibold)).lineLimit(1)
        }
        .foregroundStyle(Perch.text.opacity(0.85))
        .padding(.horizontal, 9).padding(.vertical, 5)
        .background(Capsule().fill(Perch.inner))
        .overlay(Capsule().strokeBorder(Perch.stroke, lineWidth: 1))
    }

    // MARK: Calendar

    private var calendarCard: some View {
        VStack(spacing: 9) {
            dateStrip
            HStack(spacing: 8) {
                Button { calendar.openCalendarApp() } label: {
                    Image(systemName: "plus")
                        .font(.system(size: 15, weight: .bold)).foregroundStyle(Perch.text)
                        .frame(width: 42, height: 42)
                        .background(Circle().fill(Perch.inner))
                        .overlay(Circle().strokeBorder(Perch.edge, lineWidth: 1))
                }
                .buttonStyle(.plain)
                .help("Open Calendar")

                eventRow
            }
        }
        .padding(11)
        .perchSurface()
    }

    private var dateStrip: some View {
        let today = Date()
        let cal = Calendar.current
        let offsets = [-3, -2, -1, 0, 1, 2, 3]

        return HStack(spacing: 0) {
            ForEach(offsets, id: \.self) { offset in
                let date = cal.date(byAdding: .day, value: offset, to: today) ?? today
                let number = cal.component(.day, from: date)
                if offset == 0 {
                    VStack(spacing: -1) {
                        Text(monthWeekday(today))
                            .font(.system(size: 8, weight: .bold))
                            .foregroundStyle(.black.opacity(0.55))
                        Text("\(number)")
                            .font(.system(size: 21, weight: .heavy))
                            .foregroundStyle(.black)
                    }
                    .frame(width: 44, height: 48)
                    .background(
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .fill(Color.white)
                            .shadow(color: .black.opacity(0.3), radius: 7, y: 2)
                    )
                    .padding(.horizontal, 3)
                } else {
                    Text("\(number)")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(abs(offset) == 1 ? Perch.subtle : Perch.faint)
                        .frame(maxWidth: .infinity)
                }
            }
        }
    }

    private func monthWeekday(_ date: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "MMM, E"
        return f.string(from: date)
    }

    @ViewBuilder private var eventRow: some View {
        if !calendar.checked {
            eventPlaceholder("Checking…", detail: "")
        } else if !calendar.authorised {
            Button { openCalendarPrivacy() } label: {
                eventPlaceholder("Allow Calendar access", detail: "Click to open Settings")
            }
            .buttonStyle(.plain)
        } else if let event = calendar.events.first {
            HStack(spacing: 8) {
                Image(systemName: "calendar")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(event.color)
                VStack(alignment: .leading, spacing: 0) {
                    Text(event.title)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(Perch.text).lineLimit(1)
                    Text(event.timeText)
                        .font(.system(size: 9, weight: .medium)).foregroundStyle(Perch.subtle)
                }
                Spacer(minLength: 0)
                if calendar.events.count > 1 {
                    Text("+\(calendar.events.count - 1)")
                        .font(.system(size: 9, weight: .bold)).foregroundStyle(Perch.faint)
                }
            }
            .padding(.horizontal, 11).frame(height: 42)
            .frame(maxWidth: .infinity, alignment: .leading)
            .perchWell()
            .overlay(RoundedRectangle(cornerRadius: Perch.innerRadius, style: .continuous)
                .strokeBorder(Perch.stroke, lineWidth: 1))
        } else {
            eventPlaceholder("Nothing today", detail: "")
        }
    }

    private func eventPlaceholder(_ title: String, detail: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title).font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Perch.subtle).lineLimit(1)
            if !detail.isEmpty {
                Text(detail).font(.system(size: 9)).foregroundStyle(Perch.faint).lineLimit(1)
            }
        }
        .padding(.horizontal, 11).frame(height: 42)
        .frame(maxWidth: .infinity, alignment: .leading)
        .perchWell()
        .overlay(RoundedRectangle(cornerRadius: Perch.innerRadius, style: .continuous)
            .strokeBorder(Perch.stroke, lineWidth: 1))
        .contentShape(Rectangle())
    }

    private func openCalendarPrivacy() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars") {
            NSWorkspace.shared.open(url)
        }
    }
}
