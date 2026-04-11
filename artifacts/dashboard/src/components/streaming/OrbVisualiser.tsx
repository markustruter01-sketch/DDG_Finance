import { useRef, useMemo, useEffect, useState, Suspense } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Stars } from "@react-three/drei";
import * as THREE from "three";
import {
  useStatusSummary,
  useKrakenFleetSummary,
  useLivePositions,
  useLearningJournal,
  useKrakenStatus,
  useOptionsState,
  useForexState,
  useEquityCurve,
  useAuditorReport,
} from "@/hooks/use-trading";
import { onTradePulse } from "@/components/streaming/tradePulseEvents";

function checkWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
    return !!ctx;
  } catch {
    return false;
  }
}

const BOT_COLORS_CSS: Record<string, string> = {
  oracle:       "#8b5cf6",
  "davy-jones": "#22d3ee",
  blackbeard:   "#f97316",
  calypso:      "#a855f7",
  apex:         "#f59e0b",
  navigator:    "#10b981",
};

const BOT_COLORS_HEX: Record<string, THREE.ColorRepresentation> = {
  oracle:       0x8b5cf6,
  "davy-jones": 0x22d3ee,
  blackbeard:   0xf97316,
  calypso:      0xa855f7,
  apex:         0xf59e0b,
  navigator:    0x10b981,
};

const BOT_KEYS = Object.keys(BOT_COLORS_CSS);

function clamp01(v: number) { return Math.max(0, Math.min(1, v)); }

interface OrbData {
  openPositions: number;
  fleetEquityChange: number;
  activeBots: number;
  lastAiTs: number;
  tradePulse: { active: boolean; isWin: boolean; botName: string } | null;
  aiRipple: boolean;
}

function MoltenCore({ orbData }: { orbData: OrbData }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const matRef = useRef<THREE.ShaderMaterial>(null);
  const timeRef = useRef(0);
  const pulseRef = useRef(0);
  const rippleRef = useRef(0);

  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uPulse: { value: 0 },
    uRipple: { value: 0 },
    uPositions: { value: 0 },
    uEquityDir: { value: 0 },
  }), []);

  const vertexShader = `
    varying vec3 vNormal;
    varying vec3 vPosition;
    varying vec2 vUv;
    uniform float uTime;
    uniform float uRipple;

    vec3 mod289(vec3 x) { return x - floor(x * (1.0/289.0)) * 289.0; }
    vec4 mod289(vec4 x) { return x - floor(x * (1.0/289.0)) * 289.0; }
    vec4 permute(vec4 x) { return mod289(((x*34.0)+1.0)*x); }
    vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
    float snoise(vec3 v) {
      const vec2 C = vec2(1.0/6.0, 1.0/3.0);
      const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
      vec3 i = floor(v + dot(v, C.yyy));
      vec3 x0 = v - i + dot(i, C.xxx);
      vec3 g = step(x0.yzx, x0.xyz);
      vec3 l = 1.0 - g;
      vec3 i1 = min(g.xyz, l.zxy);
      vec3 i2 = max(g.xyz, l.zxy);
      vec3 x1 = x0 - i1 + C.xxx;
      vec3 x2 = x0 - i2 + C.yyy;
      vec3 x3 = x0 - D.yyy;
      i = mod289(i);
      vec4 p = permute(permute(permute(
        i.z + vec4(0.0, i1.z, i2.z, 1.0))
        + i.y + vec4(0.0, i1.y, i2.y, 1.0))
        + i.x + vec4(0.0, i1.x, i2.x, 1.0));
      float n_ = 0.142857142857;
      vec3 ns = n_ * D.wyz - D.xzx;
      vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
      vec4 x_ = floor(j * ns.z);
      vec4 y_ = floor(j - 7.0 * x_);
      vec4 x = x_ * ns.x + ns.yyyy;
      vec4 y = y_ * ns.x + ns.yyyy;
      vec4 h = 1.0 - abs(x) - abs(y);
      vec4 b0 = vec4(x.xy, y.xy);
      vec4 b1 = vec4(x.zw, y.zw);
      vec4 s0 = floor(b0) * 2.0 + 1.0;
      vec4 s1 = floor(b1) * 2.0 + 1.0;
      vec4 sh = -step(h, vec4(0.0));
      vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
      vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
      vec3 p0 = vec3(a0.xy, h.x);
      vec3 p1 = vec3(a0.zw, h.y);
      vec3 p2 = vec3(a1.xy, h.z);
      vec3 p3 = vec3(a1.zw, h.w);
      vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
      p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
      vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
      m = m * m;
      return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
    }

    void main() {
      vNormal = normal;
      vUv = uv;
      float n = snoise(position * 2.2 + uTime * 0.4);
      float n2 = snoise(position * 4.5 - uTime * 0.25);
      float rippleWave = uRipple * snoise(position * 6.0 + uTime * 2.0) * 0.08;
      vec3 displaced = position + normal * (n * 0.06 + n2 * 0.03 + rippleWave);
      vPosition = displaced;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(displaced, 1.0);
    }
  `;

  const fragmentShader = `
    varying vec3 vNormal;
    varying vec3 vPosition;
    varying vec2 vUv;
    uniform float uTime;
    uniform float uPulse;
    uniform float uPositions;
    uniform float uEquityDir;

    void main() {
      vec3 amber = vec3(1.0, 0.55, 0.1);
      vec3 orange = vec3(1.0, 0.3, 0.05);
      vec3 red = vec3(0.9, 0.1, 0.05);
      vec3 gold = vec3(1.0, 0.8, 0.2);

      float heat = clamp(uPositions / 10.0, 0.0, 1.0);
      vec3 baseColor = mix(amber, red, heat * 0.6);
      baseColor = mix(baseColor, gold, uPulse * 0.5);

      float rim = 1.0 - max(dot(normalize(vNormal), vec3(0.0, 0.0, 1.0)), 0.0);
      rim = pow(rim, 2.0);

      float glow = 0.5 + 0.5 * sin(uTime * 1.8 + vPosition.x * 3.0 + vPosition.y * 2.0);
      glow = mix(glow, 1.0, uPulse);

      vec3 finalColor = baseColor * (0.7 + 0.3 * glow);
      finalColor += vec3(0.8, 0.4, 0.1) * rim * 0.8;
      finalColor += vec3(1.0, 0.9, 0.5) * uPulse * 0.6;

      float alpha = 0.85 + rim * 0.15;
      gl_FragColor = vec4(finalColor, alpha);
    }
  `;

  useEffect(() => {
    if (!orbData.tradePulse?.active) return;
    pulseRef.current = 1.0;
  }, [orbData.tradePulse]);

  useEffect(() => {
    if (!orbData.aiRipple) return;
    rippleRef.current = 1.0;
  }, [orbData.aiRipple]);

  useFrame((_, delta) => {
    timeRef.current += delta;
    pulseRef.current = Math.max(0, pulseRef.current - delta * 1.2);
    rippleRef.current = Math.max(0, rippleRef.current - delta * 0.6);

    if (matRef.current) {
      matRef.current.uniforms.uTime.value = timeRef.current;
      matRef.current.uniforms.uPulse.value = pulseRef.current;
      matRef.current.uniforms.uRipple.value = rippleRef.current;
      matRef.current.uniforms.uPositions.value = orbData.openPositions;
      matRef.current.uniforms.uEquityDir.value = orbData.fleetEquityChange > 0 ? 1 : orbData.fleetEquityChange < 0 ? -1 : 0;
    }
    if (meshRef.current) {
      meshRef.current.rotation.y += delta * 0.12;
      meshRef.current.rotation.x += delta * 0.04;
    }
  });

  return (
    <mesh ref={meshRef}>
      <sphereGeometry args={[1.2, 64, 64]} />
      <shaderMaterial
        ref={matRef}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        uniforms={uniforms}
        transparent
      />
    </mesh>
  );
}

function ParticleField({ orbData }: { orbData: OrbData }) {
  const COUNT = 600;
  const meshRef = useRef<THREE.Points>(null);
  const timeRef = useRef(0);

  const { positions, speeds, phases, radii } = useMemo(() => {
    const positions = new Float32Array(COUNT * 3);
    const speeds = new Float32Array(COUNT);
    const phases = new Float32Array(COUNT);
    const radii = new Float32Array(COUNT);

    for (let i = 0; i < COUNT; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = 1.3 + Math.random() * 1.8;

      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);

      speeds[i] = 0.3 + Math.random() * 0.7;
      phases[i] = Math.random() * Math.PI * 2;
      radii[i] = r;
    }
    return { positions, speeds, phases, radii };
  }, []);

  const originalPositions = useMemo(() => new Float32Array(positions), [positions]);

  const geometry = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(positions), 3));
    return geo;
  }, [positions]);

  const material = useMemo(() => {
    return new THREE.PointsMaterial({
      color: 0xf97316,
      size: 0.04,
      transparent: true,
      opacity: 0.7,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
  }, []);

  useFrame((_, delta) => {
    timeRef.current += delta;
    const t = timeRef.current;
    const equityMult = orbData.fleetEquityChange > 0 ? 1.4 : orbData.fleetEquityChange < 0 ? 0.6 : 1.0;
    const posAttr = geometry.getAttribute("position") as THREE.BufferAttribute;
    const posArr = posAttr.array as Float32Array;

    for (let i = 0; i < COUNT; i++) {
      const ox = originalPositions[i * 3];
      const oy = originalPositions[i * 3 + 1];
      const oz = originalPositions[i * 3 + 2];
      const baseR = radii[i];
      const phase = phases[i];
      const speed = speeds[i];

      const breath = Math.sin(t * speed + phase) * 0.18 * equityMult;
      const scale = (baseR + breath) / baseR;

      posArr[i * 3] = ox * scale;
      posArr[i * 3 + 1] = oy * scale;
      posArr[i * 3 + 2] = oz * scale;
    }

    posAttr.needsUpdate = true;

    if (meshRef.current) {
      meshRef.current.rotation.y += delta * 0.05;
      meshRef.current.rotation.x += delta * 0.02;
    }

    const pulseOpacity = orbData.tradePulse?.active ? 0.95 : 0.55 + 0.2 * Math.sin(t * 0.8);
    material.opacity = Math.max(0.3, Math.min(1.0, pulseOpacity));
    material.size = 0.035 + (equityMult - 1) * 0.02;
  });

  return <points ref={meshRef} geometry={geometry} material={material} />;
}

function BotArcs({ orbData }: { orbData: OrbData }) {
  const { activeBots } = orbData;
  const groupRef = useRef<THREE.Group>(null);

  const arcs = useMemo(() => {
    return BOT_KEYS.slice(0, Math.max(1, Math.min(6, activeBots))).map((key, i) => {
      const color = BOT_COLORS_HEX[key] ?? 0xffffff;
      const inclination = (i / 6) * Math.PI;
      const ascension = (i / 6) * Math.PI * 2;
      const radius = 1.55 + i * 0.08;
      const COUNT = 60;

      const pts: THREE.Vector3[] = [];
      for (let j = 0; j < COUNT; j++) {
        const angle = (j / COUNT) * Math.PI * 2;
        const x = radius * Math.cos(angle) * Math.cos(inclination) - radius * Math.sin(angle) * Math.sin(inclination) * Math.sin(ascension);
        const y = radius * Math.cos(angle) * Math.sin(inclination) + radius * Math.sin(angle) * Math.cos(inclination) * Math.sin(ascension);
        const z = radius * Math.sin(angle) * Math.cos(ascension);
        pts.push(new THREE.Vector3(x, y, z));
      }
      pts.push(pts[0].clone());

      const curve = new THREE.CatmullRomCurve3(pts, true);
      const geo = new THREE.TubeGeometry(curve, 80, 0.008, 3, true);
      const mat = new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: 0.5 + i * 0.05,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      });

      return { geo, mat, speed: 0.15 + i * 0.07, key, color };
    });
  }, [activeBots]);

  const meshRefs = useRef<(THREE.Mesh | null)[]>([]);

  useFrame((_, delta) => {
    for (let i = 0; i < arcs.length; i++) {
      const mesh = meshRefs.current[i];
      if (mesh) {
        mesh.rotation.y += delta * arcs[i].speed;
        mesh.rotation.x += delta * arcs[i].speed * 0.4;
      }
    }
  });

  return (
    <group ref={groupRef}>
      {arcs.map((arc, i) => (
        <mesh
          key={arc.key}
          ref={el => { meshRefs.current[i] = el; }}
          geometry={arc.geo}
          material={arc.mat}
        />
      ))}
    </group>
  );
}

function GlowAtmosphere({ orbData }: { orbData: OrbData }) {
  const matRef = useRef<THREE.ShaderMaterial>(null);
  const timeRef = useRef(0);
  const pulseRef = useRef(0);

  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uPulse: { value: 0 },
    uIntensity: { value: 0.6 },
  }), []);

  useEffect(() => {
    if (orbData.tradePulse?.active) pulseRef.current = 1.0;
  }, [orbData.tradePulse]);

  useEffect(() => {
    if (orbData.aiRipple) pulseRef.current = Math.max(pulseRef.current, 0.7);
  }, [orbData.aiRipple]);

  const heatIntensity = clamp01(orbData.openPositions / 8);

  useFrame((_, delta) => {
    timeRef.current += delta;
    pulseRef.current = Math.max(0, pulseRef.current - delta * 0.8);
    if (matRef.current) {
      matRef.current.uniforms.uTime.value = timeRef.current;
      matRef.current.uniforms.uPulse.value = pulseRef.current;
      matRef.current.uniforms.uIntensity.value = 0.5 + heatIntensity * 0.5;
    }
  });

  return (
    <mesh>
      <sphereGeometry args={[1.8, 32, 32]} />
      <shaderMaterial
        ref={matRef}
        uniforms={uniforms}
        vertexShader={`
          varying vec3 vNormal;
          void main() {
            vNormal = normalize(normalMatrix * normal);
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `}
        fragmentShader={`
          varying vec3 vNormal;
          uniform float uTime;
          uniform float uPulse;
          uniform float uIntensity;

          void main() {
            float rim = 1.0 - abs(dot(vNormal, vec3(0.0, 0.0, 1.0)));
            rim = pow(rim, 2.5);
            float pulse = 1.0 + uPulse * 0.8;
            float glow = rim * uIntensity * pulse;
            float flicker = 1.0 + 0.1 * sin(uTime * 3.0);
            vec3 color = mix(
              vec3(0.8, 0.35, 0.05),
              vec3(1.0, 0.7, 0.2),
              uPulse
            );
            gl_FragColor = vec4(color * glow * flicker, glow * 0.55);
          }
        `}
        transparent
        side={THREE.BackSide}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </mesh>
  );
}

function TradePulseFlare({ orbData }: { orbData: OrbData }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const matRef = useRef<THREE.MeshBasicMaterial>(null);
  const scaleRef = useRef(0.01);
  const opacRef = useRef(0);
  const activeRef = useRef(false);

  useEffect(() => {
    if (orbData.tradePulse?.active) {
      scaleRef.current = 0.1;
      opacRef.current = 1.0;
      activeRef.current = true;
    }
  }, [orbData.tradePulse]);

  const isWin = orbData.tradePulse?.isWin ?? true;

  useFrame((_, delta) => {
    if (!activeRef.current) return;
    scaleRef.current = Math.min(scaleRef.current + delta * 3.0, 4.0);
    opacRef.current = Math.max(0, opacRef.current - delta * 1.5);

    if (meshRef.current) {
      meshRef.current.scale.setScalar(scaleRef.current);
    }
    if (matRef.current) {
      matRef.current.opacity = opacRef.current;
    }
    if (opacRef.current <= 0) {
      activeRef.current = false;
      scaleRef.current = 0.01;
    }
  });

  return (
    <mesh ref={meshRef}>
      <ringGeometry args={[0.9, 1.0, 32]} />
      <meshBasicMaterial
        ref={matRef}
        color={isWin ? 0x22c55e : 0xef4444}
        transparent
        opacity={0}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

function OrbScene({ orbData }: { orbData: OrbData }) {
  const { camera } = useThree();

  useEffect(() => {
    camera.position.set(0, 0, 5);
    camera.lookAt(0, 0, 0);
  }, [camera]);

  return (
    <>
      <ambientLight intensity={0.1} />
      <pointLight position={[3, 3, 3]} intensity={1.5} color={0xff8800} />
      <pointLight position={[-3, -2, 2]} intensity={0.8} color={0x6644ff} />

      <Stars radius={50} depth={20} count={2000} factor={3} fade speed={0.5} />

      <GlowAtmosphere orbData={orbData} />
      <MoltenCore orbData={orbData} />
      <ParticleField orbData={orbData} />
      <BotArcs orbData={orbData} />
      <TradePulseFlare orbData={orbData} />
    </>
  );
}

function CSSOrb({ orbData }: { orbData: OrbData }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const timeRef = useRef(0);
  const pulseRef = useRef(0);
  const rippleRef = useRef(0);

  useEffect(() => {
    if (orbData.tradePulse?.active) pulseRef.current = 1.0;
  }, [orbData.tradePulse]);

  useEffect(() => {
    if (orbData.aiRipple) rippleRef.current = 1.0;
  }, [orbData.aiRipple]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let lastTs = performance.now();

    const particles: { x: number; y: number; r: number; speed: number; phase: number; angle: number; dist: number }[] = [];
    for (let i = 0; i < 280; i++) {
      const angle = Math.random() * Math.PI * 2;
      const dist = 90 + Math.random() * 130;
      particles.push({
        x: 0, y: 0, r: 0.8 + Math.random() * 1.4,
        speed: 0.3 + Math.random() * 0.7,
        phase: Math.random() * Math.PI * 2,
        angle, dist,
      });
    }

    function draw(ts: number) {
      const delta = Math.min((ts - lastTs) / 1000, 0.05);
      lastTs = ts;
      timeRef.current += delta;
      const t = timeRef.current;

      pulseRef.current = Math.max(0, pulseRef.current - delta * 1.2);
      rippleRef.current = Math.max(0, rippleRef.current - delta * 0.6);

      const w = canvas!.width;
      const h = canvas!.height;
      const cx = w / 2;
      const cy = h / 2;

      ctx!.clearRect(0, 0, w, h);

      const equityMult = orbData.fleetEquityChange > 0 ? 1.35 : orbData.fleetEquityChange < 0 ? 0.7 : 1.0;
      const heatFrac = clamp01(orbData.openPositions / 10);
      const baseRadius = 70 + heatFrac * 20;
      const pulse = pulseRef.current;

      const outerGlow = ctx!.createRadialGradient(cx, cy, baseRadius * 0.5, cx, cy, baseRadius * 3.5 * equityMult);
      outerGlow.addColorStop(0, `rgba(249,115,22,${0.12 + pulse * 0.15})`);
      outerGlow.addColorStop(0.4, `rgba(234,88,12,${0.06 + pulse * 0.08})`);
      outerGlow.addColorStop(1, "rgba(0,0,0,0)");
      ctx!.fillStyle = outerGlow;
      ctx!.fillRect(0, 0, w, h);

      for (const p of particles) {
        const breath = Math.sin(t * p.speed + p.phase) * 30 * equityMult;
        const rippleJitter = rippleRef.current * Math.sin(t * 6 + p.phase * 3) * 15;
        const r = p.dist + breath + rippleJitter;
        const rotOffset = t * 0.05;
        const px = cx + r * Math.cos(p.angle + rotOffset);
        const py = cy + r * Math.sin(p.angle + rotOffset) * 0.6;
        const alpha = (0.3 + 0.4 * Math.sin(t * p.speed * 0.7 + p.phase)) * (0.6 + pulse * 0.4);
        const redness = heatFrac * 0.5;
        ctx!.beginPath();
        ctx!.arc(px, py, p.r, 0, Math.PI * 2);
        ctx!.fillStyle = `rgba(${Math.round(249 - redness * 50)},${Math.round(115 + redness * 40)},22,${alpha})`;
        ctx!.fill();
      }

      const activeBotCount = Math.max(1, Math.min(6, orbData.activeBots));
      BOT_KEYS.slice(0, activeBotCount).forEach((key, i) => {
        const color = BOT_COLORS_CSS[key];
        const arcRadius = 110 + i * 14;
        const tilt = (i / 6) * 0.7;
        const rotSpeed = (0.12 + i * 0.05) * (i % 2 === 0 ? 1 : -1);
        const startAngle = t * rotSpeed;

        ctx!.save();
        ctx!.translate(cx, cy);
        ctx!.scale(1, 0.5 + tilt * 0.3);
        ctx!.beginPath();
        ctx!.arc(0, 0, arcRadius, startAngle, startAngle + Math.PI * 1.6);
        ctx!.strokeStyle = color + "88";
        ctx!.lineWidth = 1.5;
        ctx!.stroke();
        ctx!.restore();
      });

      const coreRadius = baseRadius + pulse * 12;
      const core = ctx!.createRadialGradient(cx, cy, 0, cx, cy, coreRadius);
      const r1 = 255, g1 = Math.round(180 - heatFrac * 120), b1 = Math.round(30 - heatFrac * 30);
      const r2 = 220, g2 = Math.round(80 - heatFrac * 60), b2 = 10;
      core.addColorStop(0, `rgba(${r1},${g1},${b1},${0.95 + pulse * 0.05})`);
      core.addColorStop(0.5, `rgba(${r2},${g2},${b2},0.85)`);
      core.addColorStop(1, `rgba(180,40,10,0)`);
      ctx!.beginPath();
      ctx!.arc(cx, cy, coreRadius, 0, Math.PI * 2);
      ctx!.fillStyle = core;
      ctx!.fill();

      const pct = orbData.tradePulse?.active ? 1 - pulseRef.current : 0;
      if (pct > 0) {
        const flareR = (1 - pct) * coreRadius * 4;
        const flareOpacity = pct * 0.7;
        ctx!.beginPath();
        ctx!.arc(cx, cy, flareR, 0, Math.PI * 2);
        const flareColor = orbData.tradePulse?.isWin ? `rgba(34,197,94,${flareOpacity})` : `rgba(239,68,68,${flareOpacity})`;
        ctx!.strokeStyle = flareColor;
        ctx!.lineWidth = 2;
        ctx!.stroke();
      }

      if (rippleRef.current > 0) {
        const rs = rippleRef.current;
        for (let r = 0; r < 3; r++) {
          const rippleR = coreRadius + (1 - rs + r * 0.3) * coreRadius * 2;
          ctx!.beginPath();
          ctx!.arc(cx, cy, rippleR, 0, Math.PI * 2);
          ctx!.strokeStyle = `rgba(139,92,246,${rs * 0.3})`;
          ctx!.lineWidth = 1;
          ctx!.stroke();
        }
      }

      const scanY = ((t * 0.15) % 1) * h;
      ctx!.fillStyle = `rgba(34,211,238,0.015)`;
      ctx!.fillRect(0, scanY, w, 1.5);

      animRef.current = requestAnimationFrame(draw);
    }

    animRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animRef.current);
  }, [orbData]);

  return (
    <canvas
      ref={canvasRef}
      width={window.innerWidth}
      height={window.innerHeight}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
    />
  );
}

interface TradePulseState {
  active: boolean;
  isWin: boolean;
  botName: string;
  ts: number;
}

export function OrbVisualiser() {
  const { data: summary } = useStatusSummary();
  const { data: fleet } = useKrakenFleetSummary();
  const { data: livePos } = useLivePositions();
  const { data: journal } = useLearningJournal(undefined, undefined, 5);
  const { data: djStatus } = useKrakenStatus("davy-jones");
  const { data: bbStatus } = useKrakenStatus("blackbeard");
  const { data: caStatus } = useKrakenStatus("calypso");
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();
  const { data: curve } = useEquityCurve(300);
  const { data: auditor } = useAuditorReport();

  const [tradePulse, setTradePulse] = useState<TradePulseState | null>(null);
  const [aiRipple, setAiRipple] = useState(false);
  const [webglAvailable] = useState<boolean>(() => checkWebGL());
  const lastJournalCount = useRef<number | null>(null);
  const lastAuditorRunAt = useRef<string | null>(null);

  useEffect(() => {
    const unsub = onTradePulse((ev) => {
      setTradePulse({ active: true, isWin: ev.type === "win", botName: ev.botName, ts: Date.now() });
      setTimeout(() => setTradePulse(null), 2500);
    });
    return unsub;
  }, []);

  useEffect(() => {
    const count = journal?.count ?? null;
    if (lastJournalCount.current !== null && count !== null && count !== lastJournalCount.current) {
      setAiRipple(true);
      setTimeout(() => setAiRipple(false), 3000);
    }
    if (count !== null) lastJournalCount.current = count;
  }, [journal?.count]);

  useEffect(() => {
    const runAt = auditor?.report?.run_at ?? null;
    if (lastAuditorRunAt.current !== null && runAt !== null && runAt !== lastAuditorRunAt.current) {
      setAiRipple(true);
      setTimeout(() => setAiRipple(false), 3000);
    }
    if (runAt !== null) lastAuditorRunAt.current = runAt;
  }, [auditor?.report?.run_at]);

  const openPositions = useMemo(() => {
    let n = livePos?.count ?? 0;
    n += djStatus?.position_count ?? 0;
    n += bbStatus?.position_count ?? 0;
    n += caStatus?.position_count ?? 0;
    n += optState?.positions_count ?? 0;
    n += fxState?.position_count ?? 0;
    return n;
  }, [livePos, djStatus, bbStatus, caStatus, optState, fxState]);

  const activeBots = useMemo(() => {
    let n = 0;
    const isActive = (s: string | undefined) => s === "running" || s === "online" || s === "ok";
    if (isActive(summary?.system_health?.system_status)) n++;
    if (isActive(djStatus?.status)) n++;
    if (isActive(bbStatus?.status)) n++;
    if (isActive(caStatus?.status)) n++;
    if (isActive(optState?.status)) n++;
    if (isActive(fxState?.status)) n++;
    return n;
  }, [summary, djStatus, bbStatus, caStatus, optState, fxState]);

  const fleetEquityChange = useMemo(() => {
    const snaps = curve?.snapshots;
    if (!snaps || snaps.length < 2) return 0;
    const latest = snaps[snaps.length - 1].total_equity;
    const prev = snaps[0].total_equity;
    return prev > 0 ? (latest - prev) / prev : 0;
  }, [curve]);

  const lastAiTs = useMemo(() => {
    const journalTs = journal?.entries?.[0]?.last_seen
      ? new Date(journal.entries[0].last_seen).getTime()
      : 0;
    const auditorTs = auditor?.report?.run_at
      ? new Date(auditor.report.run_at).getTime()
      : 0;
    return Math.max(journalTs, auditorTs);
  }, [journal, auditor]);

  const combinedPnl = useMemo(() => {
    const alpacaEq = summary?.portfolio_totals?.equity ?? 0;
    const krakenEq = fleet?.total_equity_usd ?? 0;
    const optEq = optState?.paper_equity ?? 0;
    const fxEq = fxState?.paper_equity ?? 0;
    const totalEquity = alpacaEq + krakenEq + optEq + fxEq;

    const snaps = curve?.snapshots;
    if (!snaps || snaps.length < 2 || totalEquity === 0) return 0;
    const baseline = snaps[0].total_equity;
    return baseline > 0 ? totalEquity - baseline : 0;
  }, [summary, fleet, optState, fxState, curve]);

  const orbData: OrbData = {
    openPositions,
    fleetEquityChange,
    activeBots,
    lastAiTs,
    tradePulse: tradePulse ? { active: tradePulse.active, isWin: tradePulse.isWin, botName: tradePulse.botName } : null,
    aiRipple,
  };

  function fmtPnl(v: number) {
    const abs = Math.abs(v);
    const s = v >= 0 ? "+" : "-";
    if (abs >= 1000) return `${s}$${(abs / 1000).toFixed(1)}k`;
    return `${s}$${abs.toFixed(0)}`;
  }

  const lastAiLabel = useMemo(() => {
    if (!lastAiTs) return "never";
    const diff = Date.now() - lastAiTs;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    return `${Math.floor(mins / 60)}h ago`;
  }, [lastAiTs]);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative", background: "#020617", overflow: "hidden" }}>
      {webglAvailable ? (
        <Canvas
          camera={{ position: [0, 0, 5], fov: 50 }}
          dpr={Math.min(window.devicePixelRatio, 2)}
          gl={{ antialias: true, alpha: false }}
          style={{ position: "absolute", inset: 0 }}
        >
          <Suspense fallback={null}>
            <OrbScene orbData={orbData} />
          </Suspense>
        </Canvas>
      ) : (
        <CSSOrb orbData={orbData} />
      )}

      <div
        style={{
          position: "absolute",
          bottom: 24,
          right: 24,
          background: "rgba(2,6,23,0.78)",
          border: "1px solid rgba(251,146,60,0.25)",
          borderRadius: 12,
          padding: "14px 18px",
          backdropFilter: "blur(12px)",
          minWidth: 180,
        }}
      >
        <div style={{ color: "rgba(148,163,184,0.5)", fontSize: 9, fontFamily: "monospace", letterSpacing: "0.15em", textTransform: "uppercase", marginBottom: 10 }}>
          Live Orb HUD
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 16px" }}>
          <div>
            <div style={{ color: "rgba(148,163,184,0.45)", fontSize: 8, fontFamily: "monospace", letterSpacing: "0.1em", textTransform: "uppercase" }}>P&amp;L</div>
            <div style={{
              color: combinedPnl >= 0 ? "#4ade80" : "#f87171",
              fontSize: 14,
              fontFamily: "monospace",
              fontWeight: 700,
            }}>
              {fmtPnl(combinedPnl)}
            </div>
          </div>

          <div>
            <div style={{ color: "rgba(148,163,184,0.45)", fontSize: 8, fontFamily: "monospace", letterSpacing: "0.1em", textTransform: "uppercase" }}>Positions</div>
            <div style={{ color: "#fbbf24", fontSize: 14, fontFamily: "monospace", fontWeight: 700 }}>
              {openPositions}
            </div>
          </div>

          <div>
            <div style={{ color: "rgba(148,163,184,0.45)", fontSize: 8, fontFamily: "monospace", letterSpacing: "0.1em", textTransform: "uppercase" }}>Active Bots</div>
            <div style={{ color: "#22d3ee", fontSize: 14, fontFamily: "monospace", fontWeight: 700 }}>
              {activeBots} / 6
            </div>
          </div>

          <div>
            <div style={{ color: "rgba(148,163,184,0.45)", fontSize: 8, fontFamily: "monospace", letterSpacing: "0.1em", textTransform: "uppercase" }}>Last AI Event</div>
            <div style={{ color: "#a78bfa", fontSize: 12, fontFamily: "monospace", fontWeight: 700 }}>
              {lastAiLabel}
            </div>
          </div>
        </div>

        {tradePulse?.active && (
          <div
            style={{
              marginTop: 10,
              padding: "4px 8px",
              borderRadius: 6,
              background: tradePulse.isWin ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)",
              border: `1px solid ${tradePulse.isWin ? "rgba(34,197,94,0.4)" : "rgba(239,68,68,0.4)"}`,
              color: tradePulse.isWin ? "#4ade80" : "#f87171",
              fontSize: 10,
              fontFamily: "monospace",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.1em",
            }}
          >
            {tradePulse.isWin ? "✓ WIN" : "✗ LOSS"} — {tradePulse.botName}
          </div>
        )}

        {aiRipple && (
          <div
            style={{
              marginTop: 6,
              padding: "4px 8px",
              borderRadius: 6,
              background: "rgba(139,92,246,0.15)",
              border: "1px solid rgba(139,92,246,0.4)",
              color: "#a78bfa",
              fontSize: 10,
              fontFamily: "monospace",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.1em",
            }}
          >
            ◉ AI Learning Event
          </div>
        )}
      </div>

      <div
        style={{
          position: "absolute",
          top: 24,
          left: "50%",
          transform: "translateX(-50%)",
          color: "rgba(251,146,60,0.35)",
          fontSize: 10,
          fontFamily: "monospace",
          letterSpacing: "0.3em",
          textTransform: "uppercase",
          textAlign: "center",
          pointerEvents: "none",
        }}
      >
        ◈ ALGOEDGE ORB — LIVE MARKET CONSCIOUSNESS ◈
      </div>
    </div>
  );
}
