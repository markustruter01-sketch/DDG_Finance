import { useRef, useEffect, useState } from "react";

const VS = `attribute vec2 aPos; void main(){ gl_Position = vec4(aPos,0.0,1.0); }`;

const FS = `
precision highp float;
uniform vec2  uRes;
uniform float uTime;
uniform float uTheta;
uniform float uPhi;
uniform float uRadius;

#define PI  3.14159265359
#define TAU 6.28318530718

const float LENSING = 100.0;
const float SPIN    = 0.3;
const float INNER   = 2.2;
const float OUTER   = 11.0;
const float DOPPLER = 100.0;
const float BLOOM   = 1.6;

float hash(vec3 p){
  p = fract(p*0.3183099 + vec3(0.1,0.2,0.3));
  p *= 17.0;
  return fract(p.x*p.y*p.z*(p.x+p.y+p.z));
}
float noise(vec3 p){
  vec3 i=floor(p); vec3 f=fract(p);
  f=f*f*(3.0-2.0*f);
  return mix(mix(mix(hash(i+vec3(0,0,0)),hash(i+vec3(1,0,0)),f.x),
                 mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
             mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),
                 mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);
}
float fbm(vec3 p){
  float v=0.0,a=0.5;
  for(int i=0;i<4;i++){ v+=a*noise(p); p*=2.0; a*=0.5; }
  return v;
}

vec3 starField(vec3 rd){
  float u=atan(rd.z,rd.x), v=asin(clamp(rd.y,-1.0,1.0));
  vec2 uv=vec2(u,v)*vec2(80.0,50.0);
  vec3 col=vec3(0.0);
  for(int layer=0;layer<3;layer++){
    float scale=1.0+float(layer)*0.6;
    vec2 sUV=uv*scale, id=floor(sUV), f=fract(sUV);
    float h1=fract(sin(dot(id,vec2(127.1,311.7)))*43758.5453);
    float h2=fract(sin(dot(id,vec2(269.5,183.3)))*43758.5453);
    float h3=fract(sin(dot(id,vec2(419.2,371.9)))*43758.5453);
    if(h1<0.985-float(layer)*0.05) continue;
    vec2 starPos=vec2(h2,h3), pos=starPos-f;
    float d=length(pos);
    float star=smoothstep(0.05,0.0,d)+smoothstep(0.15,0.0,d)*0.3;
    float twinkle=0.7+0.3*sin(uTime*2.0+h1*TAU);
    vec3 starCol=h2>0.7?vec3(0.7,0.8,1.0):h2<0.2?vec3(1.0,0.9,0.7):vec3(1.0);
    col+=starCol*star*twinkle*(1.0-float(layer)*0.25);
  }
  return col*0.9;
}

float diskDensity(vec3 p){
  float r=length(p.xz);
  if(r<INNER*0.95||r>OUTER) return 0.0;
  float radial=smoothstep(INNER*0.95,INNER+0.5,r)*smoothstep(OUTER,OUTER-3.0,r);
  float h=abs(p.y);
  float thickness=0.06+r*0.011;
  float vertical=exp(-(h*h)/(thickness*thickness));
  // Sample noise in stationary world-space coords + independent time drifts per layer.
  // No rotation-winding in the sample coordinates → concentric-ring artifact impossible.
  // Visual disk rotation comes from Doppler shift + lensing, not from noise winding.
  vec3 swirl=vec3(p.x,p.z,uTime*0.25)*0.22;
  float base=mix(0.3,1.3,fbm(swirl));
  vec3 plasma1=vec3(p.x+uTime*0.18,p.z-uTime*0.12,uTime*0.9)*0.28;
  float pTurb1=mix(0.2,1.6,fbm(plasma1));
  vec3 plasma2=vec3(p.x-uTime*0.07,p.z+uTime*0.09,-uTime*0.45)*0.13;
  float pTurb2=mix(0.4,1.4,fbm(plasma2));
  return radial*vertical*base*pTurb1*pTurb2*0.85;
}

vec3 diskEmission(vec3 p, float density){
  float r=length(p.xz);
  float sinAngle=p.z/max(r,0.001);
  float t=pow(1.0-smoothstep(INNER,OUTER*0.75,r),0.8);
  vec3 c1=vec3(0.50,0.06,0.0),c2=vec3(1.00,0.28,0.02),c3=vec3(1.00,0.58,0.10),c4=vec3(1.00,0.90,0.55);
  vec3 col=mix(c1,c2,smoothstep(0.0,0.3,t));
  col=mix(col,c3,smoothstep(0.3,0.65,t));
  col=mix(col,c4,smoothstep(0.65,1.0,t));
  float dop=sinAngle*(DOPPLER/100.0)*0.6;
  col*=max(0.3,1.0+dop*0.7);
  col=mix(col,col*vec3(0.6,0.8,1.5),max(0.0,dop)*0.3);
  col=mix(col,col*vec3(1.5,0.6,0.3),max(0.0,-dop)*0.3);
  // Stationary world-space blob — no winding, no rings
  float blob=fbm(vec3(p.x+uTime*0.05,p.z-uTime*0.03,uTime*0.08)*0.18);
  float variation=mix(0.5,1.5,blob);
  float boost=6.0/(r*0.35+0.25);
  return col*density*boost*variation;
}

void main(){
  vec2 uv=(gl_FragCoord.xy-0.5*uRes)/min(uRes.x,uRes.y);

  float sp=sin(uPhi),cp=cos(uPhi),st=sin(uTheta),ct=cos(uTheta);
  vec3 camPos=vec3(uRadius*sp*ct,uRadius*cp,uRadius*sp*st);
  vec3 forward=normalize(-camPos);
  vec3 worldUp=abs(cp)<0.985?vec3(0,1,0):vec3(1,0,0);
  vec3 right=normalize(cross(forward,worldUp));
  vec3 up=normalize(cross(right,forward));
  vec3 rd=normalize(forward+uv.x*right*0.9+uv.y*up*0.9);
  vec3 ro=camPos;

  vec3 accum=vec3(0.0);
  float trans=1.0;
  bool swallowed=false;
  float minR=1e9,t=0.0,dt=0.1;
  float prevY=ro.y;

  for(int i=0;i<200;i++){
    float r=length(ro);
    minR=min(minR,r);
    if(r<1.0){ swallowed=true; break; }
    dt=r<3.0?clamp(r*0.05,0.02,0.15):clamp(r*0.09,0.15,0.5);
    float gm=0.75*(LENSING/100.0);
    rd=normalize(rd-ro*(gm/(r*r*r))*dt);
    vec3 nextRo=ro+rd*dt;
    float nextY=nextRo.y;
    if(prevY*nextY<0.0&&trans>0.01){
      float frac=abs(prevY)/(abs(prevY)+abs(nextY));
      vec3 hit=mix(ro,nextRo,frac);
      float hitR=length(hit.xz);
      if(hitR>=INNER&&hitR<=OUTER){
        float dens=diskDensity(hit);
        if(dens>0.001){
          vec3 em=diskEmission(hit,dens);
          float alpha=clamp(dens*0.37,0.0,0.92);
          accum+=em*alpha*trans;
          trans*=(1.0-alpha);
        }
      }
    }
    prevY=nextY; ro=nextRo; t+=dt;
    if(t>80.0||trans<0.005) break;
  }

  if(!swallowed) accum+=starField(rd)*trans;

  if(!swallowed){
    float ring=exp(-pow((minR-1.5)/0.10,2.0));
    accum+=vec3(1.0,0.55,0.15)*ring*smoothstep(2.0,1.5,minR)*2.2*trans;
    float ring2=exp(-pow((minR-1.06)/0.03,2.0));
    accum+=vec3(1.0,0.70,0.25)*ring2*1.0*trans;
  }

  if(!swallowed&&minR<2.5){
    float coronaR=exp(-pow((minR-1.15)/0.25,2.0));
    float shimmer=sin(uTime*17.3+minR*41.0)*sin(uTime*11.7-minR*19.0)*0.5+0.5;
    accum+=vec3(1.0,0.65,0.25)*coronaR*shimmer*0.35;
  }

  float lum=dot(accum,vec3(0.2126,0.7152,0.0722));
  accum+=accum*smoothstep(0.3,1.5,lum)*(BLOOM/10.0)*1.2;
  accum+=vec3(1.0,0.4,0.05)*smoothstep(0.6,2.5,lum)*(BLOOM/10.0)*0.4;
  vec3 a=accum*0.5;
  vec3 mapped=(a*(2.51*a+0.03))/(a*(2.43*a+0.59)+0.14);
  mapped=pow(clamp(mapped,0.0,1.0),vec3(0.4545));
  gl_FragColor=vec4(mapped,1.0);
}
`;

const RES_SCALE = 0.85;

export function TradingEngineBlackHole() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [webglFailed, setWebglFailed] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = (
      canvas.getContext("webgl", { antialias: true }) ||
      canvas.getContext("experimental-webgl", { antialias: true })
    ) as WebGLRenderingContext | null;
    if (!gl) {
      setWebglFailed(true);
      return;
    }

    function shader(type: number, src: string): WebGLShader {
      const s = gl!.createShader(type)!;
      gl!.shaderSource(s, src);
      gl!.compileShader(s);
      if (!gl!.getShaderParameter(s, gl!.COMPILE_STATUS))
        console.error(gl!.getShaderInfoLog(s));
      return s;
    }

    const prog = gl.createProgram()!;
    gl.attachShader(prog, shader(gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      console.error("Program link error:", gl.getProgramInfoLog(prog));
      setWebglFailed(true);
      return;
    }
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const posLoc = gl.getAttribLocation(prog, "aPos");
    gl.enableVertexAttribArray(posLoc);
    gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

    const U: Record<string, WebGLUniformLocation | null> = {};
    ["uRes", "uTime", "uTheta", "uPhi", "uRadius"].forEach(
      (n) => (U[n] = gl.getUniformLocation(prog, n))
    );

    let W = 0, H = 0;

    function resize() {
      W = Math.floor(window.innerWidth * RES_SCALE);
      H = Math.floor(window.innerHeight * RES_SCALE);
      canvas.width = W;
      canvas.height = H;
      canvas.style.width = window.innerWidth + "px";
      canvas.style.height = window.innerHeight + "px";
      gl.viewport(0, 0, W, H);
      gl.uniform2f(U.uRes, W, H);
    }
    window.addEventListener("resize", resize);
    resize();

    let camTheta = 0.5, camPhi = 1.45, camRadius = 16.0;
    let tTheta = camTheta, tPhi = camPhi, tRadius = camRadius;
    let drag = false, lx = 0, ly = 0;

    canvas.addEventListener("mousedown", (e) => { drag = true; lx = e.clientX; ly = e.clientY; });
    window.addEventListener("mouseup", () => drag = false);
    window.addEventListener("mousemove", (e) => {
      if (!drag) return;
      tTheta -= (e.clientX - lx) * 0.006;
      tPhi = Math.max(0.05, Math.min(Math.PI - 0.05, tPhi + (e.clientY - ly) * 0.006));
      lx = e.clientX; ly = e.clientY;
    });
    canvas.addEventListener("wheel", (e) => {
      tRadius = Math.max(3.0, Math.min(50.0, tRadius + e.deltaY * 0.03));
      e.preventDefault();
    }, { passive: false });
    canvas.addEventListener("touchstart", (e) => { drag = true; lx = e.touches[0].clientX; ly = e.touches[0].clientY; });
    canvas.addEventListener("touchend", () => drag = false);
    canvas.addEventListener("touchmove", (e) => {
      if (!drag) return;
      tTheta -= (e.touches[0].clientX - lx) * 0.006;
      tPhi = Math.max(0.05, Math.min(Math.PI - 0.05, tPhi + (e.touches[0].clientY - ly) * 0.006));
      lx = e.touches[0].clientX; ly = e.touches[0].clientY;
      e.preventDefault();
    }, { passive: false });

    let rafId = 0;
    let lastNow = 0;

    function frame(now: number) {
      rafId = requestAnimationFrame(frame);
      if (document.hidden) { lastNow = now; return; }
      const dt = Math.min((now - lastNow) * 0.001, 0.05); // seconds, capped at 50ms
      lastNow = now;
      // Auto-orbit: full 360° in ~90s when user is not dragging
      if (!drag) tTheta += dt * 0.07;
      const s = 0.08;
      camTheta += (tTheta - camTheta) * s;
      camPhi   += (tPhi   - camPhi)   * s;
      camRadius += (tRadius - camRadius) * s;
      gl.uniform1f(U.uTime,   now * 0.001);
      gl.uniform1f(U.uTheta,  camTheta);
      gl.uniform1f(U.uPhi,    camPhi);
      gl.uniform1f(U.uRadius, camRadius);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
    rafId = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", resize);
      gl.deleteProgram(prog);
      gl.deleteBuffer(buf);
    };
  }, []);

  if (webglFailed) {
    return (
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "#000",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span style={{ color: "rgba(148,163,184,0.4)", fontFamily: "monospace", fontSize: 12 }}>
          WebGL not supported
        </span>
      </div>
    );
  }

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: "absolute",
        inset: 0,
        display: "block",
        cursor: "crosshair",
      }}
    />
  );
}
