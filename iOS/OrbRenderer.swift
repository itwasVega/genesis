import SwiftUI
import MetalKit
import QuartzCore

// MARK: - Genesis orb (Metal)
//
// Implements the "Genesis orb" handoff (Design/Orb/HANDOFF-README.md):
// - The reference photograph (Resources/OrbReference.png) is the visual source of truth.
//   A fragment shader samples it with *live* interior motion: a slowly orbiting noise field
//   and a small reflection sweep, both masked to zero at the rim so the glass edge stays still.
// - The silhouette moves only by the README contour formula (< 0.55% of the radius).
// - Success ("fed") is an explicit event: light rises over ~1.2 s and settles over ~2.8 s,
//   blending from the current value on repeats (never accumulating past 1).
// - Bloom comes from the orb's own light (Resources/OrbBloom.png, a wide blur of the
//   reference), so it is soft and strongest where the orb is brightest, never a ring.
// Shader math was prototyped against the reference animation in Design/Orb/shader_prototype.py.

/// Public, conservative controls. Everything else is internal tuning.
struct OrbConfiguration: Equatable {
    var intensity: Double = 1      // overall brightness 0...1
    var energy: Double = 1         // amount of interior motion 0...1
    var interactionEnabled = true

    /// NaN/∞ become safe defaults; everything is clamped to 0...1.
    var sanitized: OrbConfiguration {
        func clean(_ v: Double, _ fallback: Double) -> Double { v.isFinite ? min(1, max(0, v)) : fallback }
        return OrbConfiguration(intensity: clean(intensity, 1), energy: clean(energy, 1), interactionEnabled: interactionEnabled)
    }
}

/// Internal tuning, centralised.
enum OrbTuning {
    static let viewHalfSize: Float = 1.55      // view half-width in orb radii (room for bloom)
    static let flowAmplitude: Float = 0.34      // interior refraction drift, in orb radii
    static let sweep: Float = 0.13              // reflection sweep, radians
    static let flowPeriod: Double = 9           // seconds per closed orbit of the flow field
    static let rise: Double = 1.2, settle: Double = 2.8               // success timing
    static let reducedRise: Double = 1.8, reducedSettle: Double = 3.4 // gentler, non-flashing
    // Reference geometry, measured by circle fit on reference.jpg (1280 px): centre (640.16, 630.39), r 396.18.
    static let center = SIMD2<Float>(640.16 / 1280, 630.39 / 1280)
    static let radius: Float = 396.18 / 1280
}

/// Renderer timing, readable from Diagnostics.
final class OrbStats: @unchecked Sendable {
    static let shared = OrbStats()
    private let lock = NSLock()
    private var gpu: [Double] = [], interval: [Double] = []
    func record(gpuMs: Double? = nil, intervalMs: Double? = nil) {
        lock.lock(); defer { lock.unlock() }
        if let g = gpuMs, g.isFinite, g > 0 { gpu.append(g); if gpu.count > 240 { gpu.removeFirst(gpu.count - 240) } }
        if let i = intervalMs, i.isFinite, i > 0 { interval.append(i); if interval.count > 240 { interval.removeFirst(interval.count - 240) } }
    }
    /// Glow envelope samples (seconds since the first success, value), for verifying timing.
    private var trace: [(Double, Double)] = [], traceStart: Double?
    func traceGlow(_ g: Double, at t: Double) {
        lock.lock(); defer { lock.unlock() }
        guard g > 0.0005 || traceStart != nil, trace.count < 2000 else { return }
        if traceStart == nil { traceStart = t }
        trace.append((t - traceStart!, g))
    }
    var glowTrace: String {
        lock.lock(); defer { lock.unlock() }
        return trace.enumerated().filter { $0.offset % 6 == 0 }.map { String(format: "%.2f %.3f", $0.element.0, $0.element.1) }.joined(separator: "\n")
    }
    var summary: String {
        lock.lock(); defer { lock.unlock() }
        guard !gpu.isEmpty, !interval.isEmpty else { return "orb: no frames yet" }
        let g = gpu.reduce(0, +) / Double(gpu.count), worst = gpu.max() ?? 0
        let fps = 1000 / (interval.reduce(0, +) / Double(interval.count))
        return String(format: "orb: GPU %.2f ms avg, %.2f ms worst, %.0f fps (last %d frames)", g, worst, fps, gpu.count)
    }
}

/// SwiftUI entry point. `successID` changing is the explicit "fed" event; `pressID` changing
/// gives the small press response. Both are ignored when unchanged, so ordinary view updates
/// never re-trigger.
struct OrbView: View {
    var successID: Int = 0
    var pressID: Int = 0
    var configuration = OrbConfiguration()

    var body: some View {
        OrbMetalView(successID: successID, pressID: pressID, configuration: configuration.sanitized)
            .aspectRatio(1, contentMode: .fit)        // always square: never stretched
            .accessibilityHidden(true)
    }
}

struct OrbMetalView: UIViewRepresentable {
    var successID: Int
    var pressID: Int
    var configuration: OrbConfiguration
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeCoordinator() -> OrbEngine { OrbEngine() }

    func makeUIView(context: Context) -> MTKView {
        let view = MTKView(frame: .zero, device: context.coordinator.device)
        view.colorPixelFormat = .bgra8Unorm
        view.clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 0)
        view.framebufferOnly = true
        view.isOpaque = false            // the bloom fades into whatever is behind; no square
        view.backgroundColor = .clear
        view.preferredFramesPerSecond = 60
        view.enableSetNeedsDisplay = false
        view.isPaused = false
        view.delegate = context.coordinator
        context.coordinator.attach(view)
        context.coordinator.lastSuccessID = successID     // don't glow on first appearance
        context.coordinator.lastPressID = pressID
        return view
    }

    func updateUIView(_ view: MTKView, context: Context) {
        let engine = context.coordinator
        engine.configuration = configuration
        let reduced = reduceMotion || UserDefaults.standard.bool(forKey: "genesisReduceMotion")  // test override
        engine.reduceMotion = reduced
        view.preferredFramesPerSecond = reduced ? 30 : 60
        if successID != engine.lastSuccessID { engine.lastSuccessID = successID; engine.triggerSuccess() }
        if pressID != engine.lastPressID { engine.lastPressID = pressID; engine.press() }
    }

    static func dismantleUIView(_ view: MTKView, coordinator: OrbEngine) {
        view.isPaused = true
        view.delegate = nil
        coordinator.detach()
    }
}

/// Owns Metal resources and all animation state. Elapsed-time based, refresh-rate independent.
final class OrbEngine: NSObject, MTKViewDelegate {
    let device = MTLCreateSystemDefaultDevice()
    private var queue: MTLCommandQueue?
    private var pipeline: MTLRenderPipelineState?
    private var reference: MTLTexture?
    private var bloom: MTLTexture?
    private weak var view: MTKView?
    private var observers: [NSObjectProtocol] = []

    var configuration = OrbConfiguration()
    var reduceMotion = false
    var lastSuccessID = 0, lastPressID = 0

    // Animation state
    private var time: Double = 0                 // advances only while moving
    private var lastFrame: CFTimeInterval = 0
    private var glow: Double = 0
    private var glowFrom: Double = 0
    private var glowStart: CFTimeInterval = -1000
    private var kick: Double = 0

    override init() {
        super.init()
        guard let device else { return }
        queue = device.makeCommandQueue()
        do {
            let library = try device.makeLibrary(source: OrbEngine.shader, options: nil)
            let desc = MTLRenderPipelineDescriptor()
            desc.vertexFunction = library.makeFunction(name: "orb_vertex")
            desc.fragmentFunction = library.makeFunction(name: "orb_fragment")
            desc.colorAttachments[0].pixelFormat = .bgra8Unorm
            pipeline = try device.makeRenderPipelineState(descriptor: desc)
        } catch { NSLog("Genesis orb: shader failed: \(error)") }
        let loader = MTKTextureLoader(device: device)
        let opts: [MTKTextureLoader.Option: Any] = [.SRGB: false, .generateMipmaps: true]
        if let url = Bundle.main.url(forResource: "OrbReference", withExtension: "png") { reference = try? loader.newTexture(URL: url, options: opts) }
        if let url = Bundle.main.url(forResource: "OrbBloom", withExtension: "png") { bloom = try? loader.newTexture(URL: url, options: opts) }
    }

    func attach(_ view: MTKView) {
        self.view = view
        // Stop GPU work in the background; resume without a time jump (dt is clamped).
        let nc = NotificationCenter.default
        observers.append(nc.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in
            self?.view?.isPaused = true
        })
        observers.append(nc.addObserver(forName: UIApplication.willEnterForegroundNotification, object: nil, queue: .main) { [weak self] _ in
            self?.lastFrame = 0; self?.view?.isPaused = false
        })
    }

    func detach() {
        observers.forEach { NotificationCenter.default.removeObserver($0) }
        observers.removeAll()
        reference = nil; bloom = nil; pipeline = nil
    }

    deinit { observers.forEach { NotificationCenter.default.removeObserver($0) } }

    // MARK: Events

    /// Starts the fed glow from wherever it currently is (no snapping, never above 1).
    func triggerSuccess() {
        glowFrom = glow
        glowStart = CACurrentMediaTime()
        if !reduceMotion { kick = min(kick + 0.6, 1.2) }
    }

    func press() {
        guard configuration.interactionEnabled, !reduceMotion else { return }
        kick = min(kick + 0.9, 1.2)
    }

    private func glowValue(now: CFTimeInterval) -> Double {
        let rise = reduceMotion ? OrbTuning.reducedRise : OrbTuning.rise
        let settle = reduceMotion ? OrbTuning.reducedSettle : OrbTuning.settle
        let e = now - glowStart
        func smooth(_ x: Double) -> Double { let t = min(1, max(0, x)); return t * t * (3 - 2 * t) }
        if e < 0 { return 0 }
        if e < rise { return glowFrom + (1 - glowFrom) * smooth(e / rise) }
        if e < rise + settle { return 1 - smooth((e - rise) / settle) }
        return 0
    }

    // MARK: Drawing

    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {}

    func draw(in view: MTKView) {
        let now = CACurrentMediaTime()
        let dt = lastFrame == 0 ? 0 : min(now - lastFrame, 0.05)
        if lastFrame != 0 { OrbStats.shared.record(intervalMs: (now - lastFrame) * 1000) }
        lastFrame = now
        let cfg = configuration
        // While a note is absorbed the inner currents run faster, then ease back to idle pace.
        if !reduceMotion { time += dt * (0.25 + 0.75 * cfg.energy) * (1 + 2.2 * glow) }
        kick *= exp(-dt * 2.5)
        glow = min(1, max(0, glowValue(now: now)))
        OrbStats.shared.traceGlow(glow, at: now)

        guard let pipeline, let queue, let reference, let bloom,
              let pass = view.currentRenderPassDescriptor, let drawable = view.currentDrawable,
              let buffer = queue.makeCommandBuffer(), let encoder = buffer.makeRenderCommandEncoder(descriptor: pass) else { return }

        let size = view.drawableSize
        let aspect = Float(size.width / max(size.height, 1))
        // Flow phase stays continuous: wrap only the orbit angle, which is periodic.
        let phase = Float((time / OrbTuning.flowPeriod).truncatingRemainder(dividingBy: 1) * 2 * .pi)
        // 200π is a common period of all three contour terms (0.86, 0.61, 0.43 × 200π are whole turns), so the wrap is seamless.
        let contourT = Float(time.truncatingRemainder(dividingBy: 200 * .pi))
        var u = OrbUniforms(
            a: SIMD4(contourT, Float(glow * cfg.intensity), Float(reduceMotion ? 0 : kick), OrbTuning.viewHalfSize),
            b: SIMD4(phase, Float(cfg.energy) * OrbTuning.flowAmplitude, OrbTuning.radius, aspect),
            c: SIMD4(OrbTuning.center.x, OrbTuning.center.y, OrbTuning.sweep * Float(cfg.energy), reduceMotion ? 0 : 1))
        encoder.setRenderPipelineState(pipeline)
        encoder.setFragmentBytes(&u, length: MemoryLayout<OrbUniforms>.stride, index: 0)
        encoder.setFragmentTexture(reference, index: 0)
        encoder.setFragmentTexture(bloom, index: 1)
        encoder.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3)
        encoder.endEncoding()
        buffer.addCompletedHandler { cb in
            OrbStats.shared.record(gpuMs: (cb.gpuEndTime - cb.gpuStartTime) * 1000)
        }
        buffer.present(drawable)
        buffer.commit()
    }

    struct OrbUniforms { var a: SIMD4<Float>; var b: SIMD4<Float>; var c: SIMD4<Float> }

    static let shader = """
    #include <metal_stdlib>
    using namespace metal;

    struct VOut { float4 pos [[position]]; float2 uv; };
    struct U { float4 a; float4 b; float4 c; };
    // a: contourTime, glow, kick, viewHalfSize
    // b: flowPhase, flowAmplitude, refRadius, aspect
    // c: refCenter.xy, sweep, motion(0/1)

    vertex VOut orb_vertex(uint vid [[vertex_id]]) {
        float2 p[3] = { float2(-1, -1), float2(3, -1), float2(-1, 3) };
        VOut o; o.pos = float4(p[vid], 0, 1); o.uv = float2((p[vid].x + 1) * 0.5, 1 - (p[vid].y + 1) * 0.5); return o;
    }

    float hash2(float2 p) { return fract(sin(p.x * 127.1 + p.y * 311.7) * 43758.5453); }
    float vnoise(float2 p) {
        float2 i = floor(p), f = p - i, u = f * f * (3 - 2 * f);
        float a = hash2(i), b = hash2(i + float2(1, 0)), c = hash2(i + float2(0, 1)), d = hash2(i + float2(1, 1));
        return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
    }

    fragment float4 orb_fragment(VOut in [[stage_in]], constant U& u [[buffer(0)]],
                                 texture2d<float> ref [[texture(0)]], texture2d<float> bloomTex [[texture(1)]]) {
        constexpr sampler s(address::clamp_to_edge, filter::linear, mip_filter::linear);
        float t = u.a.x, glow = u.a.y, kick = u.a.z, view = u.a.w;
        float phase = u.b.x, flowAmp = u.b.y, R = u.b.z, aspect = u.b.w;
        float2 C = u.c.xy; float sweep = u.c.z, motion = u.c.w;

        // Square orb space centred in the drawable, whatever its aspect (never stretched).
        float2 p = in.uv * 2 - 1;
        if (aspect > 1) p.x *= aspect; else p.y /= aspect;
        p *= view;
        float r = length(p) + 1e-6, a = atan2(p.y, p.x);

        // Contour motion (README formula), inverted for sampling. Stays < 0.55% of the radius.
        float edge = exp(-pow((r - 1) / 0.48, 2)) * min(r, 1.0);
        float wave = 0.0022 * sin(3 * a - 0.86 * t) + 0.0012 * sin(2 * a + 0.61 * t) + 0.0006 * sin(5 * a - 0.43 * t);
        float rs = r - edge * (wave * motion + 0.0007 * kick);
        float2 q = float2(cos(a), sin(a)) * rs;

        // Interior flow: orbiting noise field + reflection sweep, zero at the rim.
        float m = (1 - smoothstep(0.70, 0.97, rs)) * motion;
        float2 orbit = 0.40 * float2(cos(phase), sin(phase));
        float n1 = vnoise(q * 1.3 + orbit) - 0.5;
        float n2 = vnoise(q * 1.3 + orbit + float2(5.2, 1.3)) - 0.5;
        // Absorb: the interior swirls inward (stronger toward the centre) and the currents
        // deepen, then unwinds as the glow settles. Zero at the rim, so the outline never moves.
        float twist = glow * 1.15 * (1 - smoothstep(0.0, 0.95, rs)) * m;
        float ang = sweep * sin(phase) * m + twist;
        float ca = cos(ang), sa = sin(ang);
        float pull = 1 + 0.08 * glow * m;                  // light drawn toward the centre
        float2 f = float2(q.x * ca - q.y * sa, q.x * sa + q.y * ca) * pull
                 + float2(n1, n2) * flowAmp * m * (1 + 0.9 * glow);
        // Never sample past the glass: softly compress where the flow would reach outside.
        // The limit is never below this pixel's own radius, so the rim itself is untouched.
        float lf = length(f) + 1e-6, cap = max(rs, 0.92);
        if (lf > cap) f *= cap / lf;
        float3 col = ref.sample(s, C + R * f).rgb;

        // Fed light: the body brightens a little, most of all toward the lower pearl light.
        float inside = 1 - smoothstep(0.985, 1.01, rs);
        float lift = smoothstep(-0.3, 1.0, q.y) * inside;
        col = col * (1 + 0.12 * glow) + 0.05 * glow * lift;

        // Bloom from the orb's own light; mostly outside the glass.
        float outside = smoothstep(0.90, 1.08, r);
        // Window: the bloom reaches zero well before the view's edge, so no box is ever visible.
        float window = 1 - smoothstep(1.18, 1.50, r);
        float3 bl = bloomTex.sample(s, C + R * p).rgb * (0.08 + 0.95 * glow) * (0.10 + 0.90 * outside) * window;
        float body = 1 - smoothstep(1.01, 1.04, r);       // the glass itself is solid
        col = 1 - (1 - saturate(col * body)) * (1 - saturate(bl));
        col = saturate(col);
        // Premultiplied output: light over transparency (black reference background = no coverage).
        float alpha = max(body, max(col.r, max(col.g, col.b)));
        return float4(col, alpha);
    }
    """
}
