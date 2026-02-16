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
        print(f"Generating: '{prompt}'...")
        start = time.time()

        # 3. Generate
        image = self.pipe(
            prompt=prompt,
            num_inference_steps=4,  # Klein is fast
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
        "isometric diagram of a robot, space dinosaur, white background, technical drawing style"
    )
