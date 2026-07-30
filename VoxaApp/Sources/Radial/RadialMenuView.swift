import SwiftUI
import AppKit

// MARK: - Geometry

enum RadialGeometry {
    static let hubRadius: CGFloat = 96
    /// Thickness of the root ring.
    static let rootThickness: CGFloat = 100
    /// Thickness of each branched-out fan.
    static let branchThickness: CGFloat = 86
    static let ringGap: CGFloat = 7

    static func inner(ring: Int, scale: Double) -> CGFloat {
        var radius = hubRadius
        for level in 0..<max(0, ring) {
            radius += (level == 0 ? rootThickness : branchThickness) + ringGap
        }
        return radius * scale
    }

    static func outer(ring: Int, scale: Double) -> CGFloat {
        inner(ring: ring, scale: scale)
            + (ring == 0 ? rootThickness : branchThickness) * scale
    }

    /// Keep-on-screen margin. Assumes one branched ring may be open, which is
    /// the common case; deeper fans simply clip at the display edge.
    static func clampMargin(scale: Double) -> CGFloat {
        outer(ring: 1, scale: scale) + 20
    }

    /// Clamp one axis of the wheel's centre.
    ///
    /// Naively doing `min(max(v, m), extent - m)` degenerates when the display
    /// is shorter than two margins: it collapses to exactly `m` for every input,
    /// which pins the wheel against the leading edge, freezes dragging on that
    /// axis, and clips the ring even when a centred wheel would have fit. So we
    /// step the margin down — full (fan open) → root ring only → give up and
    /// centre — and only then clamp.
    static func clampAxis(_ value: CGFloat, extent: CGFloat, scale: Double) -> CGFloat {
        var margin = clampMargin(scale: scale)
        if extent < margin * 2 { margin = outer(ring: 0, scale: scale) + 20 }
        if extent < margin * 2 { return extent / 2 }
        return min(max(value, margin), extent - margin)
    }

    /// A point on the wheel. `angle` runs clockwise from 12 o'clock, matching
    /// both the drawing order and `RadialController.hitTest`.
    static func point(center: CGPoint, radius: CGFloat, angle: Double) -> CGPoint {
        let radians = (angle - 90) * .pi / 180
        return CGPoint(x: center.x + radius * cos(radians),
                       y: center.y + radius * sin(radians))
    }
}

/// One wedge of a ring. Drawn in absolute coordinates so the wheel can sit
/// anywhere inside the full-screen overlay without nested coordinate spaces.
struct DonutSlice: Shape {
    let center: CGPoint
    let inner: CGFloat
    let outer: CGFloat
    let startDegrees: Double
    let endDegrees: Double
    /// Angular padding (degrees) so neighbouring wedges don't touch.
    var gap: Double = 0.6

    func path(in _: CGRect) -> Path {
        var path = Path()
        // Never let the gap invert a thin wedge.
        let safeGap = min(gap, max(0, (endDegrees - startDegrees) / 3))
        let start = Angle.degrees(startDegrees + safeGap - 90)
        let end   = Angle.degrees(endDegrees - safeGap - 90)
        path.addArc(center: center, radius: outer, startAngle: start, endAngle: end, clockwise: false)
        path.addArc(center: center, radius: inner, startAngle: end, endAngle: start, clockwise: true)
        path.closeSubpath()
        return path
    }
}

// MARK: - The wheel

struct RadialMenuView: View {
    @ObservedObject var controller: RadialController
    @ObservedObject var settings = RadialSettings.shared

    /// Called when the overlay should close (Esc, backdrop click, launch).
    var onDismiss: () -> Void

    @State private var hubHot = false
    @State private var appeared = false
    @State private var dragOrigin: CGPoint?

    private var center: CGPoint { controller.center }
    /// For the `RadialGeometry` API, which takes a Double.
    private var scale: Double { controller.scale }
    /// For layout arithmetic, which is all CGFloat.
    private var s: CGFloat { CGFloat(controller.scale) }

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .topLeading) {
                backdrop
                ForEach(Array(controller.rings.enumerated()), id: \.element.id) { index, _ in
                    ringLayer(index)
                }
                ForEach(Array(controller.rings.enumerated()), id: \.element.id) { index, _ in
                    contentsLayer(index)
                }
                hub(in: geo.size)
            }
            .onContinuousHover(coordinateSpace: .local) { phase in
                guard !controller.isDragging else { return }
                switch phase {
                case .active(let point): updateHover(at: point)
                case .ended: controller.setHover(nil); hubHot = false
                }
            }
            .contentShape(Rectangle())
            .onTapGesture { handleTap() }
        }
        .ignoresSafeArea()
        .scaleEffect(appeared ? 1 : 0.88, anchor: .center)
        .opacity(appeared ? 1 : 0)
        .animation(.spring(response: 0.26, dampingFraction: 0.78), value: appeared)
        .onAppear { appeared = true }
        .onChange(of: controller.generation) { _, _ in
            appeared = false
            withAnimation(.spring(response: 0.26, dampingFraction: 0.78)) { appeared = true }
        }
    }

    // MARK: Layers

    /// Full-screen click target so backdrop clicks dismiss.
    ///
    /// Deliberately invisible — no scrim. The wheel should sit over the desktop
    /// the way ⌘-Tab's switcher does, leaving everything behind it untouched.
    /// The near-zero opacity (rather than `.clear`) is purely to guarantee the
    /// layer still takes part in hit testing.
    private var backdrop: some View {
        Color.black.opacity(0.001).contentShape(Rectangle())
    }

    @ViewBuilder
    private func ringLayer(_ index: Int) -> some View {
        let inner = RadialGeometry.inner(ring: index, scale: scale)
        let outer = RadialGeometry.outer(ring: index, scale: scale)
        let items = controller.visibleItems(ring: index)
        let l = controller.layout(ring: index)
        let count = index == 0 ? controller.sliceCount(ring: 0) : items.count

        ZStack {
            // The root ring gets a solid plate; fans are drawn wedge by wedge so
            // the desktop still shows between branches.
            if index == 0 {
                Circle()
                    .fill(.ultraThinMaterial)
                    .environment(\.colorScheme, .dark)
                    .frame(width: outer * 2, height: outer * 2)
                    .position(center)
                    .mask(donutMask(inner: inner, outer: outer))
                Circle()
                    .fill(Color.black.opacity(0.55))
                    .frame(width: outer * 2, height: outer * 2)
                    .position(center)
                    .mask(donutMask(inner: inner, outer: outer))
            }

            ForEach(0..<max(0, count), id: \.self) { slot in
                let hot = controller.hovered == RadialTarget(ring: index, slot: slot)
                let branched = isBranchParent(ring: index, slot: slot)
                let shape = DonutSlice(
                    center: center, inner: inner, outer: outer,
                    startDegrees: l.start + Double(slot) * l.perSlice,
                    endDegrees: l.start + Double(slot + 1) * l.perSlice
                )
                shape
                    .fill(sliceFill(hot: hot, branched: branched, isRoot: index == 0))
                    .overlay(shape.stroke(Color.white.opacity(hot || branched ? 0.35 : 0.12), lineWidth: 1))
                    .animation(.easeOut(duration: 0.12), value: hot)
            }

            if index == 0 {
                Circle()
                    .strokeBorder(Color.white.opacity(0.22), lineWidth: 1)
                    .frame(width: outer * 2, height: outer * 2)
                    .position(center)
            }
        }
        .allowsHitTesting(false)
    }

    /// White for the hovered slice, a lifted tint for a folder that's branched
    /// open, and (for fans) a dark plate so they read against the desktop.
    private func sliceFill(hot: Bool, branched: Bool, isRoot: Bool) -> some ShapeStyle {
        if hot { return AnyShapeStyle(Color.white) }
        if branched { return AnyShapeStyle(Color.white.opacity(0.16)) }
        return isRoot ? AnyShapeStyle(Color.white.opacity(0.001))
                      : AnyShapeStyle(Color.black.opacity(0.72))
    }

    /// True when this folder slice is the one currently fanned out.
    private func isBranchParent(ring: Int, slot: Int) -> Bool {
        controller.rings.count > ring + 1 && controller.rings[ring + 1].parentSlot == slot
    }

    private func donutMask(inner: CGFloat, outer: CGFloat) -> some View {
        ZStack {
            Circle().frame(width: outer * 2, height: outer * 2).position(center)
            Circle().frame(width: inner * 2, height: inner * 2).position(center)
                .blendMode(.destinationOut)
        }
        .compositingGroup()
    }

    @ViewBuilder
    private func contentsLayer(_ index: Int) -> some View {
        let items = controller.visibleItems(ring: index)
        let inner = RadialGeometry.inner(ring: index, scale: scale)
        let outer = RadialGeometry.outer(ring: index, scale: scale)

        ForEach(Array(items.enumerated()), id: \.element.id) { slot, item in
            let angle = controller.centreAngle(ring: index, slot: slot)
            let hot = controller.hovered == RadialTarget(ring: index, slot: slot)
            let tint: Color = hot ? .black : .white

            ZStack {
                VStack(spacing: 3) {
                    icon(for: item, tint: tint)
                    if settings.showLabels {
                        Text(item.title)
                            .font(.system(size: 11 * min(1.25, s), weight: hot ? .semibold : .medium))
                            .foregroundStyle(tint)
                            .lineLimit(1)
                            .frame(maxWidth: 92 * s)
                    }
                    if item.isSubmenu {
                        Text("•••")
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(tint.opacity(0.55))
                    }
                }
                .position(RadialGeometry.point(center: center,
                                               radius: (inner + outer) / 2 + 4 * s,
                                               angle: angle))

                // Only the root ring carries shortcut keys; a fan repeating
                // "1, 2, 3…" would be ambiguous with the ring beneath it.
                if index == 0 {
                    Text(controller.shortcutLabel(ring: index, slot: slot).uppercased())
                        .font(.system(size: 10 * min(1.2, s), weight: .semibold, design: .rounded))
                        .foregroundStyle(tint.opacity(0.55))
                        .position(RadialGeometry.point(center: center,
                                                       radius: outer - 16 * s,
                                                       angle: angle))
                }
            }
        }
        .allowsHitTesting(false)
    }

    @ViewBuilder
    private func icon(for item: RadialItem, tint: Color) -> some View {
        let side = 28 * min(1.4, s)
        if let appIcon = RadialIcon.appIcon(for: item) {
            Image(nsImage: appIcon).resizable().interpolation(.high)
                .frame(width: side, height: side)
        } else {
            Image(systemName: item.symbol)
                .font(.system(size: 18 * min(1.35, s), weight: .medium))
                .foregroundStyle(tint)
                .frame(height: side)
        }
    }

    // MARK: Hub (also the drag handle)

    private func hub(in size: CGSize) -> some View {
        let radius = RadialGeometry.hubRadius * s

        return ZStack {
            Circle()
                .fill(.ultraThinMaterial)
                .environment(\.colorScheme, .dark)
                .overlay(Circle().fill(Color.black.opacity(0.5)))
                .overlay(Circle().strokeBorder(
                    hubHot || controller.isDragging ? Color.white.opacity(0.5) : Color.white.opacity(0.16),
                    lineWidth: 1))
                .frame(width: radius * 2 - 6, height: radius * 2 - 6)

            VStack(spacing: 5) {
                if controller.canGoBack {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(.white.opacity(hubHot ? 0.95 : 0.45))
                }

                Text(hubTitle)
                    .font(.system(size: 17 * min(1.2, s), weight: .semibold))
                    .foregroundStyle(.white)
                    .lineLimit(1)
                    .frame(maxWidth: radius * 1.6)

                pageReadout
            }
            .padding(.horizontal, 10)
            .allowsHitTesting(controller.pageCount(ring: controller.activeRingIndex) > 1)
        }
        .frame(width: radius * 2, height: radius * 2)
        .position(center)
        // Tap the hub to go back. Owned by the hub itself so the ancestor's
        // tap handler never also fires for the same click.
        .onTapGesture {
            if controller.canGoBack { controller.goBack() }
        }
        // Drag the hub to move the whole wheel. The threshold is deliberately
        // well above click jitter: a wobbly click must not pin the wheel, and
        // we only write the pin when a drag actually started.
        .simultaneousGesture(
            DragGesture(minimumDistance: 12, coordinateSpace: .local)
                .onChanged { value in
                    if dragOrigin == nil {
                        dragOrigin = controller.center
                        controller.beginDrag()
                    }
                    guard let origin = dragOrigin else { return }
                    controller.drag(to: CGPoint(x: origin.x + value.translation.width,
                                                y: origin.y + value.translation.height),
                                    in: size)
                }
                .onEnded { _ in
                    let reallyDragged = dragOrigin != nil
                    dragOrigin = nil
                    if reallyDragged { controller.endDrag(in: size) }
                }
        )
    }

    @ViewBuilder
    private var pageReadout: some View {
        let active = controller.activeRingIndex
        if controller.pageCount(ring: active) > 1 {
            HStack(spacing: 12) {
                pageArrow("chevron.left") { controller.previousPage() }
                Text("\((controller.ring(active)?.page ?? 0) + 1) / \(controller.pageCount(ring: active))")
                    .font(.system(size: 13, weight: .medium, design: .rounded))
                    .foregroundStyle(.white.opacity(0.75)).monospacedDigit()
                pageArrow("chevron.right") { controller.nextPage() }
            }
        } else if let hovered = controller.hovered {
            Text("‹ \(controller.globalIndex(hovered)) / \(controller.ring(hovered.ring)?.items.count ?? 0) ›")
                .font(.system(size: 13, weight: .medium, design: .rounded))
                .foregroundStyle(.white.opacity(0.6)).monospacedDigit()
        } else {
            Text(hubHint)
                .font(.system(size: 10.5))
                .foregroundStyle(.white.opacity(0.4))
                .lineLimit(1)
        }
    }

    private func pageArrow(_ symbol: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(.white.opacity(0.75))
                .frame(width: 22, height: 22)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private var hubTitle: String {
        controller.hoveredItem?.title ?? controller.levelTitle
    }

    private var hubHint: String {
        if controller.isDragging { return "Drop to pin" }
        if controller.canGoBack { return "Click to go back" }
        return "Drag to move · scroll to resize"
    }

    // MARK: Interaction

    private func updateHover(at point: CGPoint) {
        controller.setHover(controller.hitTest(point))
        let inHub = controller.isInHub(point)
        if hubHot != inHub { hubHot = inHub }
    }

    private func handleTap() {
        // A drag that just finished must not also read as a click.
        guard !controller.isDragging, dragOrigin == nil else { return }
        if let hovered = controller.hovered {
            if controller.activate(hovered) { onDismiss() }
            return
        }
        // Hub taps are handled by the hub's own gesture; anything else out here
        // is the backdrop.
        guard !hubHot else { return }
        onDismiss()
    }
}
