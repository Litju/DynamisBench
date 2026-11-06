/**
 * The timeline: transport, readout, the phase strip and the graduated track with its playhead.
 *
 * The track is the recording's one clock made visible. It is a real slider (keyboard: ← →
 * frame, PageUp/PageDown ten frames, Home/End), and a pointer on it seeks. Phases are the
 * recording's commanded phases (the controller's schedule) over the measured phases
 * (segmented from the motion itself) — two published facts, shown one above the other.
 */

import { Pause, Play, Repeat, SkipBack, SkipForward, StepBack, StepForward } from "lucide-react";
import { useRef, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";

import { measuredPhases } from "../api/laboratory-decode";
import { useLabData } from "./data";
import { phaseWash } from "./palette";
import { at, formatNumber, niceTicks } from "./series";
import { SPEEDS, useLaboratoryStore, type Speed } from "./store";

const SPEED_LABELS: Record<Speed, string> = { 0.25: "¼×", 0.5: "½×", 1: "1×", 2: "2×" };

export function Timeline() {
  const { recording, frames } = useLabData();
  const frame = useLaboratoryStore((state) => state.frame);
  const playing = useLaboratoryStore((state) => state.playing);
  const speed = useLaboratoryStore((state) => state.speed);
  const loop = useLaboratoryStore((state) => state.loop);
  const timebase = useLaboratoryStore((state) => state.timebase);
  const { togglePlay, stepFrame, seekFrame, seek, setSpeed, toggleLoop, pause } =
    useLaboratoryStore.getState();
  const trackRef = useRef<HTMLDivElement>(null);
  const time = at(frames.kinematics.t, frame);
  const duration = timebase.duration;
  const measured = measuredPhases(recording.summary);
  const fraction = (value: number) => `${(100 * Math.min(Math.max(value / Math.max(duration, 1e-9), 0), 1)).toFixed(3)}%`;

  const seekFromPointer = (clientX: number) => {
    const track = trackRef.current;
    if (track === null) {
      return;
    }
    const rect = track.getBoundingClientRect();
    const ratio = (clientX - rect.left) / Math.max(1, rect.width);
    seek(Math.min(Math.max(ratio, 0), 1) * duration);
  };
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    pause();
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.focus();
    seekFromPointer(event.clientX);
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      seekFromPointer(event.clientX);
    }
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const steps: Record<string, number> = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowDown: -1,
      ArrowUp: 1,
      PageDown: -10,
      PageUp: 10,
    };
    const step = steps[event.key];
    if (step !== undefined) {
      event.preventDefault();
      event.stopPropagation();
      stepFrame(step);
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      event.stopPropagation();
      pause();
      seekFrame(event.key === "Home" ? 0 : timebase.count - 1);
    }
  };

  const ticks = niceTicks(0, duration, 10);

  return (
    <section className="lab-timeline" aria-label="Timeline">
      <div className="lab-transport" role="group" aria-label="Transport">
        <button type="button" aria-label="First frame" title="First frame (Home)" onClick={() => { pause(); seekFrame(0); }}>
          <SkipBack size={15} aria-hidden />
        </button>
        <button type="button" aria-label="Previous frame" title="Previous frame (←)" onClick={() => stepFrame(-1)}>
          <StepBack size={15} aria-hidden />
        </button>
        <button
          type="button"
          className="lab-play"
          aria-label={playing ? "Pause" : "Play"}
          aria-pressed={playing}
          title="Play / pause (Space)"
          onClick={togglePlay}
        >
          {playing ? <Pause size={17} aria-hidden /> : <Play size={17} aria-hidden />}
        </button>
        <button type="button" aria-label="Next frame" title="Next frame (→)" onClick={() => stepFrame(1)}>
          <StepForward size={15} aria-hidden />
        </button>
        <button type="button" aria-label="Last frame" title="Last frame (End)" onClick={() => { pause(); seekFrame(timebase.count - 1); }}>
          <SkipForward size={15} aria-hidden />
        </button>
      </div>

      <div className="lab-readout" aria-live="off">
        <strong data-testid="playback-time">{formatNumber(time, 3)}</strong>
        <span>
          / {formatNumber(duration, 3)} s · frame <span data-testid="playback-frame">{frame + 1}</span> of {timebase.count}
        </span>
      </div>

      <div
        ref={trackRef}
        className="lab-track"
        role="slider"
        tabIndex={0}
        aria-label="Playback position"
        aria-valuemin={0}
        aria-valuemax={Number(duration.toFixed(3))}
        aria-valuenow={Number(time.toFixed(3))}
        aria-valuetext={`${formatNumber(time, 2)} seconds, frame ${frame + 1} of ${timebase.count}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onKeyDown={onKeyDown}
      >
        <div className="lab-phase-strip" data-kind="commanded" aria-hidden="true">
          {recording.phase_spans.map((span) => {
            const end = Math.min(duration, span.end_s + recording.sample_period_s);
            return (
              <span
                key={`${span.phase}-${span.start_s}`}
                style={{
                  left: fraction(span.start_s),
                  width: `calc(${fraction(end)} - ${fraction(span.start_s)})`,
                  background: phaseWash(span.phase, 46),
                }}
                data-phase={span.phase}
              >
                {span.phase === "return" ? "standing" : span.phase}
              </span>
            );
          })}
        </div>
        <div className="lab-phase-strip" data-kind="measured" aria-hidden="true" title="Measured phases">
          {measured.map((span) => (
            <span
              key={`${span.phase}-${span.start_s}`}
              style={{
                left: fraction(span.start_s),
                width: `calc(${fraction(span.end_s)} - ${fraction(span.start_s)})`,
                background: phaseWash(span.phase, 90),
              }}
            />
          ))}
        </div>
        <div className="lab-graduation" aria-hidden="true">
          {ticks.map((tick) => (
            <span key={tick} style={{ left: fraction(tick) }} data-major={Number.isInteger(tick)}>
              {Number.isInteger(tick) ? <em>{tick}</em> : null}
            </span>
          ))}
          {recording.command_events.slice(1).map((event) => (
            <i key={`${event.phase}-${event.t}`} style={{ left: fraction(event.t) }} title={`${event.phase} commanded`} />
          ))}
        </div>
        <div className="lab-playhead" style={{ left: fraction(time) }} aria-hidden="true">
          <b />
        </div>
      </div>

      <div className="lab-speeds" role="group" aria-label="Playback speed">
        {SPEEDS.map((value) => (
          <button key={value} type="button" aria-pressed={speed === value} onClick={() => setSpeed(value)}>
            {SPEED_LABELS[value]}
          </button>
        ))}
        <button type="button" aria-pressed={loop} onClick={toggleLoop} title="Loop playback">
          <Repeat size={13} aria-hidden /> loop
        </button>
      </div>
    </section>
  );
}
