import { CSSProperties } from "react";

import { seededRandom } from "./random";

export const WINGS = {
  classic: "M1 12 Q8 2 16 11 Q24 2 31 12",
  glide: "M1 11 Q9 1 16 9 Q23 4 31 8",
  loop: "M1 11 Q9 3 14.5 9 A2.4 2.4 0 1 0 17.5 9 Q23 3 31 11",
  dip: "M1 12 Q8 2 15 10 L16 11 L17 10 Q24 2 31 12",
} as const;

export type WingName = keyof typeof WINGS;

export const WING_NAMES: WingName[] = ["classic", "glide", "loop", "dip"];
const TINT_HUES = [245, 155, 75, 335, 25, 195];

export const YOUR_WING = WINGS.classic;

function hashHandle(handle: string): number {
  let hash = 0;
  for (let index = 0; index < handle.length; index += 1) {
    hash = (hash * 31 + handle.charCodeAt(index)) >>> 0;
  }
  return hash;
}

export function wingNameFor(handle: string): WingName {
  return WING_NAMES[hashHandle(handle) % WING_NAMES.length];
}

export function wingFor(handle: string): string {
  return WINGS[wingNameFor(handle)];
}

export function tintFor(handle: string): string {
  const hue = TINT_HUES[hashHandle(handle) % TINT_HUES.length];
  return `oklch(0.52 0.11 ${hue})`;
}

export function statusDotColor(status: string | null | undefined): string {
  if (status === "active" || status === "online") {
    return "var(--ok)";
  }
  if (status === "busy" || status === "pending") {
    return "var(--amber)";
  }
  return "var(--faint)";
}

export function Wing({
  path,
  size = 16,
  strokeWidth = 2.8,
  flip = false,
  className,
  style,
}: {
  path: string;
  size?: number;
  strokeWidth?: number;
  flip?: boolean;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      viewBox="0 0 32 14"
      fill="none"
      aria-hidden="true"
      className={className}
      style={{
        display: "block",
        overflow: "visible",
        transformOrigin: "center",
        ...(flip ? { transform: "scaleX(-1)" } : {}),
        ...style,
      }}
    >
      <path d={path} stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function GullAvatar({
  handle,
  size = 30,
  background = "var(--accent)",
  color = "#ffffff",
  animation,
}: {
  handle: string;
  size?: number;
  background?: string;
  color?: string;
  animation?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className="grid flex-none place-items-center rounded-full"
      style={{ width: size, height: size, background, color }}
    >
      <Wing
        path={wingFor(handle)}
        size={Math.round(size / 2)}
        strokeWidth={3.4}
        style={animation ? { animation } : undefined}
      />
    </span>
  );
}

export type AmbientGull = {
  x: string;
  y: string;
  size: number;
  opacity: number;
  rotation: string;
  flipX: boolean;
  duration: string;
  delay: string;
  path: string;
};

export function ambientGulls(count = 10): AmbientGull[] {
  const list: AmbientGull[] = [];
  for (let index = 0; index < count; index += 1) {
    list.push({
      x: `${(5 + seededRandom(index * 3 + 1) * 90).toFixed(1)}%`,
      y: `${(8 + seededRandom(index * 3 + 2) * 66).toFixed(1)}%`,
      size: Math.round(11 + seededRandom(index * 3 + 3) * 12),
      opacity: 0.12 + seededRandom(index * 9 + 6) * 0.18,
      rotation: (seededRandom(index * 11 + 7) * 28 - 14).toFixed(1),
      flipX: seededRandom(index * 13 + 8) < 0.4,
      duration: `${(3 + seededRandom(index * 5 + 4) * 2.6).toFixed(1)}s`,
      delay: `${(seededRandom(index * 5 + 5) * 2.4).toFixed(1)}s`,
      path: WINGS[WING_NAMES[Math.floor(seededRandom(index * 17 + 9) * WING_NAMES.length)]],
    });
  }
  return list;
}

export function AmbientFlock({ count = 10 }: { count?: number }) {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0">
      {ambientGulls(count).map((gull, index) => (
        <span
          key={index}
          className="absolute text-faint"
          style={{
            left: gull.x,
            top: gull.y,
            opacity: gull.opacity,
            transform: `rotate(${gull.rotation}deg) scaleX(${gull.flipX ? -1 : 1})`,
            animation: `gull-bob ${gull.duration} ease-in-out ${gull.delay} infinite alternate`,
          }}
        >
          <Wing path={gull.path} size={gull.size} strokeWidth={2.6} />
        </span>
      ))}
    </div>
  );
}

export function PassingFlock({ count = 10 }: { count?: number }) {
  return (
    <>
      {ambientGulls(count).map((gull, index) => {
        const duration = 16 + (index % 5) * 4 + (index % 3) * 1.7;
        return (
          <span
            key={index}
            aria-hidden="true"
            className="absolute text-faint"
            style={{
              left: "-8%",
              top: `${(4 + parseFloat(gull.y) * 0.6).toFixed(1)}%`,
              opacity: gull.opacity,
              animation: `gull-cross ${duration.toFixed(1)}s linear -${(duration * ((index + 1) / 11)).toFixed(1)}s infinite${gull.flipX ? " reverse" : ""}`,
            }}
          >
            <span
              style={{
                display: "block",
                transform: `scaleX(${gull.flipX ? -1 : 1})`,
                animation: `gull-bob ${gull.duration} ease-in-out ${gull.delay} infinite`,
              }}
            >
              <Wing path={gull.path} size={gull.size} strokeWidth={2.4} />
            </span>
          </span>
        );
      })}
    </>
  );
}
