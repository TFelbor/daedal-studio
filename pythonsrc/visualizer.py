import time
import torch
from diffusers import DiffusionPipeline

class Visualizer:
    def __init__(self, model_id="black-forest-labs/FLUX.2-klein-4B"):
        print(f"Loading {model_id}...")

        # 1. Load using the Generic Auto-Loader
        # Now that you updated, 'DiffusionPipeline' will successfully find 'Flux2KleinPipeline'
        self.pipe = DiffusionPipeline.from_pretrained(
            model_id,
            torch_dtype=torch.bfloat16
        )

        # 2. Optimize for Mac M4
        self.pipe.to("mps")
        print("Model loaded successfully.")

    def generate_blueprint(self, prompt, output_path="inputs/blueprint.png"):
            # CTO UPDATE: We inject "Clay Render" keywords to force 3D-readable shading.
            # This helps TripoSR see depth (Shape-from-Shading).
            engineered_prompt = (
                f"3d blender render of {prompt}, "
                "neutral background, high fidelity, 8k, soft studio lighting, "
                "solid object, thick solid geometry, smooth curves, clay material"
            )

            print(f"Generating: '{engineered_prompt}'...")
            start = time.time()

            image = self.pipe(
                prompt=engineered_prompt,
                num_inference_steps=4,
                guidance_scale=3.5,
                height=1024,
                width=1024,
                generator=torch.Generator("mps").manual_seed(int(time.time()))
            ).images[0]

            image.save(output_path)
            print(f"Saved to {output_path} ({time.time() - start:.2f}s)")
            return output_path

if __name__ == "__main__":
    viz = Visualizer()
    viz.generate_blueprint(
        prompt="futuristic robot dinosaur")
