import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { Box } from 'lucide-react';
import styles from './MeshViewer.module.css';

interface PhaseLike {
  phase: number;
  status: string;
}

interface MeshViewerProps {
  jobId: string | null;
  status: string;
  phases: PhaseLike[];
}

/** Read a design token so the scene cannot drift from the stylesheet. */
function token(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

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

export function MeshViewer({ jobId, phases }: MeshViewerProps) {
  const mountRef = useRef<HTMLDivElement>(null);
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
    scene.background = new THREE.Color(token('--raised', '#1e1e1e'));

    const width = currentMount.clientWidth || 1;
    const height = currentMount.clientHeight || 1;

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    camera.position.set(0, 40, 150);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);

    while (currentMount.firstChild) currentMount.removeChild(currentMount.firstChild);
    currentMount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.autoRotate = true;
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

    const animate = () => {
      if (!isActive) return;
      animationFrameId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };

    setLoading(true);
    setError(false);

    const fetchMesh = (retries: number) => {
      if (!isActive) return;
      fetch(`/jobs/${jobId}/mesh?t=${Date.now()}`)
        .then((res) => {
          if (!res.ok) throw new Error('Mesh not ready');
          return res.text();
        })
        .then((text) => {
          if (!isActive) return;
          const geometry = parseOBJ(text);

          // The pipeline exports Z-up (print-bed convention); three.js is Y-up.
          // Without this the part is displayed lying on its back, which is exactly
          // the silent failure the sculptor's up-axis handling exists to prevent.
          geometry.rotateX(-Math.PI / 2);

          geometry.computeBoundingBox();
          const bbox = geometry.boundingBox;
          if (bbox) {
            const center = new THREE.Vector3();
            bbox.getCenter(center);
            geometry.translate(-center.x, -center.y, -center.z);

            const size = new THREE.Vector3();
            bbox.getSize(size);
            const maxDim = Math.max(size.x, size.y, size.z) || 1;
            const scale = 80 / maxDim;
            geometry.scale(scale, scale, scale);
          }

          // Fully dielectric and almost fully rough: printed plastic, not chrome.
          // Any metalness at all puts a specular sheen on a white surface that
          // reads as metal, which is not what will come off the bed.
          const material = new THREE.MeshStandardMaterial({
            color: token('--ink', '#f2f0ed'),
            roughness: 0.95,
            metalness: 0,
            flatShading: false,
          });
          mesh = new THREE.Mesh(geometry, material);
          scene.add(mesh);

          setLoading(false);
          animate();
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

    fetchMesh(3);

    const handleResize = () => {
      const w = currentMount.clientWidth;
      const h = currentMount.clientHeight;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      isActive = false;
      window.removeEventListener('resize', handleResize);
      if (animationFrameId) cancelAnimationFrame(animationFrameId);
      if (mesh) {
        mesh.geometry.dispose();
        (mesh.material as THREE.Material).dispose();
      }
      controls.dispose();
      renderer.dispose();
      // Browsers cap live WebGL contexts (~16); without this, navigating back and
      // forth between jobs eventually kills the oldest viewer on the page.
      renderer.forceContextLoss();
      try {
        currentMount.removeChild(renderer.domElement);
      } catch {
        /* already detached */
      }
    };
  }, [jobId, isPhase3Complete]);

  if (!jobId || !isPhase3Complete || error) {
    return (
      <div className={styles.placeholder}>
        <Box size={28} strokeWidth={1.5} aria-hidden="true" />
        <span>{error ? 'The mesh could not be loaded.' : 'The mesh appears here once phase 03 completes.'}</span>
      </div>
    );
  }

  return (
    <div className={styles.viewport}>
      <div className={styles.grid} aria-hidden="true" />
      <div ref={mountRef} className={styles.canvas} />
      {loading && <span className={styles.loading}>Loading mesh…</span>}
    </div>
  );
}
