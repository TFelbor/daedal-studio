# Pipeline Architecture

The Prompt2Print generative engine works asynchronously across five core phases. Here is how your text prompt becomes a physical object.

## Phase 1: Visualizer
**Input**: Text Prompt  
**Output**: 2D Blueprint Image  
We use the state-of-the-art **FLUX.2-klein-4B** model to generate a clay-rendered image that clearly defines the geometry of the requested object.

## Phase 2: Sculptor
**Input**: 2D Blueprint Image  
**Output**: Raw 3D Mesh (.obj)  
The system uses **TripoSR** to perform neural implicit surface extraction, turning the 2D image into a full 3D mesh. We then apply Taubin smoothing to reduce noise.

## Phase 3: Engineer
**Input**: Raw 3D Mesh  
**Output**: Engineered Mesh (.obj)  
Raw AI meshes often have holes, inverted normals, or incorrect scaling. We use `manifold3d` and `trimesh` to decimate polygon counts, repair the manifold, and scale the object to fit safely on your printer's build volume.

## Phase 4: Slicer
**Input**: Engineered Mesh  
**Output**: G-code  
The repaired mesh is passed to a headless instance of **CuraEngine** running in Docker. Using bundled machine profiles (e.g., Ender 3), it generates the exact toolpath instructions needed by your printer.

## Phase 5: Operator
**Input**: G-code  
**Output**: Physical Print  
Finally, a firmware-specific operator (like the OctoPrint Operator) uploads the G-code via REST API and commands the printer to begin.
