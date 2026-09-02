import { Canvas, useThree } from '@react-three/fiber'
import { Edges, Line } from '@react-three/drei'
import { Bloom, EffectComposer, GodRays, ToneMapping } from '@react-three/postprocessing'
import { Suspense, useEffect, useRef } from 'react'
import { ToneMappingMode } from 'postprocessing'
import * as THREE from 'three'

const MODULES = [
  [-3.1, -1.6, 0.1, 1.45, 0.5, 1.15], [-1.35, -1.6, 0, 1.45, 0.5, 1.15],
  [0.4, -1.6, -0.1, 1.45, 0.5, 1.15], [2.15, -1.6, -0.2, 1.45, 0.5, 1.15],
  [-2.25, -0.75, 0, 1.55, 0.58, 1.3], [-0.4, -0.75, -0.08, 1.55, 0.58, 1.3],
  [1.45, -0.75, -0.16, 1.55, 0.58, 1.3], [-1.35, 0.18, 0, 1.7, 0.64, 1.45],
  [0.65, 0.18, -0.1, 1.7, 0.64, 1.45], [-0.42, 1.18, -0.04, 1.8, 0.7, 1.55],
] as const

const CONNECTIONS = [[0, 4], [1, 4], [1, 5], [2, 5], [2, 6], [3, 6], [4, 7], [5, 7], [5, 8], [6, 8], [7, 9], [8, 9], [9, 5]] as const

function ArchitectureScene({ progress, reduced }: { progress: number; reduced: boolean }) {
  const { invalidate } = useThree()
  const beacon = useRef<THREE.Mesh>(null!)
  const stage = Math.min(5, progress * 5.55)
  const reveal = THREE.MathUtils.smoothstep(stage, 0.55, 1.75)
  const fault = THREE.MathUtils.smoothstep(stage, 2.5, 3.25)
  const boundary = THREE.MathUtils.smoothstep(stage, 3.45, 4.25)
  const certified = THREE.MathUtils.smoothstep(stage, 4.35, 5)
  const beaconStrength = 0.68 + reveal * 0.22 + fault * 0.12 + certified * 0.2

  useEffect(() => invalidate(), [progress, invalidate])
  return (
    <group position={[1.25 + progress * 0.35, 0.15 - progress * 0.1, 0]} rotation={[-0.08 + progress * 0.05, reduced ? -0.16 : -0.22 + progress * 0.34, 0]}>
      <ambientLight intensity={1.3} />
      <directionalLight position={[4, 7, 5]} intensity={2.1} color="#efe4cf" />
      <directionalLight position={[-5, -1, 2]} intensity={0.65} color="#315cff" />
      <pointLight position={[2.9, 2.2, -2.7]} intensity={beaconStrength * 9} distance={17} decay={2} color="#f2a516" />
      <mesh ref={beacon} position={[2.9, 2.2, -2.7]} scale={0.78 + certified * 0.18}>
        <circleGeometry args={[1, 64]} />
        <meshBasicMaterial color="#ffe7b0" transparent opacity={beaconStrength} depthWrite={false} toneMapped={false} />
      </mesh>
      <mesh position={[2.9, 2.2, -2.76]} scale={1.38 + reveal * 0.18}>
        <ringGeometry args={[0.98, 1, 64]} />
        <meshBasicMaterial color="#f2a516" transparent opacity={0.2 + certified * 0.18} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      <group position={[0, -2.1, 0]}>
        {[5.9, 5.35, 4.8].map((width, index) => <mesh key={width} position={[0, index * 0.18, 0]}><boxGeometry args={[width, 0.15, 2.7 - index * 0.18]} /><meshStandardMaterial color="#413b33" roughness={0.86} metalness={0.05} /><Edges color="#ada59a" opacity={0.55} transparent /></mesh>)}
      </group>
      {MODULES.map((module, index) => {
        const [x, y, z, width, height, depth] = module
        const rowOffset = reveal * ((index % 3) - 1) * 0.24
        const risky = index === 5 || index === 9
        const color = risky && fault > 0.4 ? '#f05235' : index > 6 && boundary > 0.25 ? '#315cff' : '#413b33'
        return <mesh key={index} position={[x + rowOffset, y + reveal * (index % 2) * 0.08, z + reveal * index * 0.055]}><boxGeometry args={[width, height, depth]} /><meshStandardMaterial color={color} roughness={0.78} metalness={0.05} emissive={color} emissiveIntensity={(risky ? fault : boundary) * 0.13} /><Edges color={risky && fault > 0.25 ? '#ff8a6d' : '#ada59a'} opacity={0.85} transparent /></mesh>
      })}
      <group position={[0, 2.12, -0.02]}>
        {[1.65, 1.25, 0.86, 0.48].map((width, index) => <mesh key={width} position={[0, index * 0.34, index * 0.035]}><boxGeometry args={[width, 0.28, 1.4 - index * 0.18]} /><meshStandardMaterial color={index > 1 && boundary > 0.3 ? '#29413c' : '#413b33'} roughness={0.85} /><Edges color="#ada59a" opacity={0.75} transparent /></mesh>)}
      </group>
      <group visible={reveal > 0.02}>
        {CONNECTIONS.map(([from, to], index) => {
          const a = MODULES[from]; const b = MODULES[to]; const cycle = index >= CONNECTIONS.length - 1
          const color = cycle && fault > 0.2 ? '#f05235' : index % 4 === 0 ? '#c7f43d' : '#d8d0c2'
          return <Line key={index} points={[[a[0], a[1], 0.82 + reveal], [b[0], b[1], 0.82 + reveal]]} color={color} lineWidth={cycle ? 2.3 : 1.15} transparent opacity={reveal * (cycle ? fault : 0.74)} />
        })}
        {MODULES.map((module, index) => <mesh key={`node-${index}`} position={[module[0], module[1], 0.82 + reveal]} scale={0.06 + reveal * 0.055}><sphereGeometry args={[1, 14, 14]} /><meshBasicMaterial color={index === 5 && fault > 0.3 ? '#f05235' : index % 3 === 0 ? '#c7f43d' : '#efe8dc'} /></mesh>)}
      </group>
      <group visible={boundary > 0.02}>
        {[-1.15, 0.72].map((y, index) => <mesh key={y} position={[0, y, -0.72]}><boxGeometry args={[7.4, 0.025, 3.9]} /><meshBasicMaterial color={index ? '#315cff' : '#29413c'} transparent opacity={boundary * 0.14} depthWrite={false} /></mesh>)}
      </group>
      <mesh position={[0, 0.45, 2.15]} visible={certified > 0.02} rotation={[0, 0, -0.08]} scale={0.8 + certified * 0.25}><ringGeometry args={[1.22, 1.34, 64]} /><meshBasicMaterial color="#c7f43d" transparent opacity={certified * 0.9} side={THREE.DoubleSide} /></mesh>
      {!reduced && <EffectComposer autoClear={false} multisampling={0}>
        <GodRays
          sun={beacon}
          samples={40}
          density={0.96}
          decay={0.95}
          weight={0.48 + certified * 0.08}
          exposure={0.5 + beaconStrength * 0.15}
          clampMax={1}
          blur
          resolutionScale={0.5}
        />
        <Bloom luminanceThreshold={0.62} luminanceSmoothing={0.8} intensity={0.55} mipmapBlur />
        <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      </EffectComposer>}
    </group>
  )
}

export default function LivingScene({ progress, reduced }: { progress: number; reduced: boolean }) {
  return <div className="landing-canvas" aria-hidden="true"><Canvas camera={{ position: [0.3, 0.15, 10.3], fov: 37 }} dpr={[1, 1.5]} frameloop="demand" gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }} fallback={<div className="scene-fallback" />}><Suspense fallback={null}><ArchitectureScene progress={reduced ? 0.72 : progress} reduced={reduced} /></Suspense></Canvas></div>
}
