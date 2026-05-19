import { useRef, useMemo, useEffect, useState, Suspense } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Stars, Html } from "@react-three/drei";
import * as THREE from "three";
import { DDGBadge } from "@/components/DDGBadge";
import { useRealFeed } from "@/components/streaming/useRealFeed";
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
  useAdminLearningSnapshot,
  usePoseidonState,
  useKrakenCurrentState,
  useFleetEquity,
  useBotRegistry,
} from "@/hooks/use-trading";
import { getFleetBotCount } from "@/lib/fleet-capital";
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
  oracle:            "#8b5cf6",
  "davy-jones":      "#22d3ee",
  blackbeard:        "#f97316",
  apex:              "#f59e0b",
  navigator:         "#10b981",
  poseidon:          "#6366f1",
  "kraken-current":  "#06b6d4",
};

const BOT_COLORS_HEX: Record<string, THREE.ColorRepresentation> = {
  oracle:            0x8b5cf6,
  "davy-jones":      0x22d3ee,
  blackbeard:        0xf97316,
  apex:              0xf59e0b,
  navigator:         0x10b981,
  poseidon:          0x6366f1,
  "kraken-current":  0x06b6d4,
};

const BOT_KEYS = Object.keys(BOT_COLORS_CSS);
const BOT_COLORS_ARR = Object.values(BOT_COLORS_HEX);

const BOT_DISPLAY_NAMES: Record<string, string> = {
  oracle:            "ORACLE",
  "davy-jones":      "DAVY JONES",
  blackbeard:        "BLACKBEARD",
  apex:              "APEX",
  navigator:         "NAVIGATOR",
  poseidon:          "POSEIDON",
  "kraken-current":  "KRAKEN CURRENT",
};

function clamp01(v: number) { return Math.max(0, Math.min(1, v)); }

interface OrbData {
  openPositions: number;
  fleetEquityChange: number;
  activeBots: number;
  totalBots: number;
  lastAiTs: number;
  tradePulse: { active: boolean; isWin: boolean; botName: string } | null;
  aiRipple: boolean;
  tendrilTrigger: number;
  idleOrbPulse: number;
}

// ─── Molten Core ────────────────────────────────────────────────────────────

function MoltenCore({ orbData }: { orbData: OrbData }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const matRef = useRef<THREE.ShaderMaterial>(null);
  const timeRef = useRef(0);
  const pulseRef = useRef(0);
  const rippleRef = useRef(0);

  const uniforms = useMemo(() => ({
    uTime:      { value: 0 },
    uPulse:     { value: 0 },
    uRipple:    { value: 0 },
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

  useEffect(() => {
    if (!orbData.idleOrbPulse) return;
    pulseRef.current = Math.max(pulseRef.current, 0.6);
  }, [orbData.idleOrbPulse]);

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

// ─── Particle Field ─────────────────────────────────────────────────────────

function ParticleField({ orbData }: { orbData: OrbData }) {
  const COUNT = 600;
  const meshRef = useRef<THREE.Points>(null);
  const timeRef = useRef(0);

  const { positions, speeds, phases, radii } = useMemo(() => {
    const positions = new Float32Array(COUNT * 3);
    const speeds    = new Float32Array(COUNT);
    const phases    = new Float32Array(COUNT);
    const radii     = new Float32Array(COUNT);

    for (let i = 0; i < COUNT; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi   = Math.acos(2 * Math.random() - 1);
      const r     = 1.3 + Math.random() * 1.8;

      positions[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);

      speeds[i] = 0.3 + Math.random() * 0.7;
      phases[i] = Math.random() * Math.PI * 2;
      radii[i]  = r;
    }
    return { positions, speeds, phases, radii };
  }, []);

  const originalPositions = useMemo(() => new Float32Array(positions), [positions]);

  const geometry = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(positions), 3));
    return geo;
  }, [positions]);

  const material = useMemo(() => new THREE.PointsMaterial({
    color: 0xf97316,
    size: 0.04,
    transparent: true,
    opacity: 0.7,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  }), []);

  useFrame((_, delta) => {
    timeRef.current += delta;
    const t = timeRef.current;
    const equityMult = orbData.fleetEquityChange > 0 ? 1.4 : orbData.fleetEquityChange < 0 ? 0.6 : 1.0;
    const posAttr = geometry.getAttribute("position") as THREE.BufferAttribute;
    const posArr  = posAttr.array as Float32Array;

    for (let i = 0; i < COUNT; i++) {
      const ox = originalPositions[i * 3];
      const oy = originalPositions[i * 3 + 1];
      const oz = originalPositions[i * 3 + 2];
      const breath = Math.sin(t * speeds[i] + phases[i]) * 0.18 * equityMult;
      const scale  = (radii[i] + breath) / radii[i];
      posArr[i * 3]     = ox * scale;
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
    material.size    = 0.035 + (equityMult - 1) * 0.02;
  });

  return <points ref={meshRef} geometry={geometry} material={material} />;
}

// ─── Bot Arcs ───────────────────────────────────────────────────────────────

function BotArcs({ orbData }: { orbData: OrbData }) {
  const arcs = useMemo(() => {
    return BOT_KEYS.map((key, i) => {
      const color       = BOT_COLORS_HEX[key] ?? 0xffffff;
      const colorCss    = BOT_COLORS_CSS[key] ?? "#ffffff";
      const inclination = (i / 6) * Math.PI;
      const ascension   = (i / 6) * Math.PI * 2;
      const radius      = 1.55 + i * 0.08;
      const COUNT       = 60;

      const pts: THREE.Vector3[] = [];
      for (let j = 0; j < COUNT; j++) {
        const angle = (j / COUNT) * Math.PI * 2;
        const x = radius * Math.cos(angle) * Math.cos(inclination) - radius * Math.sin(angle) * Math.sin(inclination) * Math.sin(ascension);
        const y = radius * Math.cos(angle) * Math.sin(inclination) + radius * Math.sin(angle) * Math.cos(inclination) * Math.sin(ascension);
        const z = radius * Math.sin(angle) * Math.cos(ascension);
        pts.push(new THREE.Vector3(x, y, z));
      }
      pts.push(pts[0].clone());

      const labelPos = pts[0].clone();

      const curve = new THREE.CatmullRomCurve3(pts, true);
      const geo   = new THREE.TubeGeometry(curve, 80, 0.008, 3, true);
      const mat   = new THREE.MeshBasicMaterial({
        color, transparent: true,
        opacity: 0.5 + i * 0.05,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      });
      return { geo, mat, speed: 0.15 + i * 0.07, key, color, colorCss, labelPos, displayName: BOT_DISPLAY_NAMES[key] ?? key.toUpperCase() };
    });
  }, []);

  const groupRefs = useRef<(THREE.Group | null)[]>([]);
  const pulseRefs = useRef<number[]>(arcs.map(() => 0));
  const lastEventRef = useRef<number>(0);
  const idleTimerRef = useRef<number>(4 + Math.random() * 3);

  const badgeRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    pulseRefs.current = arcs.map(() => 0);
  }, [arcs.length]);

  useEffect(() => {
    const pulse = orbData.tradePulse;
    if (!pulse?.active) return;
    const idx = arcs.findIndex(a => a.key === pulse.botName);
    if (idx >= 0) {
      pulseRefs.current[idx] = 1.0;
      lastEventRef.current = 0;
      idleTimerRef.current = 4 + Math.random() * 3;
    }
  }, [orbData.tradePulse, arcs]);

  useFrame((_, delta) => {
    lastEventRef.current += delta;
    idleTimerRef.current -= delta;

    if (idleTimerRef.current <= 0 && arcs.length > 0 && lastEventRef.current > 5) {
      const idx = Math.floor(Math.random() * arcs.length);
      if (pulseRefs.current[idx] < 0.1) {
        pulseRefs.current[idx] = 0.6;
      }
      idleTimerRef.current = 4 + Math.random() * 3;
    }

    for (let i = 0; i < arcs.length; i++) {
      const grp = groupRefs.current[i];
      if (grp) {
        grp.rotation.y += delta * arcs[i].speed;
        grp.rotation.x += delta * arcs[i].speed * 0.4;
      }

      pulseRefs.current[i] = Math.max(0, pulseRefs.current[i] - delta * 0.7);
      const pulse = pulseRefs.current[i];

      const badge = badgeRefs.current[i];
      if (badge) {
        const scale = 1.0 + pulse * 0.35;
        const opacity = 0.75 + pulse * 0.25;
        badge.style.transform = `scale(${scale.toFixed(3)})`;
        badge.style.opacity = opacity.toFixed(3);
      }
    }
  });

  return (
    <group>
      {arcs.map((arc, i) => (
        <group
          key={arc.key}
          ref={el => { groupRefs.current[i] = el; }}
        >
          <mesh geometry={arc.geo} material={arc.mat} />
          <Html
            position={arc.labelPos}
            center
            zIndexRange={[100, 200]}
            style={{ pointerEvents: "none" }}
          >
            <div
              ref={el => { badgeRefs.current[i] = el; }}
              style={{
                padding: "2px 7px",
                border: `1px solid ${arc.colorCss}`,
                borderRadius: 3,
                color: arc.colorCss,
                fontSize: 9,
                fontFamily: "monospace",
                fontWeight: 700,
                letterSpacing: "0.12em",
                whiteSpace: "nowrap",
                background: `${arc.colorCss}22`,
                opacity: 0.75,
                textShadow: `0 0 6px ${arc.colorCss}`,
                boxShadow: `0 0 8px ${arc.colorCss}44`,
                userSelect: "none",
              }}
            >
              {arc.displayName}
            </div>
          </Html>
        </group>
      ))}
    </group>
  );
}

// ─── Glow Atmosphere ────────────────────────────────────────────────────────

function GlowAtmosphere({ orbData }: { orbData: OrbData }) {
  const matRef    = useRef<THREE.ShaderMaterial>(null);
  const timeRef   = useRef(0);
  const pulseRef  = useRef(0);

  const uniforms = useMemo(() => ({
    uTime:      { value: 0 },
    uPulse:     { value: 0 },
    uIntensity: { value: 0.6 },
  }), []);

  useEffect(() => { if (orbData.tradePulse?.active) pulseRef.current = 1.0; }, [orbData.tradePulse]);
  useEffect(() => { if (orbData.aiRipple) pulseRef.current = Math.max(pulseRef.current, 0.7); }, [orbData.aiRipple]);
  useEffect(() => { if (orbData.idleOrbPulse) pulseRef.current = Math.max(pulseRef.current, 0.6); }, [orbData.idleOrbPulse]);

  const heatIntensity = clamp01(orbData.openPositions / Math.max(1, orbData.totalBots));

  useFrame((_, delta) => {
    timeRef.current += delta;
    pulseRef.current = Math.max(0, pulseRef.current - delta * 0.8);
    if (matRef.current) {
      matRef.current.uniforms.uTime.value      = timeRef.current;
      matRef.current.uniforms.uPulse.value     = pulseRef.current;
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
            vec3 color = mix(vec3(0.8, 0.35, 0.05), vec3(1.0, 0.7, 0.2), uPulse);
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

// ─── Trade Pulse Flare ───────────────────────────────────────────────────────

function TradePulseFlare({ orbData }: { orbData: OrbData }) {
  const meshRef  = useRef<THREE.Mesh>(null);
  const matRef   = useRef<THREE.MeshBasicMaterial>(null);
  const scaleRef = useRef(0.01);
  const opacRef  = useRef(0);
  const activeRef= useRef(false);

  useEffect(() => {
    if (orbData.tradePulse?.active) {
      scaleRef.current  = 0.1;
      opacRef.current   = 1.0;
      activeRef.current = true;
    }
  }, [orbData.tradePulse]);

  const isWin = orbData.tradePulse?.isWin ?? true;

  useFrame((_, delta) => {
    if (!activeRef.current) return;
    scaleRef.current = Math.min(scaleRef.current + delta * 3.0, 4.0);
    opacRef.current  = Math.max(0, opacRef.current - delta * 1.5);
    if (meshRef.current) meshRef.current.scale.setScalar(scaleRef.current);
    if (matRef.current)  matRef.current.opacity = opacRef.current;
    if (opacRef.current <= 0) { activeRef.current = false; scaleRef.current = 0.01; }
  });

  return (
    <mesh ref={meshRef}>
      <ringGeometry args={[0.9, 1.0, 32]} />
      <meshBasicMaterial
        ref={matRef}
        color={isWin ? 0x22c55e : 0xef4444}
        transparent opacity={0}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

// ─── Tendril System (WebGL) ──────────────────────────────────────────────────

type TendrilData = {
  active:   boolean;
  startPt:  THREE.Vector3;
  dir:      THREE.Vector3;
  perpDir:  THREE.Vector3;
  maxLen:   number;
  age:      number;
  lifetime: number;
  posAttr:  THREE.BufferAttribute;
  mat:      THREE.LineBasicMaterial;
  line:     THREE.Line;
};

const TENDRIL_SEGS = 12;

function TendrilSystem({ trigger }: { trigger: number }) {
  const groupRef     = useRef<THREE.Group>(null);
  const tendrilsRef  = useRef<TendrilData[]>([]);

  useEffect(() => {
    const group = groupRef.current;
    if (!group || trigger === 0) return;

    const count = 3 + Math.floor(Math.random() * 4);
    for (let i = 0; i < count; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi   = Math.acos(2 * Math.random() - 1);
      const dir   = new THREE.Vector3(
        Math.sin(phi) * Math.cos(theta),
        Math.sin(phi) * Math.sin(theta),
        Math.cos(phi),
      ).normalize();

      const perpDir = new THREE.Vector3(dir.y, -dir.x, 0).normalize();
      if (perpDir.lengthSq() < 0.01) perpDir.set(0, dir.z, -dir.y).normalize();

      const startPt = dir.clone().multiplyScalar(1.25);
      const maxLen  = 0.9 + Math.random() * 1.4;
      const colorIdx= Math.floor(Math.random() * BOT_COLORS_ARR.length);
      const color   = BOT_COLORS_ARR[colorIdx] as number;

      const positions = new Float32Array((TENDRIL_SEGS + 1) * 3);
      for (let j = 0; j <= TENDRIL_SEGS; j++) {
        positions[j * 3]     = startPt.x;
        positions[j * 3 + 1] = startPt.y;
        positions[j * 3 + 2] = startPt.z;
      }

      const posAttr = new THREE.BufferAttribute(positions, 3);
      const geo     = new THREE.BufferGeometry();
      geo.setAttribute("position", posAttr);

      const mat = new THREE.LineBasicMaterial({
        color,
        transparent: true,
        opacity: 0.9,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        linewidth: 1,
      });

      const line = new THREE.Line(geo, mat);
      group.add(line);

      tendrilsRef.current.push({ active: true, startPt, dir, perpDir, maxLen, age: 0, lifetime: 0.9 + Math.random() * 0.6, posAttr, mat, line });
    }
  }, [trigger]);

  useFrame((_, delta) => {
    const dead: TendrilData[] = [];

    for (const t of tendrilsRef.current) {
      if (!t.active) continue;
      t.age += delta;
      const progress = t.age / t.lifetime;

      if (progress >= 1) {
        t.active = false;
        t.mat.opacity = 0;
        dead.push(t);
        continue;
      }

      const opacity = progress < 0.25 ? progress / 0.25 : 1 - (progress - 0.25) / 0.75;
      t.mat.opacity = Math.max(0, opacity * 0.95);

      const currentLen = t.maxLen * Math.min(1, progress * 3.5);
      const arr = t.posAttr.array as Float32Array;

      for (let j = 0; j <= TENDRIL_SEGS; j++) {
        const frac   = j / TENDRIL_SEGS;
        const wriggle= Math.sin(frac * Math.PI * 4 + t.age * 6) * 0.09 * frac;
        const pt = t.startPt.clone()
          .addScaledVector(t.dir, frac * currentLen)
          .addScaledVector(t.perpDir, wriggle);
        arr[j * 3]     = pt.x;
        arr[j * 3 + 1] = pt.y;
        arr[j * 3 + 2] = pt.z;
      }
      t.posAttr.needsUpdate = true;
    }

    if (dead.length > 0 && groupRef.current) {
      for (const t of dead) {
        groupRef.current.remove(t.line);
        t.line.geometry.dispose();
        t.mat.dispose();
      }
      tendrilsRef.current = tendrilsRef.current.filter(t => t.active);
    }
  });

  return <group ref={groupRef} />;
}

// ─── Orb Scene (Three.js) ────────────────────────────────────────────────────

function OrbScene({ orbData }: { orbData: OrbData }) {
  const { camera } = useThree();
  useEffect(() => { camera.position.set(0, 0, 5); camera.lookAt(0, 0, 0); }, [camera]);

  return (
    <>
      <ambientLight intensity={0.1} />
      <pointLight position={[3, 3, 3]}   intensity={1.5} color={0xff8800} />
      <pointLight position={[-3, -2, 2]} intensity={0.8} color={0x6644ff} />
      <Stars radius={50} depth={20} count={2000} factor={3} fade speed={0.5} />
      <group scale={0.85}>
        <GlowAtmosphere orbData={orbData} />
        <MoltenCore     orbData={orbData} />
        <ParticleField  orbData={orbData} />
        <BotArcs        orbData={orbData} />
        <TradePulseFlare orbData={orbData} />
        <TendrilSystem  trigger={orbData.tendrilTrigger} />
      </group>
    </>
  );
}

// ─── CSS Canvas Orb (WebGL fallback) ─────────────────────────────────────────

type CssTendril = {
  angle:    number;
  color:    string;
  age:      number;
  lifetime: number;
  maxLen:   number;
  perpOff:  number;
};

function CSSOrb({ orbData }: { orbData: OrbData }) {
  const canvasRef   = useRef<HTMLCanvasElement>(null);
  const animRef     = useRef<number>(0);
  const timeRef     = useRef(0);
  const pulseRef    = useRef(0);
  const rippleRef   = useRef(0);
  const tendrilsRef = useRef<CssTendril[]>([]);

  useEffect(() => { if (orbData.tradePulse?.active) pulseRef.current = 1.0; }, [orbData.tradePulse]);
  useEffect(() => { if (orbData.aiRipple) rippleRef.current = 1.0; },         [orbData.aiRipple]);
  useEffect(() => { if (orbData.idleOrbPulse) pulseRef.current = Math.max(pulseRef.current, 0.6); }, [orbData.idleOrbPulse]);

  useEffect(() => {
    if (!orbData.tendrilTrigger) return;
    const count  = 3 + Math.floor(Math.random() * 4);
    const colors = Object.values(BOT_COLORS_CSS);
    for (let i = 0; i < count; i++) {
      tendrilsRef.current.push({
        angle:    Math.random() * Math.PI * 2,
        color:    colors[Math.floor(Math.random() * colors.length)],
        age:      0,
        lifetime: 0.8 + Math.random() * 0.7,
        maxLen:   55 + Math.random() * 90,
        perpOff:  (Math.random() - 0.5) * 40,
      });
    }
  }, [orbData.tendrilTrigger]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let lastTs = performance.now();

    const particles: { x: number; y: number; r: number; speed: number; phase: number; angle: number; dist: number }[] = [];
    for (let i = 0; i < 280; i++) {
      const angle = Math.random() * Math.PI * 2;
      const dist  = (90 + Math.random() * 130) * 0.85;
      particles.push({ x: 0, y: 0, r: 0.8 + Math.random() * 1.4, speed: 0.3 + Math.random() * 0.7, phase: Math.random() * Math.PI * 2, angle, dist });
    }

    function draw(ts: number) {
      const delta = Math.min((ts - lastTs) / 1000, 0.05);
      lastTs = ts;
      timeRef.current += delta;
      const t = timeRef.current;

      pulseRef.current  = Math.max(0, pulseRef.current  - delta * 1.2);
      rippleRef.current = Math.max(0, rippleRef.current - delta * 0.6);

      const w  = canvas!.width;
      const h  = canvas!.height;
      const cx = w / 2;
      const cy = h / 2;

      ctx!.clearRect(0, 0, w, h);

      const equityMult = orbData.fleetEquityChange > 0 ? 1.35 : orbData.fleetEquityChange < 0 ? 0.7 : 1.0;
      const heatFrac   = clamp01(orbData.openPositions / 10);
      const baseRadius = (70 + heatFrac * 20) * 0.85;
      const pulse      = pulseRef.current;

      const outerGlow = ctx!.createRadialGradient(cx, cy, baseRadius * 0.5, cx, cy, baseRadius * 3.5 * equityMult);
      outerGlow.addColorStop(0, `rgba(249,115,22,${0.12 + pulse * 0.15})`);
      outerGlow.addColorStop(0.4, `rgba(234,88,12,${0.06 + pulse * 0.08})`);
      outerGlow.addColorStop(1, "rgba(0,0,0,0)");
      ctx!.fillStyle = outerGlow;
      ctx!.fillRect(0, 0, w, h);

      for (const p of particles) {
        const breath      = Math.sin(t * p.speed + p.phase) * 30 * equityMult;
        const rippleJitter= rippleRef.current * Math.sin(t * 6 + p.phase * 3) * 15;
        const r           = p.dist + breath + rippleJitter;
        const rotOffset   = t * 0.05;
        const px   = cx + r * Math.cos(p.angle + rotOffset);
        const py   = cy + r * Math.sin(p.angle + rotOffset) * 0.6;
        const alpha= (0.3 + 0.4 * Math.sin(t * p.speed * 0.7 + p.phase)) * (0.6 + pulse * 0.4);
        const redness = heatFrac * 0.5;
        ctx!.beginPath();
        ctx!.arc(px, py, p.r, 0, Math.PI * 2);
        ctx!.fillStyle = `rgba(${Math.round(249 - redness * 50)},${Math.round(115 + redness * 40)},22,${alpha})`;
        ctx!.fill();
      }

      const activeBotCount = Math.max(1, Math.min(orbData.totalBots, orbData.activeBots));
      BOT_KEYS.slice(0, activeBotCount).forEach((key, i) => {
        const color    = BOT_COLORS_CSS[key];
        const arcRadius= (110 + i * 11) * 0.85;
        const tilt     = (i / Math.max(1, orbData.totalBots)) * 0.7;
        const rotSpeed = (0.12 + i * 0.05) * (i % 2 === 0 ? 1 : -1);
        const startAngle = t * rotSpeed;
        ctx!.save();
        ctx!.translate(cx, cy);
        ctx!.scale(1, 0.5 + tilt * 0.3);
        ctx!.beginPath();
        ctx!.arc(0, 0, arcRadius, startAngle, startAngle + Math.PI * 1.6);
        ctx!.strokeStyle = color + "88";
        ctx!.lineWidth   = 1.5;
        ctx!.stroke();
        ctx!.restore();
      });

      // ── Tendrils ──────────────────────────────────────────────────────
      const liveTendrils: CssTendril[] = [];
      for (const tendril of tendrilsRef.current) {
        tendril.age += delta;
        const progress = tendril.age / tendril.lifetime;
        if (progress >= 1) continue;

        const opacity    = progress < 0.25 ? progress / 0.25 : 1 - (progress - 0.25) / 0.75;
        const currentLen = tendril.maxLen * Math.min(1, progress * 3.5);
        const wriggle    = Math.sin(tendril.age * 7 + tendril.perpOff) * tendril.perpOff * progress;

        const startX  = cx + baseRadius * Math.cos(tendril.angle);
        const startY  = cy + baseRadius * Math.sin(tendril.angle);
        const endX    = cx + (baseRadius + currentLen) * Math.cos(tendril.angle);
        const endY    = cy + (baseRadius + currentLen) * Math.sin(tendril.angle);
        const perpAngle = tendril.angle + Math.PI / 2;
        const cpX     = (startX + endX) / 2 + Math.cos(perpAngle) * wriggle;
        const cpY     = (startY + endY) / 2 + Math.sin(perpAngle) * wriggle;

        const hexAlpha = Math.round(opacity * 220).toString(16).padStart(2, "0");
        ctx!.beginPath();
        ctx!.moveTo(startX, startY);
        ctx!.quadraticCurveTo(cpX, cpY, endX, endY);
        ctx!.strokeStyle = tendril.color + hexAlpha;
        ctx!.lineWidth   = Math.max(0.5, 2.0 * (1 - progress * 0.8));
        ctx!.shadowColor = tendril.color;
        ctx!.shadowBlur  = 6;
        ctx!.stroke();
        ctx!.shadowBlur  = 0;

        liveTendrils.push(tendril);
      }
      tendrilsRef.current = liveTendrils;

      const coreRadius = baseRadius + pulse * 12;
      const core = ctx!.createRadialGradient(cx, cy, 0, cx, cy, coreRadius);
      const r1 = 255, g1 = Math.round(180 - heatFrac * 120), b1 = Math.round(30 - heatFrac * 30);
      const r2 = 220, g2 = Math.round(80 - heatFrac * 60);
      core.addColorStop(0, `rgba(${r1},${g1},${b1},${0.95 + pulse * 0.05})`);
      core.addColorStop(0.5, `rgba(${r2},${g2},10,0.85)`);
      core.addColorStop(1, "rgba(180,40,10,0)");
      ctx!.beginPath();
      ctx!.arc(cx, cy, coreRadius, 0, Math.PI * 2);
      ctx!.fillStyle = core;
      ctx!.fill();

      const pct = orbData.tradePulse?.active ? 1 - pulseRef.current : 0;
      if (pct > 0) {
        const flareR = (1 - pct) * coreRadius * 4;
        ctx!.beginPath();
        ctx!.arc(cx, cy, flareR, 0, Math.PI * 2);
        ctx!.strokeStyle = orbData.tradePulse?.isWin ? `rgba(34,197,94,${pct * 0.7})` : `rgba(239,68,68,${pct * 0.7})`;
        ctx!.lineWidth   = 2;
        ctx!.stroke();
      }

      if (rippleRef.current > 0) {
        const rs = rippleRef.current;
        for (let r = 0; r < 3; r++) {
          const rippleR = coreRadius + (1 - rs + r * 0.3) * coreRadius * 2;
          ctx!.beginPath();
          ctx!.arc(cx, cy, rippleR, 0, Math.PI * 2);
          ctx!.strokeStyle = `rgba(139,92,246,${rs * 0.3})`;
          ctx!.lineWidth   = 1;
          ctx!.stroke();
        }
      }

      const scanY = ((t * 0.15) % 1) * h;
      ctx!.fillStyle = "rgba(34,211,238,0.015)";
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

// ─── Algorithmic Thought Bubbles ─────────────────────────────────────────────

const ALGO_THOUGHTS = [
  "MACD: signal > baseline → BUY",
  "RSI(14) = 68.4 → overbought",
  "Kelly f* = 0.23",
  "Sharpe = 1.87",
  "EMA(9) > EMA(21) ✓",
  "σ(vol) = 0.024",
  "regime: BULL ↑",
  "BTC/USD: 4h engulfing",
  "vol crush → IV = 22%",
  "momentum: +2.4σ",
  "max drawdown: 4.2%",
  "win_rate = 54.3%",
  "profit_factor = 1.87",
  "Δ = 0.67, Γ = 0.12",
  "ADX = 28.3 → trending",
  "Bollinger squeeze → breakout",
  "θ = -0.043 / day",
  "liquidity = OK",
  "regime: Crypto-Risk-Off × 0.5",
  "pair corr(BTC,ETH) = 0.91",
  "news sentiment: neutral",
  "stoch K < 20 → oversold",
  "ATR(14) = 142.6",
  "VWAP deviation: +0.8%",
  "WFO optimised ✓",
  "position sizing: 2.0%",
  "signal confidence: 74%",
];

type AlgoThought = {
  id: number;
  text: string;
  x: number;
  y: number;
  opacity: number;
  fadeIn: boolean;
  color: string;
};

function AlgoThoughts() {
  const [thoughts, setThoughts] = useState<AlgoThought[]>([]);
  const nextId = useRef(0);
  const colors = ["#22d3ee", "#a78bfa", "#4ade80", "#fb923c", "#f472b6", "#facc15", "#6366f1", "#06b6d4"];

  useEffect(() => {
    const spawn = () => {
      const id = nextId.current++;
      const text = ALGO_THOUGHTS[Math.floor(Math.random() * ALGO_THOUGHTS.length)];
      const side  = Math.random();
      let x: number, y: number;
      if (side < 0.25)       { x = 4 + Math.random() * 18; y = 8 + Math.random() * 80; }
      else if (side < 0.5)   { x = 78 + Math.random() * 18; y = 8 + Math.random() * 80; }
      else if (side < 0.75)  { x = 20 + Math.random() * 60; y = 4 + Math.random() * 12; }
      else                   { x = 20 + Math.random() * 60; y = 82 + Math.random() * 12; }

      const color = colors[Math.floor(Math.random() * colors.length)];
      const thought: AlgoThought = { id, text, x, y, opacity: 0, fadeIn: true, color };
      setThoughts(prev => [...prev.slice(-8), thought]);

      setTimeout(() => setThoughts(prev => prev.map(t => t.id === id ? { ...t, opacity: 1, fadeIn: false } : t)), 50);
      setTimeout(() => setThoughts(prev => prev.map(t => t.id === id ? { ...t, opacity: 0 } : t)), 3200);
      setTimeout(() => setThoughts(prev => prev.filter(t => t.id !== id)), 4000);

      const delay = 3500 + Math.random() * 3000;
      setTimeout(spawn, delay);
    };

    const initial = setTimeout(spawn, 1200 + Math.random() * 1000);
    return () => clearTimeout(initial);
  }, []);

  return (
    <>
      {thoughts.map(t => (
        <div
          key={t.id}
          style={{
            position: "absolute",
            left: `${t.x}%`,
            top:  `${t.y}%`,
            transform: "translate(-50%, -50%)",
            opacity: t.opacity,
            transition: "opacity 0.7s ease",
            pointerEvents: "none",
            userSelect: "none",
            fontFamily: "monospace",
            fontSize: 11,
            fontWeight: 700,
            color: t.color,
            textShadow: `0 0 10px ${t.color}88, 0 0 20px ${t.color}44`,
            background: "rgba(2,6,23,0.7)",
            border: `1px solid ${t.color}44`,
            borderRadius: 6,
            padding: "3px 8px",
            letterSpacing: "0.05em",
            whiteSpace: "nowrap",
          }}
        >
          {t.text}
        </div>
      ))}
    </>
  );
}

// ─── Main OrbVisualiser ───────────────────────────────────────────────────────

interface TradePulseState {
  active:  boolean;
  isWin:   boolean;
  botName: string;
  ts:      number;
}

export function OrbVisualiser() {
  const { data: summary       } = useStatusSummary();
  const { data: fleet         } = useKrakenFleetSummary();
  const { data: livePos       } = useLivePositions();
  const { data: journal       } = useLearningJournal(undefined, undefined, 5);
  const { data: djStatus      } = useKrakenStatus("davy-jones");
  const { data: bbStatus      } = useKrakenStatus("blackbeard");
  const { data: optState      } = useOptionsState();
  const { data: fxState       } = useForexState();
  const { data: poseidonState } = usePoseidonState();
  const { data: kcState       } = useKrakenCurrentState();
  const { data: curve         } = useEquityCurve(300);
  const { data: auditor       } = useAuditorReport();
  const { data: snapshot      } = useAdminLearningSnapshot();
  const { data: fleetEqOrb    } = useFleetEquity();
  const { data: registry          } = useBotRegistry();
  const { trades: closedTradesFeed, openPositions: openTradesFeed } = useRealFeed(12);

  const [tradePulse,     setTradePulse    ] = useState<TradePulseState | null>(null);
  const [aiRipple,       setAiRipple      ] = useState(false);
  const [tendrilTrigger, setTendrilTrigger] = useState(0);
  const [idleOrbPulse,   setIdleOrbPulse  ] = useState(0);
  const [webglAvailable                  ] = useState<boolean>(() => checkWebGL());
  const lastJournalCount  = useRef<number | null>(null);
  const lastAuditorRunAt  = useRef<string | null>(null);

  // Trade pulse events
  useEffect(() => {
    const unsub = onTradePulse((ev) => {
      setTradePulse({ active: true, isWin: ev.type === "win", botName: ev.botName, ts: Date.now() });
      setTimeout(() => setTradePulse(null), 2500);
    });
    return unsub;
  }, []);

  // AI ripple on learning-journal count change
  useEffect(() => {
    const count = journal?.count ?? null;
    if (lastJournalCount.current !== null && count !== null && count !== lastJournalCount.current) {
      setAiRipple(true); setTimeout(() => setAiRipple(false), 3000);
    }
    if (count !== null) lastJournalCount.current = count;
  }, [journal?.count]);

  // AI ripple on auditor run
  useEffect(() => {
    const runAt = auditor?.report?.run_at ?? null;
    if (lastAuditorRunAt.current !== null && runAt !== null && runAt !== lastAuditorRunAt.current) {
      setAiRipple(true); setTimeout(() => setAiRipple(false), 3000);
    }
    if (runAt !== null) lastAuditorRunAt.current = runAt;
  }, [auditor?.report?.run_at]);

  // Random tendril timer — fires every 2–5 seconds regardless of trade events
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(() => {
        setTendrilTrigger(n => n + 1);
        schedule();
      }, 2000 + Math.random() * 3000);
    };
    schedule();
    return () => clearTimeout(timer);
  }, []);

  // Idle orb pulse — fires every 2–5 seconds to keep the orb feeling alive
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(() => {
        setIdleOrbPulse(n => n + 1);
        schedule();
      }, 2000 + Math.random() * 3000);
    };
    schedule();
    return () => clearTimeout(timer);
  }, []);

  // ── Derived data ─────────────────────────────────────────────────────────

  const openPositions = useMemo(() => {
    let n = livePos?.count ?? 0;
    n += djStatus?.position_count ?? 0;
    n += bbStatus?.position_count ?? 0;
    n += optState?.positions_count ?? 0;
    n += fxState?.position_count ?? 0;
    n += poseidonState?.open_positions ?? 0;
    n += kcState?.open_positions ?? 0;
    return n;
  }, [livePos, djStatus, bbStatus, fleetEqOrb, optState, fxState, poseidonState, kcState]);

  const activeBots = useMemo(() => {
    const ACTIVE_STATUSES = new Set(["active", "running", "idle"]);
    return (registry?.bots ?? []).filter(b => ACTIVE_STATUSES.has((b.status ?? "").toLowerCase())).length;
  }, [registry]);

  const fleetEquityChange = useMemo(() => {
    const snaps = curve?.snapshots;
    if (!snaps || snaps.length < 2) return 0;
    const latest = snaps[snaps.length - 1].total_equity;
    const prev   = snaps[0].total_equity;
    return prev > 0 ? (latest - prev) / prev : 0;
  }, [curve]);

  const lastAiTs = useMemo(() => {
    const journalTs  = journal?.entries?.[0]?.last_seen ? new Date(journal.entries[0].last_seen).getTime() : 0;
    const auditorTs  = auditor?.report?.run_at          ? new Date(auditor.report.run_at).getTime()        : 0;
    const snapshotTs = snapshot?.exported_at            ? new Date(snapshot.exported_at).getTime()         : 0;
    return Math.max(journalTs, auditorTs, snapshotTs);
  }, [journal, auditor, snapshot]);

  // P&L = total current equity minus starting capital — single source of truth.
  const combinedPnl = fleetEqOrb?.fleet_total?.pnl ?? 0;

  const orbData: OrbData = {
    openPositions,
    fleetEquityChange,
    activeBots,
    totalBots: getFleetBotCount(registry, fleetEqOrb),
    lastAiTs,
    tradePulse: tradePulse ? { active: tradePulse.active, isWin: tradePulse.isWin, botName: tradePulse.botName } : null,
    aiRipple,
    tendrilTrigger,
    idleOrbPulse,
  };

  function fmtPnl(v: number) {
    const abs = Math.abs(v);
    const s   = v >= 0 ? "+" : "-";
    if (abs >= 1_000_000) return `${s}$${(abs / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000)     return `${s}$${(abs / 1_000).toFixed(1)}k`;
    return `${s}$${abs.toFixed(0)}`;
  }

  const lastAiLabel = useMemo(() => {
    if (!lastAiTs) return "never";
    const diff = Date.now() - lastAiTs;
    const mins = Math.floor(diff / 60_000);
    if (mins < 1)  return "just now";
    if (mins < 60) return `${mins}m ago`;
    return `${Math.floor(mins / 60)}h ago`;
  }, [lastAiTs]);

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div style={{ width: "100%", height: "100%", position: "relative", background: "#020617", overflow: "hidden" }}>
      {webglAvailable ? (
        <Canvas
          camera={{ position: [0, 0, 5.88], fov: 50 }}
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

      {/* ── LIVE ORB HUD — 30% larger ── */}
      <div
        style={{
          position: "absolute",
          bottom: 24,
          right: 24,
          background: "rgba(2,6,23,0.82)",
          border: "1px solid rgba(251,146,60,0.3)",
          borderRadius: 14,
          padding: "18px 24px",
          backdropFilter: "blur(14px)",
          minWidth: 234,
        }}
      >
        <div style={{ color: "rgba(148,163,184,0.55)", fontSize: 11, fontFamily: "monospace", letterSpacing: "0.15em", textTransform: "uppercase", marginBottom: 12 }}>
          Live Orb HUD
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 20px" }}>
          <div>
            <div style={{ color: "rgba(148,163,184,0.5)", fontSize: 10, fontFamily: "monospace", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 2 }}>P&amp;L</div>
            <div style={{ color: combinedPnl >= 0 ? "#4ade80" : "#f87171", fontSize: 18, fontFamily: "monospace", fontWeight: 700 }}>
              {fmtPnl(combinedPnl)}
            </div>
          </div>

          <div>
            <div style={{ color: "rgba(148,163,184,0.5)", fontSize: 10, fontFamily: "monospace", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 2 }}>Positions</div>
            <div style={{ color: "#fbbf24", fontSize: 18, fontFamily: "monospace", fontWeight: 700 }}>
              {openPositions}
            </div>
          </div>

          <div>
            <div style={{ color: "rgba(148,163,184,0.5)", fontSize: 10, fontFamily: "monospace", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 2 }}>Active Bots</div>
            <div style={{ color: "#22d3ee", fontSize: 18, fontFamily: "monospace", fontWeight: 700 }}>
              {activeBots} / {getFleetBotCount(registry, fleetEqOrb)}
            </div>
          </div>

          <div>
            <div style={{ color: "rgba(148,163,184,0.5)", fontSize: 10, fontFamily: "monospace", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 2 }}>Last AI Event</div>
            <div style={{ color: "#a78bfa", fontSize: 15, fontFamily: "monospace", fontWeight: 700 }}>
              {lastAiLabel}
            </div>
          </div>
        </div>

        {tradePulse?.active && (
          <div style={{
            marginTop: 12,
            padding: "5px 10px",
            borderRadius: 7,
            background: tradePulse.isWin ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)",
            border: `1px solid ${tradePulse.isWin ? "rgba(34,197,94,0.4)" : "rgba(239,68,68,0.4)"}`,
            color: tradePulse.isWin ? "#4ade80" : "#f87171",
            fontSize: 11, fontFamily: "monospace", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em",
          }}>
            {tradePulse.isWin ? "✓ WIN" : "✗ LOSS"} — {tradePulse.botName}
          </div>
        )}

        {aiRipple && (
          <div style={{
            marginTop: 8,
            padding: "5px 10px",
            borderRadius: 7,
            background: "rgba(139,92,246,0.15)",
            border: "1px solid rgba(139,92,246,0.4)",
            color: "#a78bfa",
            fontSize: 11, fontFamily: "monospace", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em",
          }}>
            ◉ AI Learning Event
          </div>
        )}
      </div>

      {/* ── ALGO THOUGHT BUBBLES ── */}
      <AlgoThoughts />

      {/* ── PROMINENT TITLE ── */}
      <div
        style={{
          position: "absolute",
          top: 20,
          left: "50%",
          transform: "translateX(-50%)",
          textAlign: "center",
          pointerEvents: "none",
          userSelect: "none",
        }}
      >
        <div style={{
          color: "rgba(251,146,60,0.95)",
          fontSize: 18,
          fontFamily: "monospace",
          fontWeight: 700,
          letterSpacing: "0.35em",
          textTransform: "uppercase",
          textShadow: "0 0 20px rgba(251,146,60,0.8), 0 0 40px rgba(251,146,60,0.4), 0 0 60px rgba(234,88,12,0.3)",
        }}>
          ◈ TRADING ENGINE ORB ◈
        </div>
        <div style={{
          color: "rgba(251,146,60,0.5)",
          fontSize: 10,
          fontFamily: "monospace",
          letterSpacing: "0.25em",
          textTransform: "uppercase",
          marginTop: 4,
          textShadow: "0 0 12px rgba(251,146,60,0.4)",
        }}>
          LIVE MARKET CONSCIOUSNESS
        </div>
      </div>

      {/* ── LEFT PANEL: RECENTLY CLOSED TRADES ── */}
      {closedTradesFeed.length > 0 && (
        <div
          style={{
            position: "absolute",
            left: 16,
            top: 80,
            bottom: 52,
            width: 216,
            display: "flex",
            flexDirection: "column",
            overflowY: "auto",
            zIndex: 20,
          }}
        >
          <div style={{ color: "rgba(148,163,184,0.4)", fontSize: 9, fontFamily: "monospace", letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 6, paddingLeft: 2 }}>
            ◂ Closed Trades
          </div>
          {closedTradesFeed.slice(0, 10).map((t, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "5px 8px",
                marginBottom: 3,
                borderRadius: 7,
                background: t.isWin ? "rgba(34,197,94,0.07)" : "rgba(239,68,68,0.07)",
                border: `1px solid ${t.isWin ? "rgba(34,197,94,0.18)" : "rgba(239,68,68,0.18)"}`,
                backdropFilter: "blur(10px)",
              }}
            >
              <span style={{ fontSize: 10, color: t.isWin ? "#4ade80" : "#f87171", flexShrink: 0, fontFamily: "monospace" }}>
                {t.isWin ? "✓" : "✗"}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontFamily: "monospace", fontSize: 10, color: "rgba(241,245,249,0.85)", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {t.symbol}
                </div>
                <div style={{ fontFamily: "monospace", fontSize: 8, color: "rgba(148,163,184,0.5)", letterSpacing: "0.05em" }}>
                  {t.bot}
                </div>
              </div>
              <span style={{ fontFamily: "monospace", fontSize: 10, fontWeight: 700, color: t.isWin ? "#4ade80" : "#f87171", flexShrink: 0 }}>
                {t.pnlUsd >= 0 ? "+" : ""}${Math.abs(t.pnlUsd) >= 1000 ? `${(Math.abs(t.pnlUsd) / 1000).toFixed(1)}k` : Math.abs(t.pnlUsd).toFixed(0)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* ── RIGHT PANEL: OPEN POSITIONS ── */}
      {openTradesFeed.length > 0 && (
        <div
          style={{
            position: "absolute",
            right: 16,
            top: 80,
            bottom: 240,
            width: 216,
            display: "flex",
            flexDirection: "column",
            overflowY: "auto",
            zIndex: 20,
          }}
        >
          <div style={{ color: "rgba(148,163,184,0.4)", fontSize: 9, fontFamily: "monospace", letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 6, textAlign: "right", paddingRight: 2 }}>
            Open Positions ▸
          </div>
          {openTradesFeed.slice(0, 10).map((p, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "5px 8px",
                marginBottom: 3,
                borderRadius: 7,
                background: (p.pnlUsd ?? 0) >= 0 ? "rgba(52,211,153,0.07)" : "rgba(239,68,68,0.07)",
                border: `1px solid ${(p.pnlUsd ?? 0) >= 0 ? "rgba(52,211,153,0.18)" : "rgba(239,68,68,0.18)"}`,
                backdropFilter: "blur(10px)",
              }}
            >
              <span style={{ fontSize: 8, color: (p.pnlUsd ?? 0) >= 0 ? "#34d399" : "#f87171", flexShrink: 0 }}>⬤</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontFamily: "monospace", fontSize: 10, color: "rgba(241,245,249,0.85)", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {p.symbol}
                </div>
                <div style={{ fontFamily: "monospace", fontSize: 8, color: "rgba(148,163,184,0.5)", letterSpacing: "0.05em" }}>
                  {p.bot}
                </div>
              </div>
              <span style={{ fontFamily: "monospace", fontSize: 10, fontWeight: 700, color: (p.pnlUsd ?? 0) >= 0 ? "#34d399" : "#f87171", flexShrink: 0 }}>
                {(p.pnlUsd ?? 0) >= 0 ? "+" : ""}${Math.abs(p.pnlUsd ?? 0) >= 1000 ? `${(Math.abs(p.pnlUsd ?? 0) / 1000).toFixed(1)}k` : Math.abs(p.pnlUsd ?? 0).toFixed(0)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* ── DDG BADGE ── */}
      <DDGBadge style={{ position: "absolute", bottom: 16, left: 16, zIndex: 30 }} />
    </div>
  );
}
