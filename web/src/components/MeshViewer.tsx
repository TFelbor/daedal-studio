import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { Box } from 'lucide-react';

// OrbitControls is usually available here in modern three.js installations
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

interface MeshViewerProps {
  jobId: string | null;
  status: string;
  phases: any[];
}

function parseOBJ(text: string) {
  const positions: number[] = [];
  const vertices: number[] = [];
  const lines = text.split('\n');
  for (const line of lines) {
    const parts = line.trim().split(/\s+/);
    if (parts[0] === 'v') {
      vertices.push(parseFloat(parts[1]), parseFloat(parts[2]), parseFloat(parts[3]));
    } else if (parts[0] === 'f') {
      const faceIndices: number[] = [];
      for (let i = 1; i < parts.length; i++) {
        if (!parts[i]) continue;
        const index = parseInt(parts[i].split('/')[0], 10) - 1;
        faceIndices.push(index);
      }
      for (let i = 1; i < faceIndices.length - 1; i++) {
        const i1 = faceIndices[0] * 3;
        const i2 = faceIndices[i] * 3;
        const i3 = faceIndices[i + 1] * 3;
        positions.push(
          vertices[i1], vertices[i1+1], vertices[i1+2],
          vertices[i2], vertices[i2+1], vertices[i2+2],
          vertices[i3], vertices[i3+1], vertices[i3+2]
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
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);

  // Check if phase 3 (Engineer) or later is complete
  const phase3Status = phases.find(p => p.phase === 3)?.status;
  const isPhase3Complete = phase3Status === 'complete';

  useEffect(() => {
    if (!jobId || !isPhase3Complete || !mountRef.current) return;

    let isActive = true;
    const currentMount = mountRef.current;
    
    // Setup scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#f5f5f5');
    
    const width = currentMount.clientWidth;
    const height = currentMount.clientHeight;
    
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    camera.position.set(0, 50, 150);
    
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    rendererRef.current = renderer;
    
    // Clear any previous canvas
    while (currentMount.firstChild) {
      currentMount.removeChild(currentMount.firstChild);
    }
    currentMount.appendChild(renderer.domElement);
    
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 2.0;

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);
    
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLight.position.set(10, 20, 10);
    scene.add(dirLight);

    let mesh: THREE.Mesh | null = null;
    let animationFrameId: number;

    const animate = () => {
      if (!isActive) return;
      animationFrameId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };

    setLoading(true);
    
    const fetchMesh = (retries: number) => {
      if (!isActive) return;
      fetch(`/jobs/${jobId}/mesh?t=${Date.now()}`)
        .then(res => {
          if (!res.ok) throw new Error('Mesh not ready');
          return res.text();
        })
        .then(text => {
          if (!isActive) return;
        const geometry = parseOBJ(text);
        
        // Center and scale geometry
        geometry.computeBoundingBox();
        const bbox = geometry.boundingBox;
        if (bbox) {
          const center = new THREE.Vector3();
          bbox.getCenter(center);
          geometry.translate(-center.x, -center.y, -center.z);
          
          const size = new THREE.Vector3();
          bbox.getSize(size);
          const maxDim = Math.max(size.x, size.y, size.z);
          const scale = 80 / maxDim; // Fit nicely in view
          geometry.scale(scale, scale, scale);
        }
        
        const material = new THREE.MeshStandardMaterial({ 
          color: '#3b82f6', 
          roughness: 0.5,
          metalness: 0.1
        });
        mesh = new THREE.Mesh(geometry, material);
        scene.add(mesh);
        
        setLoading(false);
        animate();
        })
        .catch(err => {
          if (!isActive) return;
          if (retries > 0) {
            setTimeout(() => fetchMesh(retries - 1), 2000);
          } else {
            console.error(err);
            setError(true);
            setLoading(false);
          }
        });
    };
    
    fetchMesh(3);

    const handleResize = () => {
      if (!currentMount || !renderer) return;
      const w = currentMount.clientWidth;
      const h = currentMount.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      isActive = false;
      window.removeEventListener('resize', handleResize);
      if (animationFrameId) cancelAnimationFrame(animationFrameId);
      if (renderer) renderer.dispose();
      if (mesh) {
        mesh.geometry.dispose();
        (mesh.material as THREE.Material).dispose();
      }
      if (currentMount && renderer.domElement) {
        try { currentMount.removeChild(renderer.domElement); } catch (e) {}
      }
    };
  }, [jobId, isPhase3Complete]);

  if (!jobId || !isPhase3Complete || error) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', minHeight: '300px', border: '2px dashed #ccc',
        borderRadius: '8px', color: '#666', flexDirection: 'column',
        backgroundColor: '#f9f9f9'
      }}>
        <Box size={48} color="#ccc" style={{ marginBottom: '16px' }} />
        <p>{error ? "Error loading 3D model" : "3D model will appear here"}</p>
      </div>
    );
  }

  return (
    <div style={{ position: 'relative', height: '100%', minHeight: '300px', borderRadius: '8px', overflow: 'hidden' }}>
      {loading && (
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
          backgroundColor: 'rgba(255,255,255,0.8)', zIndex: 10
        }}>
          <p style={{ fontWeight: 500, color: '#3b82f6' }}>Loading mesh...</p>
        </div>
      )}
      <div ref={mountRef} style={{ width: '100%', height: '100%' }} />
    </div>
  );
}
