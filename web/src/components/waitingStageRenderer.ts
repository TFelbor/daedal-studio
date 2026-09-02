import { accentAt, cssToken, inkAt, onThemeChange, prefersReducedMotion } from '../theme';

export type WaitingKind = 'blueprint' | 'mesh' | 'slice';

type Point = [number, number];

interface StandInMesh {
  verts: number[][];
  edges: [number, number][];
}

/**
 * The drawn half of the waiting stage.
 *
 * Held as a plain class rather than React state because every value in here changes
 * on every frame: putting `yaw` or `sweep` through `useState` would re-render the
 * page sixty times a second to move a line by two pixels. The component owns the
 * canvas element and this owns what is on it.
 *
 * Three drawings, one per artifact the pipeline produces, each showing the *work* of
 * its phase rather than a spinner over an empty box:
 *
 *   blueprint — a drafting head laying an isometric outline across the sheet
 *   mesh      — a stand-in solid assembling itself, orbitable like the real viewer
 *   slice     — the toolpath stack climbing, travelable by drag
 *
 * All three are draggable, which is the point: the stage the user will interact with
 * once the artifact exists already answers to the same gesture while they wait, so
 * the wait teaches the control instead of blocking it.
 */
export class WaitingStageRenderer {
  private canvas: HTMLCanvasElement;
  private kind: WaitingKind;
  private accent: string;
  private reduced: boolean;
  private mesh: StandInMesh;
  private t0 = 0;
  private raf = 0;
  private box: { w: number; h: number } = { w: 0, h: 0 };
  private observer: ResizeObserver | null = null;
  private unsubscribeTheme: (() => void) | null = null;
  private refitScheduled = false;
  private drag: { x: number; y: number } | null = null;
  private onFirstDrag: () => void;
  private dragged = false;

  /** Per-drawing interaction state. Never read during render, only during a frame. */
  private view = {
    blueprint: { sweep: 0, manual: false, idleAt: 0, span: 0 },
    mesh: { yaw: 0.6, pitch: -0.3, vy: 0, vp: 0, born: 0 },
    slice: { layers: 0, manual: false, idleAt: 0 },
  };

  constructor(canvas: HTMLCanvasElement, kind: WaitingKind, onFirstDrag: () => void) {
    this.canvas = canvas;
    this.kind = kind;
    this.onFirstDrag = onFirstDrag;
    this.accent = cssToken('--accent', '#43a38d');
    this.reduced = prefersReducedMotion();
    this.mesh = buildStandIn();
  }

  start() {
    this.t0 = performance.now();
    this.view.mesh.born = this.t0;

    // Scheduled, not synchronous. Writing the backing store inside the observer
    // callback makes the observer fire again, and the browser gives up with
    // "ResizeObserver loop completed with undelivered notifications".
    this.observer = new ResizeObserver(() => {
      if (this.refitScheduled) return;
      this.refitScheduled = true;
      requestAnimationFrame(() => {
        this.refitScheduled = false;
        this.fit();
      });
    });
    this.fit();
    this.observer.observe(this.canvas);

    this.canvas.addEventListener('pointerdown', this.handleDown);
    this.canvas.addEventListener('pointermove', this.handleMove);
    this.canvas.addEventListener('pointerup', this.handleUp);
    this.canvas.addEventListener('pointercancel', this.handleUp);

    // The accent was resolved once, at construction. A theme flip changes it, and
    // this surface is animating — so it would go on stroking the old ground's
    // accent until the component happened to remount.
    this.unsubscribeTheme = onThemeChange(() => {
      this.accent = cssToken('--accent', '#43a38d');
    });

    this.raf = requestAnimationFrame(this.frame);
  }

  destroy() {
    cancelAnimationFrame(this.raf);
    this.observer?.disconnect();
    this.unsubscribeTheme?.();
    this.unsubscribeTheme = null;
    this.canvas.removeEventListener('pointerdown', this.handleDown);
    this.canvas.removeEventListener('pointermove', this.handleMove);
    this.canvas.removeEventListener('pointerup', this.handleUp);
    this.canvas.removeEventListener('pointercancel', this.handleUp);
  }

  /**
   * Switch drawings without tearing the renderer down.
   *
   * The mesh's assembly is replayed from zero, because someone who has just clicked
   * onto that tab has not seen it build; the other two hand their auto-motion back.
   */
  setKind(kind: WaitingKind) {
    this.kind = kind;
    const now = performance.now();
    if (kind === 'mesh') this.view.mesh.born = now;
    if (kind === 'blueprint') {
      this.view.blueprint.manual = false;
      this.view.blueprint.idleAt = 0;
    }
    if (kind === 'slice') {
      this.view.slice.manual = false;
      this.view.slice.idleAt = 0;
    }
  }

  private fit() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    // A sub-pixel jitter is not a resize. Rewriting the backing store for one costs a
    // full clear and re-notifies the observer for nothing.
    if (Math.abs(rect.width - this.box.w) < 0.5 && Math.abs(rect.height - this.box.h) < 0.5) {
      return;
    }
    this.canvas.width = Math.round(rect.width * dpr);
    this.canvas.height = Math.round(rect.height * dpr);
    this.canvas.getContext('2d')?.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.box = { w: rect.width, h: rect.height };
  }

  private handleDown = (e: PointerEvent) => {
    this.canvas.setPointerCapture(e.pointerId);
    this.drag = { x: e.clientX, y: e.clientY };
    this.canvas.style.cursor = 'grabbing';
    // The hint has done its job once they have taken hold.
    if (!this.dragged) {
      this.dragged = true;
      this.onFirstDrag();
    }
    if (this.kind === 'blueprint') {
      this.view.blueprint.manual = true;
      this.view.blueprint.idleAt = 0;
    } else if (this.kind === 'slice') {
      this.view.slice.manual = true;
      this.view.slice.idleAt = 0;
    }
  };

  private handleMove = (e: PointerEvent) => {
    if (!this.drag) return;
    const dx = e.clientX - this.drag.x;
    const dy = e.clientY - this.drag.y;
    this.drag = { x: e.clientX, y: e.clientY };

    if (this.kind === 'mesh') {
      const v = this.view.mesh;
      v.yaw += dx * 0.016;
      v.pitch = Math.max(-1.3, Math.min(1.3, v.pitch + dy * 0.012));
      v.vy = dx * 0.016;
      v.vp = dy * 0.012;
    } else if (this.kind === 'blueprint') {
      // Map the drag to the head's own travel, not the frame width, or the head
      // moves slower than the cursor and reads as lag.
      const v = this.view.blueprint;
      const span = v.span || this.canvas.getBoundingClientRect().width || 1;
      v.sweep = Math.max(0, Math.min(1, v.sweep + dx / span));
    } else {
      this.view.slice.layers = Math.max(0, Math.min(SLICE_LAYERS, this.view.slice.layers - dy * 0.28));
    }
  };

  private handleUp = () => {
    this.drag = null;
    this.canvas.style.cursor = 'grab';
    const now = performance.now();
    if (this.kind === 'blueprint') this.view.blueprint.idleAt = now;
    if (this.kind === 'slice') this.view.slice.idleAt = now;
  };

  private frame = () => {
    this.raf = requestAnimationFrame(this.frame);
    const ctx = this.canvas.getContext('2d');
    if (!ctx || !this.box.w) return;
    const { w, h } = this.box;
    const now = performance.now();
    ctx.clearRect(0, 0, w, h);
    if (this.kind === 'blueprint') this.drawBlueprint(ctx, w, h, now);
    else if (this.kind === 'mesh') this.drawMesh(ctx, w, h, now);
    else this.drawSlice(ctx, w, h, now);
  };

  /** Phase 01 — a drafting head laying an isometric outline down across the sheet. */
  private drawBlueprint(ctx: CanvasRenderingContext2D, w: number, h: number, now: number) {
    const v = this.view.blueprint;
    // Hand auto-motion back a couple of seconds after the pointer lets go, so a
    // stage someone poked once does not sit frozen for the rest of the phase.
    if (!v.manual || (v.idleAt && now - v.idleAt > 2200)) {
      v.manual = false;
      if (!this.reduced) v.sweep = Math.min(1, ((now - this.t0) / 6400) % 1.3);
    }
    const sweep = Math.min(1, v.sweep);

    const A = Math.min(w, h) * 0.0027 * 92;

    // Project into a local frame first, so the drawing can be measured before it is
    // placed. An isometric box is *not* vertically symmetric about its own origin —
    // the top face rises 0.74 units while the base falls a full unit — so centring on
    // `h / 2` directly leaves it sitting low by about a third of the box height. The
    // fix is to centre the drawing on its own bounds rather than trusting the origin.
    const local = (x: number, y: number, z: number): Point => [
      (x - y) * 0.866 * A,
      ((x + y) * 0.5 - z) * A,
    ];

    const corners: Point[] = [
      [-1, -1],
      [1, -1],
      [1, 1],
      [-1, 1],
    ];
    const raw: [Point, Point][] = [];
    for (let i = 0; i < 4; i++) {
      const p = corners[i];
      const q = corners[(i + 1) % 4];
      raw.push([local(p[0], p[1], 0), local(q[0], q[1], 0)]);
      raw.push([local(p[0], p[1], 0.74), local(q[0], q[1], 0.74)]);
      raw.push([local(p[0], p[1], 0), local(p[0], p[1], 0.74)]);
      raw.push([local(p[0] * 0.72, p[1] * 0.72, 0.62), local(q[0] * 0.72, q[1] * 0.72, 0.62)]);
      raw.push([local(p[0], p[1], 0.74), local(p[0] * 0.72, p[1] * 0.72, 0.62)]);
    }

    // Centre on the object, not on the construction lines: those overrun the box on
    // purpose, and letting them vote would shove the solid off-centre to compensate.
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const [a, b] of raw) {
      for (const q of [a, b]) {
        if (q[0] < minX) minX = q[0];
        if (q[0] > maxX) maxX = q[0];
        if (q[1] < minY) minY = q[1];
        if (q[1] > maxY) maxY = q[1];
      }
    }
    const ox = w / 2 - (minX + maxX) / 2;
    const oy = h / 2 - (minY + maxY) / 2;
    const P = (x: number, y: number, z: number): Point => {
      const q = local(x, y, z);
      return [q[0] + ox, q[1] + oy];
    };
    const segs: [Point, Point][] = raw.map(([a, b]) => [
      [a[0] + ox, a[1] + oy],
      [b[0] + ox, b[1] + oy],
    ]);

    // The crosshair rides the head, on the drawing's own centreline — which is now
    // `h / 2` exactly, because the drawing was just centred there.
    const cy = h / 2;

    // The head crosses the whole frame, edge to edge. It used to travel only the
    // drawing's own width, which left it starting and stopping in mid-air partway
    // across the box instead of sweeping the sheet.
    v.span = w;
    const sx = sweep * w;

    // Construction lines first — they are drawn before the object, as on a real sheet.
    ctx.save();
    ctx.setLineDash([2, 5]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = inkAt(0.13);
    const ext: [Point, Point][] = [
      [P(-1, -1, 0), P(-1, -1, 1.5)],
      [P(1, 1, 0), P(1, 1, 1.5)],
      [P(-1.6, -1.6, 0), P(1.6, 1.6, 0)],
      [P(-1.6, 1.6, 0), P(1.6, -1.6, 0)],
    ];
    for (const [p, q] of ext) clipDraw(ctx, p, q, -1e5, sx);
    ctx.restore();

    // Two passes: the whole revealed drawing in ink, then a narrow accent band at the
    // head, so the leading edge glows without recolouring whole segments behind it.
    ctx.save();
    ctx.lineWidth = 1.25;
    ctx.strokeStyle = inkAt(0.5);
    for (const [p, q] of segs) clipDraw(ctx, p, q, -1e5, sx);
    ctx.strokeStyle = this.accent;
    ctx.lineWidth = 1.4;
    for (const [p, q] of segs) clipDraw(ctx, p, q, sx - 26, sx);
    ctx.restore();

    // The head: a full-height rule with a crosshair on the drawing's centreline.
    ctx.save();
    ctx.strokeStyle = accentAt(0.45);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(sx, 0);
    ctx.lineTo(sx, h);
    ctx.stroke();
    ctx.strokeStyle = this.accent;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(sx - 7, cy);
    ctx.lineTo(sx + 7, cy);
    ctx.moveTo(sx, cy - 7);
    ctx.lineTo(sx, cy + 7);
    ctx.stroke();
    ctx.restore();

    // Registration marks land on every corner the head has passed — the same
    // six-mark grammar the frames use, here as the drawing's own datum points.
    ctx.save();
    ctx.strokeStyle = accentAt(0.7);
    ctx.lineWidth = 1;
    for (const c of corners) {
      for (const z of [0, 0.74]) {
        const q = P(c[0], c[1], z);
        if (q[0] > sx) continue;
        cross(ctx, q, 3.5);
      }
    }
    ctx.restore();
  }

  /** Phase 02/03 — a stand-in solid assembling itself, orbitable like the real viewer. */
  private drawMesh(ctx: CanvasRenderingContext2D, w: number, h: number, now: number) {
    const v = this.view.mesh;
    if (!this.drag) {
      // Carry the throw, then settle back to the idle turn.
      v.yaw += v.vy;
      v.pitch += v.vp;
      v.vy *= 0.93;
      v.vp *= 0.93;
      if (Math.abs(v.vy) < 0.0008) v.vy = 0;
      if (Math.abs(v.vp) < 0.0008) v.vp = 0;
      if (!this.reduced) v.yaw += 0.0035;
    }

    const p = this.reduced ? 1 : Math.min(1, (now - v.born) / 2600);
    const { verts, edges } = this.mesh;
    // Size from the envelope rather than from the frame, so the drawing fills the
    // box to a known margin instead of to a guess.
    const R = (Math.min(w, h) * MESH_FILL) / (2 * MESH_ENVELOPE);
    const cx = w / 2;
    // Dead centre, and no correction for the bed.
    //
    // The correction that used to be here was wrong twice over. The stand-in solid is
    // symmetric about `cy` — the radial wobble reaches 1.30 units and perspective adds
    // a sixth, so it spans ±1.51R either side — and the bed ellipse's lowest point sits
    // at 1.35R, *inside* that envelope. So the bed never extended the drawing at all,
    // and compensating for it shifted the whole thing up by 0.6R. That is why the mesh
    // still sat high after the blueprint was fixed.
    const cy = h / 2;
    const cyw = Math.cos(v.yaw);
    const syw = Math.sin(v.yaw);
    const cp = Math.cos(v.pitch);
    const sp = Math.sin(v.pitch);

    const proj = verts.map((q) => {
      const [x, y, z] = q;
      const x2 = x * cyw - z * syw;
      const z2 = x * syw + z * cyw;
      const y2 = y * cp - z2 * sp;
      const z3 = y * sp + z2 * cp;
      const k = R / (1 + z3 * 0.11);
      return [cx + x2 * k, cy - y2 * k, z3];
    });

    const vShown = Math.min(verts.length, Math.ceil(p * 1.7 * verts.length));
    const eShown = Math.min(edges.length, Math.ceil(Math.max(0, p - 0.22) * 1.9 * edges.length));

    ctx.save();
    ctx.lineWidth = 1;
    for (let i = 0; i < eShown; i++) {
      const [ai, bi] = edges[i];
      if (ai >= vShown || bi >= vShown) continue;
      const a = proj[ai];
      const b = proj[bi];
      const depth = (a[2] + b[2]) / 2;
      const fresh = p < 1 && i > eShown - 5;
      ctx.strokeStyle = fresh
        ? this.accent
        : inkAt(0.34 - depth * 0.13);
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
      ctx.stroke();
    }

    // Every vertex wears a registration cross, so the assembling solid is drawn in
    // the same marks the rest of the board is built from.
    for (let i = 0; i < vShown; i++) {
      const q = proj[i];
      const front = q[2] < 0;
      ctx.strokeStyle = front ? accentAt(0.9) : accentAt(0.38);
      cross(ctx, [q[0], q[1]], front ? 3.6 : 2.6);
    }
    ctx.restore();

    // The part is scaled to a print bed, so it gets a floor to sit against. No clamp:
    // the centring above already guarantees the pair fits, and a clamp would silently
    // reintroduce the asymmetry on a short stage.
    ctx.save();
    ctx.strokeStyle = inkAt(0.09);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.ellipse(cx, cy + BED_DROP * R, R * 0.8, R * 0.15, 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  /** Phase 04 — the toolpath stack climbing, travelable by drag. */
  private drawSlice(ctx: CanvasRenderingContext2D, w: number, h: number, now: number) {
    const v = this.view.slice;
    if (!v.manual || (v.idleAt && now - v.idleAt > 2200)) {
      v.manual = false;
      if (!this.reduced) v.layers = ((now - this.t0) / 130) % (SLICE_LAYERS + 16);
    }
    const k = Math.max(1, Math.min(SLICE_LAYERS, v.layers));
    const pitch = Math.min(h, 520) * 0.0165;
    const R = Math.min(w, h) * 0.27;
    const cx = w / 2;
    // Half the stack's own height, so the finished stack is centred and the growing
    // one climbs into a fixed envelope rather than drifting up the frame as it builds.
    const cy = h / 2 + (SLICE_LAYERS * pitch) / 2;

    const ring = (z: number): Point[] => {
      const r = R * (0.55 + 0.45 * Math.sin(0.85 + z * 2.55));
      const pts: Point[] = [];
      for (let i = 0; i < 8; i++) {
        const th = (i / 8) * Math.PI * 2 + Math.PI / 8;
        pts.push([
          cx + Math.cos(th) * r,
          cy + Math.sin(th) * r * 0.42 - z * SLICE_LAYERS * pitch,
        ]);
      }
      return pts;
    };
    const trace = (pts: Point[]) => {
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.closePath();
    };

    ctx.save();
    ctx.lineWidth = 1;
    const whole = Math.floor(k);
    // Cooled layers fade with depth; every fifth reads brighter, as a slicer preview
    // marks its own decades.
    for (let i = 0; i < whole; i++) {
      const age = (whole - i) / SLICE_LAYERS;
      ctx.strokeStyle =
        i % 5 === 0
          ? inkAt(0.3 - age * 0.16)
          : inkAt(0.16 - age * 0.09);
      trace(ring(i / SLICE_LAYERS));
      ctx.stroke();
    }

    // The layer being written: accent outline plus its infill, clipped to the
    // contour, and alternating direction the way a real slicer alternates it.
    const top = ring(whole / SLICE_LAYERS);
    ctx.save();
    trace(top);
    ctx.clip();
    ctx.strokeStyle = accentAt(0.35);
    ctx.lineWidth = 1;
    const dir = whole % 2 === 0 ? 1 : -1;
    for (let x = -R * 1.2; x < R * 1.2; x += 7) {
      ctx.beginPath();
      ctx.moveTo(cx + x, top[0][1] - R * 0.6);
      ctx.lineTo(cx + x + dir * R * 0.55, top[0][1] + R * 0.6);
      ctx.stroke();
    }
    ctx.restore();
    ctx.strokeStyle = this.accent;
    ctx.lineWidth = 1.5;
    trace(top);
    ctx.stroke();

    // Where the head is right now, on the perimeter of the layer being written.
    const nz = top[Math.floor((k % 1) * 8) % 8];
    ctx.fillStyle = this.accent;
    ctx.fillRect(nz[0] - 2, nz[1] - 2, 4, 4);
    ctx.restore();
  }
}

const SLICE_LAYERS = 46;

/** How far below the solid's centre its bed sits, in units of the solid's radius. */
const BED_DROP = 1.2;

/**
 * Half-height of the stand-in solid, in units of R.
 *
 * Derived, not chosen: `buildStandIn`'s radial wobble takes the furthest vertex to
 * 1.295 units, and the projection's perspective divide (`1 + z·0.11`) adds up to a
 * further 16.6% on the near side — 1.295 / (1 − 1.295·0.11) = 1.51. The bed ellipse
 * bottoms out at BED_DROP + 0.15 = 1.35R, comfortably inside it, so this figure alone
 * describes the whole drawing's extent in both axes.
 */
const MESH_ENVELOPE = 1.51;

/** Fraction of the frame's short side the drawing fills, leaving an even margin. */
const MESH_FILL = 0.86;

/** A registration cross, the mark the whole board is built from. */
function cross(ctx: CanvasRenderingContext2D, p: Point, s: number) {
  ctx.beginPath();
  ctx.moveTo(p[0] - s, p[1]);
  ctx.lineTo(p[0] + s, p[1]);
  ctx.moveTo(p[0], p[1] - s);
  ctx.lineTo(p[0], p[1] + s);
  ctx.stroke();
}

/**
 * Draw p→q clipped to the vertical band `lo <= x <= hi`.
 *
 * This is what makes the drafting head reveal geometry rather than fade it in: a
 * segment the head is halfway across is drawn halfway, at its true endpoints.
 */
function clipDraw(
  ctx: CanvasRenderingContext2D,
  p: Point,
  q: Point,
  lo: number,
  hi: number,
) {
  const dx = q[0] - p[0];
  let t0 = 0;
  let t1 = 1;
  if (Math.abs(dx) < 1e-6) {
    if (p[0] < lo || p[0] > hi) return;
  } else {
    const ta = (lo - p[0]) / dx;
    const tb = (hi - p[0]) / dx;
    t0 = Math.max(0, Math.min(ta, tb));
    t1 = Math.min(1, Math.max(ta, tb));
    if (t0 >= t1) return;
  }
  const dy = q[1] - p[1];
  ctx.beginPath();
  ctx.moveTo(p[0] + dx * t0, p[1] + dy * t0);
  ctx.lineTo(p[0] + dx * t1, p[1] + dy * t1);
  ctx.stroke();
}

/**
 * The stand-in solid: an icosahedron with a radial wobble.
 *
 * Edges are derived from vertex distance rather than hardcoded, so subdividing would
 * not need a second edge table. The wobble is there so the placeholder reads as a
 * part rather than as a ball — a perfect sphere looks like a loading graphic, which
 * is the thing this replaces.
 */
function buildStandIn(): StandInMesh {
  const t = (1 + Math.sqrt(5)) / 2;
  const norm = (p: number[]) => {
    const l = Math.hypot(p[0], p[1], p[2]);
    return [p[0] / l, p[1] / l, p[2] / l];
  };
  const verts = [
    [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
    [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
    [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
  ].map(norm);

  const near = (a: number[], b: number[]) =>
    Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) < 1.06;

  const edges: [number, number][] = [];
  for (let i = 0; i < verts.length; i++) {
    for (let j = i + 1; j < verts.length; j++) {
      if (near(verts[i], verts[j])) edges.push([i, j]);
    }
  }

  const shaped = verts.map((p) => {
    const k = 1 + 0.17 * Math.sin(p[1] * 2.4) + 0.09 * Math.cos(p[0] * 3.1);
    return [p[0] * k, p[1] * k * 1.12, p[2] * k];
  });

  return { verts: shaped, edges };
}
