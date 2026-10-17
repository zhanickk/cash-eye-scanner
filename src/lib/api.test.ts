import { describe, it, expect } from "vitest";
import {
  parseSeconds, formatTime, validateFile, isSafeHttpUrl, VERDICT_LABEL,
  parseJobResponse, frameDataUrl,
} from "./api";

describe("api helpers", () => {
  it("accepts only .mov", () => {
    expect(validateFile(new File(["x"], "a.MOV"))).toBeNull();
    expect(validateFile(new File(["x"], "a.mp4"))).not.toBeNull();
  });
  it("parses timecodes", () => {
    expect(parseSeconds("01:05")).toBe(65);
    expect(parseSeconds(12.5)).toBe(12.5);
    expect(formatTime(3725)).toBe("1:02:05");
  });
  it("keeps exact verdict keys", () => {
    expect(Object.keys(VERDICT_LABEL).sort()).toEqual(["no_violation", "violation"]);
  });
  it("parses the jury violations schema and evidence frames", () => {
    expect(parseJobResponse({
      job_id: "job-1", status: "done", verdict: "violation",
      violations: [{ type: "cash handling", timecode_sec: 42.5, description: "Observed action",
        evidence_frames: [{ timestamp_sec: 43, image_base64: "YWJj" }] }],
    })).toMatchObject({ violations: [{ timecode_sec: 42.5, evidence_frames: [{ timestamp_sec: 43, image_base64: "YWJj" }] }] });
  });
  it("rejects the old events/timestamp/frames schema", () => {
    expect(() => parseJobResponse({ job_id: "job-1", status: "done", verdict: "violation", events: [{ timestamp: 42.5, frames: ["/frame.jpg"] }] })).toThrow();
  });
  it("builds an image data URL for raw base64 and keeps an existing data URL", () => {
    expect(frameDataUrl("YWJj")).toBe("data:image/jpeg;base64,YWJj");
    expect(frameDataUrl("data:image/png;base64,YWJj")).toBe("data:image/png;base64,YWJj");
  });
  it("rejects unsafe links", () => {
    expect(isSafeHttpUrl("javascript:alert(1)")).toBe(false);
    expect(isSafeHttpUrl("https://adilet.zan.kz")).toBe(true);
  });
});
