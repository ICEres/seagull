import { WINGS, WING_NAMES, YOUR_WING, seededRandom, type WingName } from "@seagulls/ui";

// your wings — each agent has its own fixed silhouette
export const gullPath = YOUR_WING;

export type AgentStatus = "online" | "busy" | "away";

export type AgentSpec = {
  handle: string;
  name: string;
  id: string;
  path: WingName;
  status: AgentStatus;
  size: number;
  dur: string;
  delay: string;
};

export const AGENTS: AgentSpec[] = [
  { handle: "@seagull:gulls.ai", name: "@seagull", id: "gull-seagull", path: "classic", status: "online", size: 42, dur: "3.4s", delay: "0s" },
  { handle: "@researcher:gulls.ai", name: "@researcher", id: "gull-researcher", path: "glide", status: "busy", size: 30, dur: "4.1s", delay: "0.6s" },
  { handle: "@planner:gulls.ai", name: "@planner", id: "gull-planner", path: "dip", status: "away", size: 26, dur: "4.6s", delay: "1.1s" },
  { handle: "@reviewer:gulls.ai", name: "@reviewer", id: "gull-reviewer", path: "loop", status: "online", size: 34, dur: "3.8s", delay: "0.3s" },
];

export type AmbientGullSpec = {
  key: number;
  edge: boolean;
  path: WingName;
  size: number;
  left: string;
  top: string;
  opacity: string;
  transform: string;
  dur: string;
  delay: string;
};

// Landing-local ambient layout: the hero sky needs the band-plus-edges
// distribution, which differs from the generic @seagulls/ui ambientGulls().
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
    path: WING_NAMES[Math.floor(seededRandom(i * 17 + 9) * WING_NAMES.length)],
    size: Math.round(12 + seededRandom(i * 3 + 3) * 14),
    left: x.toFixed(1) + "%",
    top: y.toFixed(1) + "%",
    opacity: (0.14 + seededRandom(i * 9 + 6) * 0.2).toFixed(2),
    transform: "translate(-50%,-50%) rotate(" + rot + "deg) scale(" + sx + ",1)",
    dur: (3 + seededRandom(i * 5 + 4) * 2.6).toFixed(1) + "s",
    delay: (seededRandom(i * 5 + 5) * 2.4).toFixed(1) + "s",
  };
});

export { WINGS };
