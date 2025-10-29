// Placeholder WebGL toggle — optional GPU path. Graceful fallback if unavailable.
export class Renderer3D {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    this.ready = !!this.gl;
    if (!this.ready) console.warn('WebGL not available; staying on CPU 2D renderer');
  }
  setPacket(_pkt) {}
  frame() {
    if (!this.ready) return;
    const gl = this.gl;
    gl.viewport(0,0,gl.canvas.width, gl.canvas.height);
    gl.clearColor(0.03,0.05,0.12,1);
    gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    // TODO: add lightweight point rendering shader if GPU is allowed
  }
}
