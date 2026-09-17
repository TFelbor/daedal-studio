import { useEffect, useRef, useState } from 'react';
import { useTheme } from '../hooks/useTheme';
import { useIsPhone } from '../hooks/useMediaQuery';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import { cssToken, prefersReducedMotion } from '../theme';
import { StageState } from './StageState';
import { stageStatus } from './stageStatus';
import styles from './MeshViewer.module.css';
import { apiFetch } from '../api/http';
import { getJobSpec, type ViewCallout, type ViewDocument } from '../api/client';

interface PhaseLike {
  phase: number;
  status: string;
}

interface MeshViewerProps {
  jobId: string | null;
  status: string;
  phases: PhaseLike[];
  /** Live pipeline output, newest last. Passed through to the stage state. */
  logLines?: string[];
  /**
   * Whether this job was compiled from a spec. False — the default — fetches nothing and
   * draws nothing extra: a generative job has no designed millimetres, and a viewer that
   * said so would be explaining an absence the spec panel already explains.
   */
  hasSpec?: boolean;
}

/** Read a design token so the scene cannot drift from the stylesheet. */
const token = cssToken;

/**
 * How far the served mesh's extents may differ from `view.json`'s frame, per axis, mm.
 *
 * The same ±0,05 mm the whole parametric path claims. Inside it the two are the same
 * part and the callouts are translated onto the mesh; outside it they are not, and
 * nothing is drawn — a stale artifact or a rescaled mesh must cost the annotations, not
 * their honesty.
 */
const FRAME_TOLERANCE_MM = 0.05;

/** How far a dimension line is nudged along its `offset`, as a fraction of the part. */
const CALLOUT_NUDGE = 0.03;
/** How long each end tick is, as a fraction of the part. */
const CALLOUT_TICK = 0.02;
/** What a callout facing away from the camera fades to. */
const CALLOUT_BACK_OPACITY = 0.22;

function parseOBJ(text: string) {
  const positions: number[] = [];
  const vertices: number[] = [];
  for (const line of text.split('\n')) {
    const parts = line.trim().split(/\s+/);
    if (parts[0] === 'v') {
      vertices.push(parseFloat(parts[1]), parseFloat(parts[2]), parseFloat(parts[3]));
    } else if (parts[0] === 'f') {
      const faceIndices: number[] = [];
      for (let i = 1; i < parts.length; i++) {
        if (!parts[i]) continue;
        faceIndices.push(parseInt(parts[i].split('/')[0], 10) - 1);
      }
      for (let i = 1; i < faceIndices.length - 1; i++) {
        const i1 = faceIndices[0] * 3;
        const i2 = faceIndices[i] * 3;
        const i3 = faceIndices[i + 1] * 3;
        positions.push(
          vertices[i1], vertices[i1 + 1], vertices[i1 + 2],
          vertices[i2], vertices[i2 + 1], vertices[i2 + 2],
          vertices[i3], vertices[i3 + 1], vertices[i3 + 2],
        );
      }
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.computeVertexNormals();
  return geometry;
}

/** A millimetre as this project writes one: comma decimal, one place, unit attached. */
function formatMm(value: number): string {
  return `${value.toFixed(1).replace('.', ',')} mm`;
}

/**
 * Where `view.json`'s coordinates land on the mesh that was actually served, or null.
 *
 * The frame describes the plate the *compiler* built; the mesh on the wire is Phase 3's,
 * which `orient_for_print` XY-centres and sits on Z = 0 — a translation and nothing else,
 * because `--target-mm` is refused in assert mode. So the two have identical extents and
 * differ by one vector, and that vector is what the callouts are moved by.
 *
 * When the extents disagree the mesh is not the part the callouts describe — a rescaled
 * mesh, a stale artifact, a Phase 3 that learned to rotate. Null, and the viewer draws
 * the mesh with no annotations rather than annotating it with another part's numbers.
 * That turns a remembered fact about the pipeline into a checked one.
 */
function reconcileFrame(
  frame: ViewDocument['frame'],
  meshBounds: THREE.Box3,
): THREE.Vector3 | null {
  const min = new THREE.Vector3(...frame.bounds_mm.min);
  const max = new THREE.Vector3(...frame.bounds_mm.max);
  const designed = max.clone().sub(min);
  const served = meshBounds.max.clone().sub(meshBounds.min);
  const axes: Array<'x' | 'y' | 'z'> = ['x', 'y', 'z'];
  for (const axis of axes) {
    if (Math.abs(designed[axis] - served[axis]) > FRAME_TOLERANCE_MM) return null;
  }
  return meshBounds.min.clone().sub(min);
}

interface DrawnCallout {
  tier: number;
  /** The direction the line is nudged along, in the part's own Z-up frame. */
  offset: THREE.Vector3;
  line: THREE.LineSegments;
  material: THREE.LineBasicMaterial;
  label: CSS2DObject;
  element: HTMLDivElement;
}

/**
 * One dimension line: the measure line, an end tick at each end, and a label at the
 * midpoint.
 *
 * Both are built in the part's own millimetre frame and added to the same group as the
 * mesh, so one matrix carries the vertices and the anchors alike — a callout cannot drift
 * from the surface it names because there is no second transform for it to drift through.
 * The label is a DOM node styled from the ink tokens, so it follows the theme natively
 * and stays crisp at any device pixel ratio.
 */
function drawCallout(callout: ViewCallout, scale: number, shift: THREE.Vector3): DrawnCallout {
  const from = new THREE.Vector3(...callout.from).add(shift);
  const to = new THREE.Vector3(...callout.to).add(shift);
  const offset = new THREE.Vector3(...callout.offset);
  if (offset.lengthSq() > 0) offset.normalize();
  const nudge = offset.clone().multiplyScalar(scale * CALLOUT_NUDGE);
  const a = from.clone().add(nudge);
  const b = to.clone().add(nudge);
  const tick = offset.clone().multiplyScalar(scale * CALLOUT_TICK);

  const geometry = new THREE.BufferGeometry().setFromPoints([
    a, b,
    a.clone().sub(tick), a.clone().add(tick),
    b.clone().sub(tick), b.clone().add(tick),
  ]);
  const material = new THREE.LineBasicMaterial({
    color: token('--accent', '#c8a165'),
    transparent: true,
    opacity: 1,
  });
  const line = new THREE.LineSegments(geometry, material);

  const element = document.createElement('div');
  element.className = styles.callout;
  // The feature and the tier, on the node. A CSS module class is a hashed string, so
  // these are what the viewport smoke selects on — and what a person inspecting a label
  // that looks wrong needs in order to find the feature it came from.
  element.dataset.callout = callout.feature;
  element.dataset.tier = String(callout.tier);
  const value = document.createElement('span');
  value.className = styles.calloutValue;
  value.textContent = formatMm(callout.value_mm);
  const name = document.createElement('span');
  name.className = styles.calloutLabel;
  name.textContent = callout.label;
  element.append(value, name);

  const label = new CSS2DObject(element);
  label.position.copy(a.clone().add(b).multiplyScalar(0.5));

  return { tier: callout.tier, offset, line, material, label, element };
}

export function MeshViewer({ jobId, phases, logLines, hasSpec = false }: MeshViewerProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  // Held so the theme effect below can re-colour them without tearing the scene
  // down — a rebuild would re-download the mesh and reset the orbit camera.
  const sceneRef = useRef<THREE.Scene | null>(null);
  const materialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  const calloutsRef = useRef<DrawnCallout[]>([]);
  const theme = useTheme();
  const isPhone = useIsPhone();
  // Read through a ref by the animation loop, which outlives any one render: the tier
  // filter must not rebuild the scene, or rotating a phone would re-download the mesh.
  const isPhoneRef = useRef(isPhone);
  useEffect(() => { isPhoneRef.current = isPhone; }, [isPhone]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const isPhase3Complete = phases.find((p) => p.phase === 3)?.status === 'complete';

  useEffect(() => {
    if (!jobId || !isPhase3Complete || !mountRef.current) return;

    let isActive = true;
    let animationFrameId = 0;
    let mesh: THREE.Mesh | null = null;
    const currentMount = mountRef.current;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(token('--raised', '#343535'));
    sceneRef.current = scene;

    const width = currentMount.clientWidth || 1;
    const height = currentMount.clientHeight || 1;

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    camera.position.set(0, 40, 150);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);

    // The callouts' text is DOM, not texture: it stays sharp at every zoom and takes the
    // ink tokens without the scene knowing the theme moved. It sits over the canvas and
    // never takes a pointer event, so the part still orbits by dragging through a label.
    const labelRenderer = new CSS2DRenderer();
    labelRenderer.setSize(width, height);
    labelRenderer.domElement.className = styles.labels;

    while (currentMount.firstChild) currentMount.removeChild(currentMount.firstChild);
    currentMount.appendChild(renderer.domElement);
    currentMount.appendChild(labelRenderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    // Drawn surfaces gate their own motion — the CSS media query cannot reach
    // a WebGL canvas. The model still orbits by hand.
    controls.autoRotate = !prefersReducedMotion();
    controls.autoRotateSpeed = 1.4;

    // Neutral, soft lighting. An accent-tinted fill used to sit here, and on a
    // white surface it read as warm metal — the model is meant to look like matte
    // clay, which is also what the blueprint stage promises.
    scene.add(new THREE.AmbientLight(0xffffff, 0.72));
    const keyLight = new THREE.DirectionalLight(0xffffff, 0.55);
    keyLight.position.set(12, 24, 14);
    scene.add(keyLight);
    const fillLight = new THREE.DirectionalLight(0xffffff, 0.22);
    fillLight.position.set(-16, -8, -10);
    scene.add(fillLight);

    // Everything the part is made of hangs off one group, and the group carries the two
    // transforms — Z-up to Y-up, and the part onto the floor. Baking them into the
    // geometry instead, which is what this did before the callouts existed, would leave
    // the annotations needing a second copy of both.
    const part = new THREE.Group();
    part.rotation.x = -Math.PI / 2;
    scene.add(part);

    // Held outside the loop: three vectors allocated per callout per frame is a hundred
    // objects a second for the garbage collector to find, on a page that is also running
    // a WebGL render.
    const eye = new THREE.Vector3();
    const facingDirection = new THREE.Vector3();
    const worldOffset = new THREE.Vector3();
    const animate = () => {
      if (!isActive) return;
      animationFrameId = requestAnimationFrame(animate);
      controls.update();
      if (calloutsRef.current.length) {
        camera.getWorldPosition(eye);
        for (const drawn of calloutsRef.current) {
          // Tier 1 only below 720 px, the phone step of the app's one breakpoint ladder.
          // Read per frame from a ref rather than from a dependency, because a rotation
          // must not rebuild the scene and re-download the mesh.
          const visible = !isPhoneRef.current || drawn.tier === 1;
          drawn.line.visible = visible;
          drawn.label.visible = visible;   // CSS2DRenderer hides the element itself
          if (!visible) continue;
          // A label on the far side of the part reads through it — CSS2D has no depth.
          // The cheap stand-in for occlusion: fade a callout whose own free-space
          // direction has turned away from the camera. Not true occlusion, and not
          // trying to be; overlapping labels on a near-square part are still possible.
          worldOffset.copy(drawn.offset).applyQuaternion(part.quaternion);
          drawn.label.getWorldPosition(facingDirection);
          facingDirection.subVectors(eye, facingDirection).normalize();
          const opacity = worldOffset.dot(facingDirection) < 0 ? CALLOUT_BACK_OPACITY : 1;
          drawn.material.opacity = opacity;
          drawn.element.style.opacity = String(opacity);
        }
      }
      renderer.render(scene, camera);
      labelRenderer.render(scene, camera);
    };

    setLoading(true);
    setError(false);

    /**
     * Point the camera at the part, in millimetres.
     *
     * Scene units *are* millimetres now, so a 200 mm tray and a 50 mm divider are
     * genuinely different sizes and the camera has to be told how far back to stand
     * rather than the part being resized to a fixed 80 units. That normalisation is what
     * made every callout a lie waiting to happen: a number in mm over a mesh whose size
     * came from a ratio.
     */
    const frameCamera = (box: THREE.Box3) => {
      const size = box.getSize(new THREE.Vector3());
      const centre = box.getCenter(new THREE.Vector3());
      const extent = Math.max(size.x, size.y, size.z) || 1;
      const distance = (extent / 2) / Math.tan((camera.fov * Math.PI) / 360) * 1.7;
      camera.near = Math.max(distance / 100, 0.01);
      camera.far = distance * 10;
      camera.updateProjectionMatrix();
      // A three-quarter view from slightly above: the one angle that shows a box's
      // opening, its front and one side at once, which is where the callouts are.
      const direction = new THREE.Vector3(0.55, 0.45, 1).normalize();
      camera.position.copy(centre).addScaledVector(direction, distance);
      controls.target.copy(centre);
      controls.minDistance = distance * 0.15;
      controls.maxDistance = distance * 6;
      controls.update();
    };

    const fetchMesh = (retries: number) => {
      if (!isActive) return;
      apiFetch(`/jobs/${jobId}/mesh?t=${Date.now()}`)
        .then((res) => {
          if (!res.ok) throw new Error('Mesh not ready');
          return res.text();
        })
        .then((text) => {
          if (!isActive) return;
          const geometry = parseOBJ(text);
          geometry.computeBoundingBox();
          // An empty box is `+Inf … −Inf`, and every number derived from it is NaN — a
          // camera at NaN renders nothing and reports nothing. A mesh with no vertices
          // is a failed load, not a part.
          const bounds = geometry.boundingBox ?? new THREE.Box3();
          if (bounds.isEmpty()) throw new Error('The mesh has no geometry');

          // Fully dielectric and almost fully rough: printed plastic, not chrome.
          // Any metalness at all puts a specular sheen on a white surface that
          // reads as metal, which is not what will come off the bed.
          const material = new THREE.MeshStandardMaterial({
            color: token('--ink', '#dbdbdb'),
            roughness: 0.95,
            metalness: 0,
            flatShading: false,
          });
          materialRef.current = material;
          mesh = new THREE.Mesh(geometry, material);
          part.add(mesh);

          // The group is rotated (the pipeline exports Z-up, three.js is Y-up — without
          // it the part is displayed lying on its back, which is exactly the silent
          // failure the sculptor's up-axis handling exists to prevent) and then moved so
          // the part is centred over the grid and sitting on it. Both are *view*
          // transforms; nothing is scaled, so a millimetre on screen is a millimetre.
          const size = bounds.getSize(new THREE.Vector3());
          const centre = bounds.getCenter(new THREE.Vector3());
          part.position.set(-centre.x, -bounds.min.z, centre.y);
          frameCamera(new THREE.Box3(
            new THREE.Vector3(-size.x / 2, 0, -size.y / 2),
            new THREE.Vector3(size.x / 2, size.z, size.y / 2),
          ));

          setLoading(false);
          animate();
          if (hasSpec) annotate(bounds, Math.max(size.x, size.y, size.z) || 1);
        })
        .catch(() => {
          if (!isActive) return;
          if (retries > 0) {
            window.setTimeout(() => fetchMesh(retries - 1), 2000);
          } else {
            setError(true);
            setLoading(false);
          }
        });
    };

    /**
     * Draw the spec's own millimetres over the mesh, or draw nothing.
     *
     * Every way this can go wrong ends in *no callouts* and no explanation: a job with no
     * spec, a `view.json` Phase 2 has not written, a document that does not parse, a
     * frame the served mesh does not match. The mesh is never held back for the view
     * document either — the part is what the viewer is for, and the annotations are what
     * it adds when it can stand behind them.
     */
    const annotate = (bounds: THREE.Box3, scale: number) => {
      getJobSpec(jobId)
        .then((record) => {
          if (!isActive || !record?.view?.callouts?.length) return;
          const shift = reconcileFrame(record.view.frame, bounds);
          if (!shift) {
            console.warn(
              '[MeshViewer] the served mesh does not have view.json\'s extents; ' +
              'drawing it without dimensions.',
            );
            return;
          }
          const drawn = record.view.callouts.map((c) => drawCallout(c, scale, shift));
          for (const d of drawn) {
            part.add(d.line);
            part.add(d.label);
          }
          calloutsRef.current = drawn;
        })
        .catch(() => {
          /* No annotations. The spec panel is where a missing spec is explained. */
        });
    };

    fetchMesh(3);

    const handleResize = () => {
      const w = currentMount.clientWidth;
      const h = currentMount.clientHeight;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      labelRenderer.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      isActive = false;
      sceneRef.current = null;
      materialRef.current = null;
      window.removeEventListener('resize', handleResize);
      if (animationFrameId) cancelAnimationFrame(animationFrameId);
      if (mesh) {
        mesh.geometry.dispose();
        (mesh.material as THREE.Material).dispose();
      }
      for (const drawn of calloutsRef.current) {
        drawn.line.geometry.dispose();
        drawn.material.dispose();
        drawn.label.removeFromParent();
        drawn.element.remove();
      }
      calloutsRef.current = [];
      controls.dispose();
      renderer.dispose();
      // Browsers cap live WebGL contexts (~16); without this, navigating back and
      // forth between jobs eventually kills the oldest viewer on the page.
      renderer.forceContextLoss();
      for (const node of [renderer.domElement, labelRenderer.domElement]) {
        try {
          currentMount.removeChild(node);
        } catch {
          /* already detached */
        }
      }
    };
  }, [jobId, isPhase3Complete, hasSpec]);

  // The ground moved: repaint the scene, the plastic and the dimension lines. The
  // animation loop is already running, so setting the colours is the whole update — and
  // the lines are re-coloured in place for the same reason the mesh is, since rebuilding
  // them would re-fetch the view document and drop the camera.
  useEffect(() => {
    const background = sceneRef.current?.background;
    if (background instanceof THREE.Color) background.set(token('--raised', '#343535'));
    materialRef.current?.color.set(token('--ink', '#dbdbdb'));
    for (const drawn of calloutsRef.current) {
      drawn.material.color.set(token('--accent', '#c8a165'));
    }
  }, [theme]);

  // A failed fetch is the one case the stage state cannot describe: the phase is
  // done and the artifact still is not coming.
  if (error) {
    return (
      <div className={styles.placeholder}>
        <span>The mesh could not be loaded.</span>
      </div>
    );
  }

  // Before phase 3 lands there is nothing to render, so the frame states where phase
  // 3 is instead. Phase 3's own status and no other: while phase 2 compiles, phase 3
  // has not started, and a frame reporting itself as running would be inventing the
  // one thing this component is not allowed to invent.
  if (!jobId || !isPhase3Complete) {
    return (
      <StageState
        phase={3}
        status={stageStatus(phases.find(p => p.phase === 3)?.status)}
        logLines={logLines}
        fill
      />
    );
  }

  return (
    <div className={styles.viewport}>
      <div className={styles.grid} aria-hidden="true" />
      <div ref={mountRef} className={styles.canvas} />
      {/* The mesh is on the wire but not yet parsed. The phase is genuinely done, so
          the note says what is actually happening rather than letting the derived
          line report a finished phase over an empty frame. */}
      {loading && <StageState phase={3} status="done" note="Loading the mesh" fill />}
    </div>
  );
}
