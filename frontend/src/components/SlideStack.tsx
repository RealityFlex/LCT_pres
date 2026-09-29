import { Icon20CheckCircleOn } from "@vkontakte/icons";
import { AnimatePresence, motion, useMotionValue, useSpring, useTransform, type MotionValue } from "motion/react";
import { useEffect, useState } from "react";

const CHIPS = [
  "Цвета компании",
  "Шрифты шаблона",
  "Логотип на месте",
  "Редактируемый PPTX",
  "Текст читается",
  "Цифры из брифа",
];

function FakeSlide({ tone }: { tone: number }) {
  const dark = tone % 2 === 0;
  return (
    <div className="flex h-full w-full flex-col p-[6%]" style={{ background: dark ? "#0b1b33" : "#f7f9fc" }}>
      <div className="mb-[5%] h-[7%] w-[46%] rounded" style={{ background: dark ? "#ffffff" : "#0b1b33", opacity: 0.9 }} />
      <div className="mb-[8%] h-[4%] w-[30%] rounded" style={{ background: "#0077FF" }} />
      <div className="grid flex-1 grid-cols-3 gap-[4%]">
        {[0, 1, 2].map((k) => (
          <div key={k} className="flex flex-col gap-[10%] rounded-lg p-[8%]" style={{ background: dark ? "rgba(255,255,255,.07)" : "#fff", boxShadow: dark ? "none" : "0 4px 14px rgba(0,40,120,.08)" }}>
            <div className="size-[22%] rounded-full" style={{ background: ["#0077FF", "#735CE6", "#E03FAB"][k], opacity: 0.85 }} />
            <div className="h-[10%] w-[80%] rounded" style={{ background: dark ? "rgba(255,255,255,.7)" : "#1c2433" }} />
            <div className="h-[7%] w-full rounded opacity-40" style={{ background: dark ? "#fff" : "#1c2433" }} />
            <div className="h-[7%] w-[70%] rounded opacity-40" style={{ background: dark ? "#fff" : "#1c2433" }} />
          </div>
        ))}
      </div>
    </div>
  );
}

function Card({ src, i, n, rx, ry }: { src?: string; i: number; n: number; rx: MotionValue<number>; ry: MotionValue<number> }) {
  const depth = n - 1 - i; // 0 — передний
  const x = `${-depth * 6}%`;
  const y = `${-depth * 8}%`;
  return (
    <div
      className="absolute left-[6%] top-[22%] w-[88%] animate-float"
      style={{ zIndex: 10 - depth, transformStyle: "preserve-3d", animationDelay: `${-depth * 1.3}s`, animationDuration: `${6 + depth}s` }}
    >
      <motion.div
        className="slide-3d relative w-full"
        style={{ aspectRatio: "16 / 9", rotateX: rx, rotateY: ry, x, y, z: -depth * 70 }}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 - depth * 0.16 }}
        transition={{ duration: 0.8, delay: 0.15 * i }}
      >
        <div className={depth === 0 ? "scan-wrap h-full w-full" : "h-full w-full"}>
          {src ? <img src={src} alt="" className="h-full w-full object-cover" /> : <FakeSlide tone={i} />}
        </div>
      </motion.div>
    </div>
  );
}

export function SlideStack({ images, className }: { images: string[]; className?: string }) {
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const sx = useSpring(mx, { stiffness: 60, damping: 16 });
  const sy = useSpring(my, { stiffness: 60, damping: 16 });
  const ry = useTransform(sx, (v) => -16 + v * 10);
  const rx = useTransform(sy, (v) => 10 - v * 7);
  const [chip, setChip] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setChip((c) => (c + 1) % CHIPS.length), 2200);
    const on = (e: PointerEvent) => {
      mx.set((e.clientX / window.innerWidth) * 2 - 1);
      my.set((e.clientY / window.innerHeight) * 2 - 1);
    };
    window.addEventListener("pointermove", on);
    return () => {
      clearInterval(t);
      window.removeEventListener("pointermove", on);
    };
  }, [mx, my]);

  const pics = images.slice(0, 4);
  const n = Math.max(3, pics.length);
  const cards = Array.from({ length: n }, (_, k) => pics[k]);
  const spots = [
    { left: "0%", top: "12%" },
    { right: "0%", top: "20%" },
    { left: "2%", bottom: "12%" },
    { right: "2%", bottom: "6%" },
  ];
  return (
    <div className={`relative ${className ?? ""}`}>
      <div className="stage-3d absolute inset-0">
        <div className="absolute inset-[8%] rounded-[40%] bg-[radial-gradient(circle,color-mix(in_srgb,var(--brand)_35%,transparent),transparent_65%)] blur-2xl" />
        {cards.map((src, k) => (
          <Card key={k} src={src} i={k} n={n} rx={rx} ry={ry} />
        ))}
      </div>
      <AnimatePresence mode="popLayout">
        <motion.div
          key={chip}
          className="glass-strong absolute z-30 flex items-center gap-2 rounded-full px-3.5 py-2 text-[13px] font-semibold"
          style={spots[chip % spots.length]}
          initial={{ opacity: 0, y: 10, scale: 0.9 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -8, scale: 0.95 }}
          transition={{ type: "spring", stiffness: 300, damping: 24 }}
        >
          <Icon20CheckCircleOn className="text-ok" />
          {CHIPS[chip]}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
