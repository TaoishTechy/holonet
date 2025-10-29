// Optional WebGL path (kept minimal; CPU-first preference).
// We render simple points; if WebGL fails, we auto-disable.

let gl = null;
let program = null;
let webglActive = false;

export function setWebGLActive(v){ webglActive = v; }

export async function ensureWebGL(canvas){
  if (gl) return true;
  try{
    gl = canvas.getContext('webgl2', { antialias: true, alpha:false });
    if (!gl) gl = canvas.getContext('webgl', { antialias:true, alpha:false });
    if (!gl) return false;

    const vsSrc = `#version 100
attribute vec2 a_pos;
attribute float a_size;
varying float v_size;
void main(){
  gl_Position = vec4(a_pos, 0.0, 1.0);
  gl_PointSize = a_size;
  v_size = a_size;
}`;
    const fsSrc = `#ifdef GL_ES
precision mediump float;
#endif
void main(){
  float d = length(gl_PointCoord.xy - vec2(0.5));
  if (d>0.5) discard;
  gl_FragColor = vec4(0.35,0.69,1.0,1.0);
}`;
    const vs = gl.createShader(gl.VERTEX_SHADER);
    gl.shaderSource(vs, vsSrc); gl.compileShader(vs);
    if (!gl.getShaderParameter(vs, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(vs));
    const fs = gl.createShader(gl.FRAGMENT_SHADER);
    gl.shaderSource(fs, fsSrc); gl.compileShader(fs);
    if (!gl.getShaderParameter(fs, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(fs));
    program = gl.createProgram();
    gl.attachShader(program, vs); gl.attachShader(program, fs); gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    return true;
  }catch(e){
    console.warn('WebGL init failed', e);
    gl = null; program = null;
    return false;
  }
}

export function renderWebGL(pkt, canvas){
  if (!webglActive || !gl || !program){ return; }
  // resize
  const dpr = Math.max(1, window.devicePixelRatio||1);
  const w = canvas.clientWidth|0, h = canvas.clientHeight|0;
  if (canvas.width !== (w*dpr)|0 || canvas.height !== (h*dpr)|0){
    canvas.width = (w*dpr)|0; canvas.height = (h*dpr)|0;
  }
  gl.viewport(0,0,canvas.width,canvas.height);
  gl.clearColor(0.02,0.03,0.05,1); gl.clear(gl.COLOR_BUFFER_BIT);

  const vsLoc = gl.getAttribLocation(program, 'a_pos');
  const szLoc = gl.getAttribLocation(program, 'a_size');

  const verts = [];
  const sizes = [];
  for (const v of (pkt.vortices||[])){
    const cx = v.center?.[0] ?? 0;
    const cy = v.center?.[1] ?? 0;
    const x = (cx/1.5);
    const y = (cy/1.5);
    verts.push(x, -y);
    const amp = Math.max(0, Math.min(1, v.amp ?? 0.5));
    sizes.push(4 + 18*amp);
  }

  const vb = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vb);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(verts), gl.DYNAMIC_DRAW);
  gl.enableVertexAttribArray(vsLoc);
  gl.vertexAttribPointer(vsLoc, 2, gl.FLOAT, false, 0, 0);

  const sb = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, sb);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(sizes), gl.DYNAMIC_DRAW);
  gl.enableVertexAttribArray(szLoc);
  gl.vertexAttribPointer(szLoc, 1, gl.FLOAT, false, 0, 0);

  gl.drawArrays(gl.POINTS, 0, verts.length/2);

  gl.deleteBuffer(vb);
  gl.deleteBuffer(sb);
}
