# BEZUBAAN Saathi

They have no voice. We can be theirs.

Stray animal emergency reporting and rescue dispatch for the IIT Roorkee campus:
report an injured animal with a photo, triage cases by urgency, dispatch the
nearest rescue van, resolve cases and track hotspots.

Duplicate detection runs in the browser in three layers: photo fingerprint (pHash),
wound and marking patterns (OpenCV ORB), and an AI image model (CLIP ViT-B/32,
LAION-400M, 4-bit ONNX) that recognises the same animal from another angle, pose
or background. The model is split into `clip-part1.bin` … `clip-part3.bin`
(keep them next to `index.html`).

Live site: https://iiaea.github.io/bezubaan-saathi/
