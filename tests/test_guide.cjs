const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { landmarkPosition } = require('../apps/web/capture-core.js');

function environment() {
  const calls = [], elements = new Map();
  const methods = ['clearRect','save','restore','translate','scale','rotate','beginPath','moveTo','lineTo',
    'stroke','arc','fill','ellipse','roundRect','fillText'];
  const context = Object.fromEntries(methods.map((name) => [name, (...args) => calls.push({name,args})]));
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {hidden:false, textContent:'', attrs:{},
      getContext: () => context, getBoundingClientRect: () => ({width:800,height:450}),
      setAttribute(name,value) {this.attrs[name]=value;}});
    return elements.get(id);
  };
  const sandbox = {window:{devicePixelRatio:1, matchMedia:() => ({matches:true,addEventListener(){}})},
    document:{hidden:false,getElementById:element,addEventListener(){}}, performance:{now:()=>2000},
    KineCapture:{landmarkPosition}, requestAnimationFrame(){return 1;}, cancelAnimationFrame(){}};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(require.resolve('../apps/web/guide.js'),'utf8'),sandbox);
  return {guide:sandbox.window.KineGuide, element, calls};
}
test('all seven avatar gestures remain visible, including reduced-motion mode', () => {
  const env = environment();
  for (const id of ['elbow','knee','shoulder','hip','trunk','neck_tilt','neck_turn']) {
    env.guide.setProtocol(id,id); env.guide.setSide('right');
    assert.equal(env.element('guide-panel').hidden,false);
    assert.ok(env.element('guide-avatar').attrs['aria-label'].includes(id));
    assert.equal(env.element('guide-cue').textContent,'Illustration du geste');
  }
  assert.equal(env.guide.toggle,undefined);
  assert.equal(env.calls.filter((call) => call.name === 'save').length,env.calls.filter((call) => call.name === 'restore').length);
});
test('selected head/trunk points use their connections, not the old arm triple', () => {
  const env = environment(); env.calls.length = 0;
  env.guide.drawPose(env.element('overlay'),{width_px:640,height_px:480,protocol_id:'trunk_lateral_inclination',
    points:[{x:.3,y:.2},{x:.7,y:.2},{x:.4,y:.7},{x:.6,y:.7}],connections:[[0,1],[2,3]],
    shoulder:null,elbow:null,wrist:null},false);
  assert.equal(env.calls.filter((call) => call.name === 'stroke').length,6);
  assert.equal(env.calls.filter((call) => call.name === 'arc').length,8);
});
test('missing points never produce a connecting segment across an occlusion', () => {
  const env = environment(); env.calls.length = 0;
  env.guide.drawPose(env.element('overlay'),{width_px:640,height_px:480,
    points:[{x:.3,y:.2},null,{x:.4,y:.7}],connections:[[0,1],[1,2]]},true);
  assert.equal(env.calls.filter((call) => call.name === 'stroke').length,0);
});
