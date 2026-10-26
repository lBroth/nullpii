<!-- SPDX-License-Identifier: Apache-2.0 -->

<!--
  A CSS-only model of the logo in the hero. The closed state is the base
  state, so SSR, browsers without CSS animations, and reduced-motion users
  all get the complete lock. JavaScript only adds pointer tilt on devices
  with a fine pointer; every other movement is a transform/opacity keyframe.
-->
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';

const COLUMN_X = [77, 92, 106, 120, 135, 150, 165] as const;
const COLUMN_WIDTH = [15, 14, 14, 15, 15, 15, 14.5] as const;
const ROW_Y = [112, 130, 148, 166, 184] as const;
const COLUMN_COLOR = [
  '#00fdfd',
  '#00d5df',
  '#00d5df',
  '#00c5d3',
  '#008ba4',
  '#008ba4',
  '#007594',
] as const;
const LAST_ROW_RIGHT_COLOR = '#006f8f';
const CUBE_FACES = ['front', 'back', 'right', 'left', 'top', 'bottom'] as const;
const SHACKLE_LAYERS = [-6, -4, -2, 0, 2, 4, 6] as const;
const PIXEL_FIRST_DELAY_MS = 90;
const PIXEL_STAGGER_MS = 45;

/* Every filled cell in the PNG, including the final cell of each row. */
const BODY_CELLS = [
  [0, 0],
  [3, 0],
  [6, 0],
  [1, 1],
  [2, 1],
  [4, 1],
  [5, 1],
  [0, 2],
  [3, 2],
  [6, 2],
  [1, 3],
  [2, 3],
  [4, 3],
  [5, 3],
  [2, 4],
  [4, 4],
] as const;

/* Deliberately varied depth and rotation make the assembly read as 3D. */
const SCATTER = [
  { x: -88, y: -48, z: -120, rx: -55, ry: -70, rz: -35 },
  { x: 18, y: -92, z: 130, rx: 70, ry: 45, rz: 18 },
  { x: 94, y: -36, z: -70, rx: -35, ry: 85, rz: 42 },
  { x: -64, y: 34, z: 150, rx: 65, ry: -50, rz: 28 },
  { x: -18, y: -72, z: -170, rx: -80, ry: 35, rz: -18 },
  { x: 46, y: 58, z: 110, rx: 45, ry: 75, rz: -32 },
  { x: 88, y: 22, z: -140, rx: -60, ry: -65, rz: 20 },
  { x: -102, y: 70, z: 60, rx: 35, ry: 90, rz: 50 },
  { x: 8, y: 96, z: -110, rx: 85, ry: 30, rz: -45 },
  { x: 102, y: 66, z: 170, rx: -45, ry: 70, rz: 35 },
  { x: -72, y: 112, z: -80, rx: -70, ry: -40, rz: 22 },
  { x: -30, y: 64, z: 180, rx: 55, ry: 65, rz: -28 },
  { x: 52, y: 116, z: -150, rx: -65, ry: 50, rz: 38 },
  { x: 96, y: 94, z: 90, rx: 75, ry: -55, rz: -20 },
  { x: -34, y: 128, z: 120, rx: 40, ry: -80, rz: 30 },
  { x: 48, y: 138, z: -60, rx: -50, ry: 60, rz: -40 },
] as const;

const pixels = BODY_CELLS.map(([column, row], index) => {
  const scatter = SCATTER[index];
  const color = row === 4 && column === 4 ? LAST_ROW_RIGHT_COLOR : COLUMN_COLOR[column];

  return {
    id: `${row}-${column}`,
    style: {
      left: `${COLUMN_X[column]}px`,
      top: `${ROW_Y[row]}px`,
      animationDelay: `${PIXEL_FIRST_DELAY_MS + index * PIXEL_STAGGER_MS}ms`,
      '--pixel-width': `${COLUMN_WIDTH[column]}px`,
      '--pixel-color': color,
      '--scatter-x': `${scatter.x}px`,
      '--scatter-y': `${scatter.y}px`,
      '--scatter-z': `${scatter.z}px`,
      '--scatter-rx': `${scatter.rx}deg`,
      '--scatter-ry': `${scatter.ry}deg`,
      '--scatter-rz': `${scatter.rz}deg`,
    },
  };
});

const root = ref<HTMLElement | null>(null);
const tilt = ref<HTMLElement | null>(null);
let observedHero: HTMLElement | null = null;
let animationFrame: number | null = null;
let pointerX = 0;
let pointerY = 0;

function setTilt(x: number, y: number): void {
  tilt.value?.style.setProperty('--tilt-x', `${x}deg`);
  tilt.value?.style.setProperty('--tilt-y', `${y}deg`);
}

function applyPointerTilt(): void {
  animationFrame = null;
  if (!observedHero) return;

  const bounds = observedHero.getBoundingClientRect();
  if (bounds.width === 0 || bounds.height === 0) return;

  const horizontal = (pointerX - bounds.left) / bounds.width - 0.5;
  const vertical = (pointerY - bounds.top) / bounds.height - 0.5;
  setTilt(-vertical * 9, horizontal * 12);
}

function handlePointerMove(event: PointerEvent): void {
  pointerX = event.clientX;
  pointerY = event.clientY;
  animationFrame ??= requestAnimationFrame(applyPointerTilt);
}

function resetPointerTilt(): void {
  if (animationFrame !== null) cancelAnimationFrame(animationFrame);
  animationFrame = null;
  setTilt(0, 0);
}

onMounted(() => {
  const finePointer = window.matchMedia('(pointer: fine)');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (!finePointer.matches || reducedMotion.matches) return;

  observedHero = root.value?.closest<HTMLElement>('.VPHero') ?? null;
  if (!observedHero) return;

  observedHero.addEventListener('pointermove', handlePointerMove, { passive: true });
  observedHero.addEventListener('pointerleave', resetPointerTilt);
});

onBeforeUnmount(() => {
  if (animationFrame !== null) cancelAnimationFrame(animationFrame);
  observedHero?.removeEventListener('pointermove', handlePointerMove);
  observedHero?.removeEventListener('pointerleave', resetPointerTilt);
});
</script>

<template>
  <div ref="root" class="np-lock-hero" aria-hidden="true">
    <div class="np-lock-aura" />
    <div class="np-lock-shadow" />

    <div class="np-lock-view">
      <div ref="tilt" class="np-lock-tilt">
        <div class="np-lock-float">
          <div class="np-lock-scale">
            <div class="np-lock-assembly">
              <div class="np-lock-shackle">
                <div
                  v-for="depth in SHACKLE_LAYERS"
                  :key="depth"
                  class="np-lock-shackle-layer"
                  :style="{ transform: `translateZ(${depth}px)` }"
                />
              </div>

              <div
                v-for="pixel in pixels"
                :key="pixel.id"
                class="np-lock-pixel"
                :style="pixel.style"
              >
                <div class="np-lock-cube">
                  <div
                    v-for="face in CUBE_FACES"
                    :key="face"
                    class="np-lock-face"
                    :class="`np-lock-face-${face}`"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.np-lock-hero {
  --lock-scale: 1.15;
  --lock-glow: rgba(13, 148, 136, 0.18);
  --lock-shadow: rgba(0, 117, 148, 0.2);
  position: relative;
  width: 100%;
  max-width: 240px;
  height: 190px;
  margin: 0 auto;
  overflow: hidden;
  overflow: clip;
  pointer-events: none;
  user-select: none;
}

:global(.dark) .np-lock-hero {
  --lock-glow: rgba(45, 212, 191, 0.2);
  --lock-shadow: rgba(0, 203, 215, 0.18);
}

.np-lock-view,
.np-lock-tilt,
.np-lock-float,
.np-lock-scale,
.np-lock-assembly {
  transform-style: preserve-3d;
}

.np-lock-view {
  position: absolute;
  inset: 0;
  perspective: 900px;
}

.np-lock-tilt {
  --tilt-x: 0deg;
  --tilt-y: 0deg;
  width: 100%;
  height: 100%;
  transform: rotateX(var(--tilt-x)) rotateY(var(--tilt-y));
  transition: transform 160ms ease-out;
}

.np-lock-float {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 256px;
  height: 256px;
  margin: -128px 0 0 -128px;
  animation: np-lock-float 7s ease-in-out 2.5s infinite;
}

.np-lock-scale,
.np-lock-assembly {
  width: 100%;
  height: 100%;
}

.np-lock-scale {
  transform: scale(var(--lock-scale));
}

.np-lock-assembly {
  position: relative;
  transform-origin: 128px 150px;
  animation: np-lock-click 2.5s ease-out both;
}

.np-lock-aura {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: radial-gradient(circle, var(--lock-glow), transparent 68%);
  opacity: 0.42;
  transform: translate(-50%, -50%);
  animation: np-lock-aura 2.5s ease-out both;
}

.np-lock-shadow {
  position: absolute;
  bottom: 10px;
  left: 50%;
  width: 112px;
  height: 18px;
  border-radius: 50%;
  background: radial-gradient(ellipse, var(--lock-shadow), transparent 70%);
  opacity: 0.6;
  transform: translateX(-50%);
  animation: np-lock-shadow 2.5s ease-out both;
}

/* The supplied row map contains sixteen filled cells; following it
 * exactly preserves the silhouette of the PNG. */
.np-lock-pixel {
  --pixel-height: 15px;
  --pixel-depth: 12px;
  --pixel-half-depth: 6px;
  position: absolute;
  width: var(--pixel-width);
  height: var(--pixel-height);
  opacity: 1;
  transform-style: preserve-3d;
  animation: np-lock-pixel-arrive 720ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
}

.np-lock-cube {
  position: relative;
  width: 100%;
  height: 100%;
  transform-style: preserve-3d;
}

.np-lock-face {
  position: absolute;
  display: block;
  backface-visibility: hidden;
}

.np-lock-face-front,
.np-lock-face-back {
  inset: 0;
}

.np-lock-face-front {
  background: var(--pixel-color);
  transform: translateZ(var(--pixel-half-depth));
}

.np-lock-face-back {
  background: color-mix(in srgb, var(--pixel-color), #00141d 38%);
  transform: rotateY(180deg) translateZ(var(--pixel-half-depth));
}

.np-lock-face-right,
.np-lock-face-left {
  top: 0;
  width: var(--pixel-depth);
  height: 100%;
}

.np-lock-face-right {
  right: calc(var(--pixel-half-depth) * -1);
  background: color-mix(in srgb, var(--pixel-color), #00141d 28%);
  transform: rotateY(90deg);
}

.np-lock-face-left {
  left: calc(var(--pixel-half-depth) * -1);
  background: color-mix(in srgb, var(--pixel-color), #00141d 14%);
  transform: rotateY(-90deg);
}

.np-lock-face-top,
.np-lock-face-bottom {
  left: 0;
  width: 100%;
  height: var(--pixel-depth);
}

.np-lock-face-top {
  top: calc(var(--pixel-half-depth) * -1);
  background: color-mix(in srgb, var(--pixel-color), white 34%);
  transform: rotateX(90deg);
}

.np-lock-face-bottom {
  bottom: calc(var(--pixel-half-depth) * -1);
  background: color-mix(in srgb, var(--pixel-color), #00141d 32%);
  transform: rotateX(-90deg);
}

/* Seven masked gradient strokes form a solid, extruded inverted U. Its
 * transform origin is the center of the left leg, so the right leg swings
 * around the left one before the whole shackle drops onto the body. */
.np-lock-shackle {
  position: absolute;
  top: 51px;
  left: 92px;
  width: 74px;
  height: 58px;
  transform: none;
  transform-origin: 7.5px 100%;
  transform-style: preserve-3d;
  animation: np-lock-shackle-close 2.5s cubic-bezier(0.4, 0, 0.2, 1) both;
}

.np-lock-shackle-layer {
  position: absolute;
  inset: 0;
  box-sizing: border-box;
  border: 15px solid transparent;
  border-bottom: 0;
  border-radius: 40px 40px 0 0;
  background: linear-gradient(105deg, #38e9ec 0%, #00cbd7 46%, #008ba4 100%) border-box;
  -webkit-mask: linear-gradient(#000 0 0) padding-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#000 0 0) padding-box, linear-gradient(#000 0 0);
  mask-composite: exclude;
}

@media (min-width: 640px) {
  .np-lock-hero {
    --lock-scale: 1.3;
    max-width: 260px;
    height: 230px;
  }

  .np-lock-shadow {
    bottom: 14px;
  }
}

@media (min-width: 960px) {
  .np-lock-hero {
    --lock-scale: 1.65;
    max-width: 300px;
    height: 300px;
  }

  .np-lock-shadow {
    bottom: 16px;
    width: 136px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .np-lock-tilt {
    transform: none;
    transition: none;
  }

  .np-lock-float,
  .np-lock-assembly,
  .np-lock-aura,
  .np-lock-shadow,
  .np-lock-pixel,
  .np-lock-shackle {
    animation: none;
  }
}

@keyframes np-lock-pixel-arrive {
  0% {
    opacity: 0;
    transform: translate3d(var(--scatter-x), var(--scatter-y), var(--scatter-z))
      rotateX(var(--scatter-rx)) rotateY(var(--scatter-ry)) rotateZ(var(--scatter-rz)) scale(0.6);
  }

  20% {
    opacity: 0.9;
  }

  82% {
    opacity: 1;
    transform: translate3d(0, 0, 5px) rotateX(0) rotateY(0) rotateZ(0) scale(1.04);
  }

  100% {
    opacity: 1;
    transform: none;
  }
}

@keyframes np-lock-shackle-close {
  0%,
  52% {
    transform: translate3d(0, -18px, 18px) rotateY(-72deg);
  }

  70% {
    transform: translate3d(0, -18px, 8px) rotateY(7deg);
  }

  76% {
    transform: translate3d(0, -18px, 3px) rotateY(0);
  }

  86% {
    transform: translate3d(0, 1.5px, 0) rotateY(0);
  }

  90%,
  100% {
    transform: none;
  }
}

@keyframes np-lock-click {
  0%,
  86% {
    transform: scale(1);
  }

  89% {
    transform: scale(1.025);
  }

  92% {
    transform: scale(0.996);
  }

  95%,
  100% {
    transform: scale(1);
  }
}

@keyframes np-lock-aura {
  0% {
    opacity: 0.08;
    transform: translate(-50%, -50%) scale(0.82);
  }

  48%,
  84% {
    opacity: 0.42;
    transform: translate(-50%, -50%) scale(1);
  }

  89% {
    opacity: 0.75;
    transform: translate(-50%, -50%) scale(1.08);
  }

  100% {
    opacity: 0.42;
    transform: translate(-50%, -50%) scale(1);
  }
}

@keyframes np-lock-shadow {
  0% {
    opacity: 0;
    transform: translateX(-50%) scale(0.7);
  }

  55%,
  84% {
    opacity: 0.6;
    transform: translateX(-50%) scale(1);
  }

  89% {
    opacity: 0.8;
    transform: translateX(-50%) scale(1.06);
  }

  100% {
    opacity: 0.6;
    transform: translateX(-50%) scale(1);
  }
}

@keyframes np-lock-float {
  0%,
  100% {
    transform: translateY(0);
  }

  50% {
    transform: translateY(-5px);
  }
}
</style>
