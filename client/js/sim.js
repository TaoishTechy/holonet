// Minimal CPU simulator used when no WS feed present
let timer = 0;
let t0 = performance.now();
let entities = [];

export function startSim(){
  if (timer) return;
  if (entities.length === 0){
    // seed 12 entities in a 3x4 grid-ish
    for (let i=0;i<12;i++){
      entities.push({
        entity: 's'+(i+1),
        glyphs: [['Ω','Ψ','Φ'], ['⊗','⊕','⦿'], ['Θ','!','⟳'], ['*','✶','✺']][i%4],
        amp: 0.5 + 0.1*Math.sin(i),
        phase: (i*0.7)%6.283,
        center: [ (i%4)-1.5, (Math.floor(i/4))-1.0, 0 ],
        entangled: [],
        healing_properties: {},
      });
    }
  }
  timer = setInterval(() => {
    const dt = (performance.now()-t0)/1000;
    entities.forEach((v,i)=>{
      v.phase = (v.phase + 1.2*dt) % 6.283;
      v.amp = 0.5 + 0.25*Math.sin((performance.now()/500)+i);
      v.center[0] += 0.02 * ((i%2)?1:-1);
      if (Math.random()<0.02){
        const j = (i+1)%entities.length;
        v.entangled = [entities[j].entity];
      }
    });
    t0 = performance.now();
  }, 50);
}

export function stopSim(){
  if (timer){ clearInterval(timer); timer = 0; }
}

export function simFrame(){
  return { ver:'1.2', vortices: entities, meta_reflection: { coherence: 0.66 } };
}
