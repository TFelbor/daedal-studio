import os
import numpy as np
# Force CPU fallback for M4 Mac compatibility
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

import torch
import trimesh
from PIL import Image, ImageOps
from tsr.system import TSR
from tsr.utils import remove_background, resize_foreground

# === MONKEY PATCH: Fix for M4/MPS ===
from tsr.models.isosurface import MarchingCubeHelper
original_forward = MarchingCubeHelper.forward
def patched_forward(self, level):
    return original_forward(self, level.cpu())
MarchingCubeHelper.forward = patched_forward
# ====================================

class P2PSculptor:
    def __init__(self):
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        print(f"[*] Initializing Sculptor on device: {self.device}")

        base_path = os.path.dirname(os.path.abspath(__file__))
        model_dir = os.path.join(base_path, "models", "TripoSR")

        self.model = TSR.from_pretrained(
            model_dir,
            config_name="config.yaml",
            weight_name="model.ckpt"
        )
        self.model.to(self.device)
        self.model.eval()

    def generate_mesh(self, image_path, output_path):
        print(f"[*] Processing image: {image_path}")
        image = Image.open(image_path)

        # 1. Pre-processing: Clean the Input
        image = remove_background(image)
        image = resize_foreground(image, 0.85)

        # CTO FIX: Clean the Alpha Channel (The "Dirty Mask" Fix)
        # Sometimes rembg leaves faint pixels (value 1-10) in the empty space.
        # This forces anything not fully visible to be 100% transparent.
        if image.mode == 'RGBA':
            r, g, b, a = image.split()
            # If pixel is less than 10% opaque, kill it. Else make it solid.
            a = a.point(lambda p: 255 if p > 50 else 0)
            image = Image.merge('RGBA', (r, g, b, a))

        # CTO FIX: Use NEUTRAL GRAY Background
        # Black (0) = Void? Solid?
        # White (255) = Wall? Light?
        # Gray (127) = Neutral Studio. The safest bet for AI.
        bg_color = (127, 127, 127)

        if image.mode == 'RGBA':
            bg = Image.new("RGB", image.size, bg_color)
            bg.paste(image, mask=image.split()[3])
            image = bg
        else:
            image = image.convert("RGB")

        image.save("inputs/debug_final_view.png")

        # 2. Inference
        with torch.no_grad():
            scene_codes = self.model([image], device=self.device)

            # CTO FIX: Raise the Threshold!
            # Default is 25.0. We raise it to 45.0 to cut away the "Air Block".
            # If it's still blocky, try 60.0. If it disappears, lower to 30.0.
            meshes = self.model.extract_mesh(
                scene_codes,
                has_vertex_color=False,
                resolution=256,
                threshold=45.0
            )

            main_mesh = meshes[0]

            # 3. Post-Processing
            print("[*] Optimizing Mesh Topology...")

            # Rotation Fix (Stand it up)
            rotation_matrix = trimesh.transformations.rotation_matrix(
                -np.pi / 2, [1, 0, 0]
            )
            main_mesh.apply_transform(rotation_matrix)

            # Cleanup artifacts
            components = main_mesh.split(only_watertight=False)
            if len(components) > 0:
                # Get the biggest thing (The Object)
                main_mesh = max(components, key=lambda m: m.extents.max())

            # Polish (Subdivide + Taubin)
            main_mesh = main_mesh.subdivide()
            trimesh.smoothing.filter_taubin(main_mesh, iterations=10)

            # Export
            main_mesh.export(output_path)
            print(f"[+] Final Mesh generated at: {output_path}")

if __name__ == "__main__":
    sculptor = P2PSculptor()
    sculptor.generate_mesh("inputs/blueprint.png", "outputs/test_mesh.obj")
