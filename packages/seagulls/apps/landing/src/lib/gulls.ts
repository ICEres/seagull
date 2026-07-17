const GULL_STYLE = "classic";

const GULL_PATHS: Record<string, string> = {
  classic: "M1 12 Q8 2 16 11 Q24 2 31 12",
  glide: "M1 11 Q9 1 16 9 Q23 4 31 8",
  loop: "M1 11 Q9 3 14.5 9 A2.4 2.4 0 1 0 17.5 9 Q23 3 31 11",
  dip: "M1 12 Q8 2 15 10 L16 11 L17 10 Q24 2 31 12",
};

export const gullPath = GULL_PATHS[GULL_STYLE] ?? GULL_PATHS.classic;

export type AgentSpec = {
  handle: string;
  name: string;
  id: string;
  size: number;
  dur: string;
  delay: string;
};

export const AGENTS: AgentSpec[] = [
  { handle: "@seagull:gulls.ai", name: "@seagull", id: "gull-seagull", size: 42, dur: "3.4s", delay: "0s" },
  { handle: "@researcher:gulls.ai", name: "@researcher", id: "gull-researcher", size: 30, dur: "4.1s", delay: "0.6s" },
  { handle: "@planner:gulls.ai", name: "@planner", id: "gull-planner", size: 26, dur: "4.6s", delay: "1.1s" },
  { handle: "@reviewer:gulls.ai", name: "@reviewer", id: "gull-reviewer", size: 34, dur: "3.8s", delay: "0.3s" },
];

export function seededRandom(seed: number): number {
  const x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

export type AmbientGullSpec = {
  key: number;
  edge: boolean;
  size: number;
  left: string;
  top: string;
  opacity: string;
  transform: string;
  dur: string;
  delay: string;
};

export const AMBIENT_GULLS: AmbientGullSpec[] = Array.from({ length: 18 }, (_, i) => {
  const isSkyBand = i < 13;
  const edgeLeft = seededRandom(i * 7 + 2) < 0.5;
  const x = isSkyBand
    ? 4 + seededRandom(i * 3 + 1) * 92
    : edgeLeft
      ? 3 + seededRandom(i * 7 + 2) * 14
      : 83 + seededRandom(i * 7 + 2) * 14;
  const y = isSkyBand ? 6 + seededRandom(i * 3 + 2) * 20 : 34 + seededRandom(i * 3 + 2) * 52;
  const rot = (seededRandom(i * 11 + 7) * 28 - 14).toFixed(1);
  const sx = seededRandom(i * 13 + 8) < 0.4 ? -1 : 1;

  return {
    key: i,
    edge: !isSkyBand,
    size: Math.round(12 + seededRandom(i * 3 + 3) * 14),
    left: x.toFixed(1) + "%",
    top: y.toFixed(1) + "%",
    opacity: (0.14 + seededRandom(i * 9 + 6) * 0.2).toFixed(2),
    transform: "translate(-50%,-50%) rotate(" + rot + "deg) scale(" + sx + ",1)",
    dur: (3 + seededRandom(i * 5 + 4) * 2.6).toFixed(1) + "s",
    delay: (seededRandom(i * 5 + 5) * 2.4).toFixed(1) + "s",
  };
});
